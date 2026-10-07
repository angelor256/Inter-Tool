"""
tools.py — Herramientas (function calling) que el modelo puede invocar.

Cada herramienta tiene:
    - un esquema JSON (lo que ve el modelo, en TOOLS)
    - una implementación Python (registrada en _HANDLERS)
`execute_tool` es el único punto de entrada: valida los argumentos, ejecuta la
herramienta y devuelve SIEMPRE un string JSON (los errores también, para que el
modelo pueda explicarlos al usuario en lugar de romper la petición).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Estado compartido durante UNA petición
# --------------------------------------------------------------------------- #
@dataclass
class ToolContext:
    tools_used: list[str] = field(default_factory=list)
    escalation_reason: str | None = None  # lo rellena escalar_a_humano


# --------------------------------------------------------------------------- #
# Esquemas que se envían a OpenAI
# --------------------------------------------------------------------------- #
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_estado_pedido",
            "description": (
                "Consulta el estado de un pedido por su número. Úsala cuando el cliente "
                "pregunte por el estado, envío o ubicación de un pedido. Si el cliente no "
                "ha dado el número de pedido, pídeselo en lugar de inventarlo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Número de pedido, p. ej. 'A1001'."}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalar_a_humano",
            "description": (
                "Deriva la conversación a un agente humano. Úsala cuando el cliente pida "
                "explícitamente hablar con una persona/agente, o cuando esté muy molesto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string", "description": "Motivo breve de la derivación."}
                },
                "required": ["motivo"],
            },
        },
    },
]

# --------------------------------------------------------------------------- #
# Implementaciones
# --------------------------------------------------------------------------- #
# Base de datos de pedidos SIMULADA. En producción, sustituir por una llamada a tu
# sistema de pedidos y comprobar que el pedido pertenece al cliente de la sesión
# (si no, cualquiera podría consultar pedidos ajenos adivinando números).
_FAKE_ORDERS = {
    "A1001": {"status": "En preparación", "eta": "2026-10-10", "carrier": None},
    "A1002": {"status": "Enviado", "eta": "2026-10-09", "carrier": "DHL", "tracking": "JD0146000123"},
    "A1003": {"status": "Entregado", "eta": None, "carrier": "Correos"},
}
_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9-]{3,20}$")


async def consultar_estado_pedido(order_id: str, ctx: ToolContext) -> dict:
    order_id = order_id.strip().upper()
    if not _ORDER_ID_RE.match(order_id):
        return {"error": "Formato de número de pedido inválido"}
    order = _FAKE_ORDERS.get(order_id)
    if order is None:
        return {"found": False, "order_id": order_id}
    return {"found": True, "order_id": order_id, **order}


async def escalar_a_humano(motivo: str, ctx: ToolContext) -> dict:
    ctx.escalation_reason = motivo.strip()[:300] or "solicitud del usuario"
    return {"ok": True, "detalle": "Un agente humano será notificado y contactará al cliente."}


_HANDLERS = {
    "consultar_estado_pedido": consultar_estado_pedido,
    "escalar_a_humano": escalar_a_humano,
}


async def execute_tool(name: str, raw_arguments: str, ctx: ToolContext) -> str:
    """Ejecuta la herramienta pedida por el modelo y devuelve un string JSON."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Herramienta desconocida: {name}"})
    try:
        args = json.loads(raw_arguments or "{}")
        result = await handler(**args, ctx=ctx)
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Argumentos inválidos"})
    ctx.tools_used.append(name)
    return json.dumps(result, ensure_ascii=False)
