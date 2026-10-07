import asyncio

import httpx

import escalation


def test_webhook_payload_and_failure_is_swallowed(monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(500 if len(sent) == 2 else 200)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(escalation.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    monkeypatch.setenv("ESCALATION_WEBHOOK_URL", "http://hook.test/x")

    asyncio.run(escalation.notify_human_agent("s1", "motivo", "hola", [{"role": "user", "content": "hola"}]))
    body = httpx.Response(200, content=sent[0].content).json()
    assert body["session_id"] == "s1" and body["reason"] == "motivo" and "text" in body

    # un 500 del webhook se registra pero no lanza excepción
    asyncio.run(escalation.notify_human_agent("s1", "motivo", "hola", []))


def test_no_url_configured_does_not_raise(monkeypatch):
    monkeypatch.delenv("ESCALATION_WEBHOOK_URL", raising=False)
    asyncio.run(escalation.notify_human_agent("s1", "m", "h", []))
