"""
escalation.py — Notificación a agentes humanos mediante webhook.

El payload incluye `text` (compatible con webhooks entrantes de Slack/Teams/Discord*)
y los campos estructurados para sistemas propios (Zapier, n8n, tu helpdesk...).
(*Discord espera "content"; usa un adaptador si es tu caso.)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

log = logging.getLogger("escalation")


async def notify_human_agent(
    session_id: str, reason: str, last_message: str, transcript: list[dict]
) -> None:
    """
    Envía el aviso de escalación. Nunca lanza excepciones: se ejecuta en segundo
    plano y un fallo del webhook no debe afectar a la respuesta del cliente.
    """
    url = os.getenv("ESCALATION_WEBHOOK_URL")
    if not url:
        log.warning("ESCALATION_WEBHOOK_URL no configurada; escalación solo registrada: session=%s motivo=%s",
                    session_id, reason)
        return

    payload = {
        "text": f"Escalación a humano — sesión {session_id}\nMotivo: {reason}\nÚltimo mensaje: {last_message}",
        "session_id": session_id,
        "reason": reason,
        "last_message": last_message,
        "transcript": transcript,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        log.info("Escalación enviada: session=%s", session_id)
    except httpx.HTTPError:
        log.exception("Fallo al enviar el webhook de escalación: session=%s", session_id)
