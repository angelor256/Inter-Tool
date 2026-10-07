"""Tests de /api/chat con OpenAI y Supabase simulados (no requieren credenciales)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main


class FakeOpenAI:
    def __init__(self):
        self.chat_calls = []
        self.embeddings = SimpleNamespace(create=self._embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._complete))

    async def _embed(self, **kw):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * 1536)])

    async def _complete(self, **kw):
        self.chat_calls.append(kw["messages"])
        msg = SimpleNamespace(content="Respuesta del modelo")
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
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    monkeypatch.setattr(main, "create_client", lambda *a: FakeSupabase([0.9, 0.8, 0.5]))
    monkeypatch.setattr(main, "AsyncOpenAI", lambda **kw: FakeOpenAI())
    with TestClient(main.app) as c:
        yield c


def post(c, msg="hola", sid="s1"):
    return c.post("/api/chat", json={"message": msg, "session_id": sid})


def test_answers_with_only_relevant_chunks(client):
    r = post(client).json()
    assert r["answer"] == "Respuesta del modelo" and r["answered_from_context"]
    assert [s["chunk_index"] for s in r["sources"]] == [0, 1]  # 0.5 descartado
    prompt = client.app.state.openai.chat_calls[0]
    assert "texto 0" in prompt[-1]["content"] and "texto 2" not in prompt[-1]["content"]


def test_low_score_skips_llm(client):
    client.app.state.supabase.scores = [0.74, 0.3, 0.1]
    r = post(client).json()
    assert r["answer"] == main.NO_INFO_MESSAGE and not r["answered_from_context"]
    assert client.app.state.openai.chat_calls == []


def test_history_is_sent_on_second_turn(client):
    post(client, "primera")
    post(client, "segunda")
    second = client.app.state.openai.chat_calls[1]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == "primera"  # el historial no incluye el contexto


def test_sessions_are_isolated_and_bounded():
    s = main.SessionStore(max_turns=2, max_sessions=2)
    for i in range(5):
        s.add_turn("a", f"u{i}", f"a{i}")
    assert len(s.get("a")) == 4 and s.get("a")[0]["content"] == "u3"
    s.add_turn("b", "x", "y"); s.add_turn("c", "x", "y")
    assert s.get("a") == [] and s.get("b") and s.get("c")


def test_validation(client):
    assert client.post("/api/chat", json={"message": "", "session_id": "s"}).status_code == 422
