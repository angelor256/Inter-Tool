"""
llm_config.py — Proveedor de IA (embeddings + chat), compartido por ingest.py y main.py.

Ambos proveedores se usan con el SDK de OpenAI (Gemini expone un endpoint compatible),
así que cambiar de uno a otro es solo cuestión de variables de entorno:

    LLM_PROVIDER=openai   (por defecto)  -> OPENAI_API_KEY
    LLM_PROVIDER=gemini                  -> GEMINI_API_KEY

Overrides opcionales: LLM_BASE_URL, EMBEDDING_MODEL, CHAT_MODEL, SIMILARITY_THRESHOLD.

IMPORTANTE: los vectores de proveedores distintos NO son comparables. Si cambias de
proveedor, borra los datos (`truncate documents;`) y vuelve a ejecutar la ingesta.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()  # antes de leer cualquier variable (este módulo se importa primero)

# Tamaño fijo de los vectores: debe coincidir con `vector(1536)` de sql/schema.sql.
# Se pide explícitamente a la API, así la tabla no cambia al usar Gemini.
EMBEDDING_DIM = 1536

_PRESETS = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "embedding_model": "text-embedding-3-small",
        "chat_model": "gpt-4o",
        "similarity_threshold": 0.75,
    },
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "embedding_model": "gemini-embedding-001",
        "chat_model": "gemini-2.5-flash",
        # Los scores de coseno de Gemini suelen ser menores que los de OpenAI;
        # punto de partida a ajustar mirando los scores que imprime el servidor.
        "similarity_threshold": 0.65,
    },
}

PROVIDER = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
if PROVIDER not in _PRESETS:
    sys.exit(f"LLM_PROVIDER inválido: {PROVIDER!r}. Usa 'openai' o 'gemini'.")
_preset = _PRESETS[PROVIDER]

API_KEY_ENV: str = _preset["api_key_env"]
BASE_URL: str | None = os.getenv("LLM_BASE_URL") or _preset["base_url"]
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL") or _preset["embedding_model"]
CHAT_MODEL: str = os.getenv("CHAT_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or _preset["chat_model"]
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD") or _preset["similarity_threshold"])


def client_kwargs() -> dict:
    """Argumentos para OpenAI() / AsyncOpenAI() según el proveedor elegido."""
    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        sys.exit(f"Falta la variable de entorno {API_KEY_ENV} (LLM_PROVIDER={PROVIDER}; ver .env.example)")
    kwargs = {"api_key": api_key}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return kwargs
