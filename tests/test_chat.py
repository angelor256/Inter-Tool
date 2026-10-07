"""Tests de /api/chat con OpenAI, Supabase y webhook simulados (sin credenciales)."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main


def tool_call(name, **args):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args))
    return SimpleNamespace(id=f"call_{name}", function=fn)


class FakeOpenAI:
    """`script` es la lista de respuestas del modelo: str (texto final) o lista de tool_calls."""

    def __init__(self, script=None):
        self.script = list(script or ["Respuesta del modelo"])
        self.calls = []
        self.embeddings = SimpleNamespace(create=self._embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._complete))

    async def _embed(self, **kw):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * 1536)])

    async def _complete(self, **kw):
        self.calls.append([dict(m) for m in kw["messages"]])
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, str):
            msg = SimpleNamespace(content=step, tool_calls=None)
        else:
            msg = SimpleNamespace(content=None, tool_calls=step)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class FakeSupabase:
    def __init__(self, scores):
        self.scores = scores

    def rpc(self, name, params):
        assert name == "match_documents" and params["match_count"] == 3
        rows = [{"source": "faq.txt", "chunk_index": i, "content": f"texto {i}", "similarity": s}
                for i, s in enumerate(self.scores)]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))


@pytest.fixture
def client(monkeypatch):
    for k in ("OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        monkeypatch.setenv(k, "x")
    notified = []

    async def fake_notify(*args):
        notified.append(args)

    monkeypatch.setattr(main, "notify_human_agent", fake_notify)
    monkeypatch.setattr(main, "create_client", lambda *a: FakeSupabase([0.9, 0.8, 0.5]))
    monkeypatch.setattr(main, "AsyncOpenAI", lambda **kw: FakeOpenAI())
    with TestClient(main.app) as c:
        c.notified = notified
        yield c


def post(c, msg="hola", sid="s1"):
    return c.post("/api/chat", json={"message": msg, "session_id": sid}).json()


# --- Fase 2: RAG -----------------------------------------------------------
def test_answers_with_only_relevant_chunks(client):
    r = post(client)
    assert r["answer"] == "Respuesta del modelo" and r["answered_from_context"]
    assert not r["escalated"] and r["tools_used"] == []
    assert [s["chunk_index"] for s in r["sources"]] == [0, 1]  # 0.5 descartado
    prompt = client.app.state.openai.calls[0][-1]["content"]
    assert "texto 0" in prompt and "texto 2" not in prompt


def test_history_is_sent_on_second_turn(client):
    post(client, "primera")
    post(client, "segunda")
    second = client.app.state.openai.calls[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == "primera"


def test_sessions_are_isolated_and_bounded():
    s = main.SessionStore(max_turns=2, max_sessions=2)
    for i in range(5):
        s.add_turn("a", f"u{i}", f"a{i}")
    assert len(s.get("a")) == 4 and s.get("a")[0]["content"] == "u3"
    s.add_turn("b", "x", "y"); s.add_turn("c", "x", "y")
    assert s.get("a") == [] and s.get("b") and s.get("c")


def test_validation(client):
    assert client.post("/api/chat", json={"message": "", "session_id": "s"}).status_code == 422


# --- Fase 3: function calling ---------------------------------------------
def test_order_status_tool_roundtrip(client):
    client.app.state.supabase.scores = [0.2, 0.1, 0.1]  # sin contexto documental
    client.app.state.openai.script = [[tool_call("consultar_estado_pedido", order_id="a1002")],
                                      "Tu pedido va en camino con DHL."]
    r = post(client, "¿Dónde está mi pedido A1002?")
    assert r["answer"] == "Tu pedido va en camino con DHL."
    assert r["tools_used"] == ["consultar_estado_pedido"] and not r["escalated"]
    # el resultado de la herramienta se devolvió al modelo en la 2ª llamada
    tool_msg = client.app.state.openai.calls[1][-1]
    assert tool_msg["role"] == "tool" and "DHL" in tool_msg["content"]
    # el historial guarda solo texto, no mensajes de herramienta
    assert [m["role"] for m in client.app.state.sessions.get("s1")] == ["user", "assistant"]


def test_unknown_order_and_bad_args(client):
    import asyncio
    from tools import ToolContext, execute_tool
    ctx = ToolContext()
    run = asyncio.run
    assert json.loads(run(execute_tool("consultar_estado_pedido", '{"order_id":"ZZZ999"}', ctx)))["found"] is False
    assert "error" in json.loads(run(execute_tool("consultar_estado_pedido", '{"order_id":"../x"}', ctx)))
    assert "error" in json.loads(run(execute_tool("consultar_estado_pedido", "no-json", ctx)))
    assert "error" in json.loads(run(execute_tool("borrar_todo", "{}", ctx)))


# --- Fase 3: escalación ----------------------------------------------------
def test_user_requests_human_escalates_once(client):
    client.app.state.openai.script = [[tool_call("escalar_a_humano", motivo="pide agente")],
                                      "Te derivo con un agente."]
    r = post(client, "Quiero hablar con una persona")
    assert r["escalated"] and r["escalation_reason"] == "pide agente"
    assert len(client.notified) == 1
    session_id, reason, last_msg, transcript = client.notified[0]
    assert (session_id, reason, last_msg) == ("s1", "pide agente", "Quiero hablar con una persona")
    assert transcript[-1]["role"] == "assistant"

    # segunda petición de humano en la misma sesión: escalated=True pero sin aviso duplicado
    client.app.state.openai.script = [[tool_call("escalar_a_humano", motivo="insiste")], "Ok."]
    assert post(client, "¡Un humano ya!")["escalated"]
    assert len(client.notified) == 1


def test_low_confidence_escalates_without_trusting_model(client):
    client.app.state.supabase.scores = [0.74, 0.3, 0.1]
    client.app.state.openai.script = ["Seguro que la respuesta es 42"]  # el modelo "alucina"
    r = post(client, "pregunta rara")
    assert r["answer"].startswith(main.NO_INFO_MESSAGE) and main.HANDOFF_NOTICE in r["answer"]
    assert r["escalated"] and not r["answered_from_context"]
    assert len(client.notified) == 1 and "baja confianza" in client.notified[0][1]


def test_model_says_no_info_with_context_escalates(client):
    client.app.state.openai.script = ["No tengo esa información"]
    r = post(client)
    assert r["escalated"] and r["answered_from_context"]


def test_low_confidence_escalation_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(main, "ESCALATE_ON_LOW_CONFIDENCE", False)
    client.app.state.supabase.scores = [0.1, 0.1, 0.1]
    r = post(client)
    assert r["answer"] == main.NO_INFO_MESSAGE and not r["escalated"] and client.notified == []


def test_tool_loop_is_bounded(client):
    client.app.state.openai.script = [[tool_call("consultar_estado_pedido", order_id="A1001")]] * 10 + ["fin"]
    r = post(client)
    assert len(client.app.state.openai.calls) == main.MAX_TOOL_ROUNDS + 1
