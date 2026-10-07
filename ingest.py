"""
ingest.py — Fase 1 del pipeline RAG: ingesta de documentos.

Flujo:  archivo (.txt/.md/.pdf) -> texto -> chunks (400 palabras, solape 50)
        -> embeddings (OpenAI text-embedding-3-small) -> Supabase (pgvector)

Uso:
    python ingest.py docs/manual.pdf docs/faq.txt
    python ingest.py docs/            # procesa recursivamente una carpeta

Variables de entorno (ver .env.example):
    OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Iterator

from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader
from supabase import Client, create_client
from tenacity import retry, stop_after_attempt, wait_exponential

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensiones
CHUNK_SIZE_WORDS = 400
CHUNK_OVERLAP_WORDS = 50
EMBED_BATCH_SIZE = 100    # textos por petición a OpenAI
INSERT_BATCH_SIZE = 100   # filas por inserción en Supabase
SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}

log = logging.getLogger("ingest")


# --------------------------------------------------------------------------- #
# 1. Lectura de documentos
# --------------------------------------------------------------------------- #
def read_pdf(path: Path) -> str:
    """Extrae el texto de todas las páginas de un PDF."""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_text(path: Path) -> str:
    """Lee un archivo de texto plano (UTF-8, tolerante a errores)."""
    return path.read_text(encoding="utf-8", errors="replace")


def load_document(path: Path) -> str:
    """Devuelve el texto de un documento según su extensión."""
    return read_pdf(path) if path.suffix.lower() == ".pdf" else read_text(path)


def discover_files(inputs: Iterable[str]) -> Iterator[Path]:
    """Expande archivos y carpetas (recursivo) a archivos soportados."""
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(
                f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file():
            yield p
        else:
            log.warning("Ignorado (no existe o extensión no soportada): %s", p)


# --------------------------------------------------------------------------- #
# 2. Chunking
# --------------------------------------------------------------------------- #
def chunk_words(
    text: str,
    chunk_size: int = CHUNK_SIZE_WORDS,
    overlap: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """
    Divide `text` en ventanas de `chunk_size` palabras con `overlap` palabras
    compartidas entre fragmentos consecutivos (paso = chunk_size - overlap).
    """
    if overlap >= chunk_size:
        raise ValueError("overlap debe ser menor que chunk_size")

    words = text.split()
    step = chunk_size - overlap
    chunks: list[str] = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + chunk_size]))
        if start + chunk_size >= len(words):  # la ventana ya cubre el final
            break
    return chunks


# --------------------------------------------------------------------------- #
# 3. Embeddings
# --------------------------------------------------------------------------- #
@retry(wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(5))
def _embed_batch(client: OpenAI, batch: list[str]) -> list[list[float]]:
    """Una llamada a la API de embeddings, con reintentos ante rate limits/errores."""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
    # La API garantiza el orden, pero ordenamos por índice por seguridad.
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Calcula embeddings para `texts` en lotes."""
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        embeddings.extend(_embed_batch(client, texts[i : i + EMBED_BATCH_SIZE]))
    return embeddings


# --------------------------------------------------------------------------- #
# 4. Almacenamiento en Supabase
# --------------------------------------------------------------------------- #
def store_chunks(
    supabase: Client,
    source: str,
    chunks: list[str],
    embeddings: list[list[float]],
    metadata: dict | None = None,
) -> None:
    """
    Guarda los chunks de un documento. Es idempotente: borra primero los
    fragmentos previos del mismo `source`, así reingerir un archivo actualizado
    no deja datos obsoletos.
    """
    supabase.table("documents").delete().eq("source", source).execute()

    rows = [
        {
            "source": source,
            "chunk_index": idx,
            "content": content,
            "metadata": metadata or {},
            "embedding": embedding,
        }
        for idx, (content, embedding) in enumerate(zip(chunks, embeddings))
    ]
    for i in range(0, len(rows), INSERT_BATCH_SIZE):
        supabase.table("documents").insert(rows[i : i + INSERT_BATCH_SIZE]).execute()


# --------------------------------------------------------------------------- #
# 5. Orquestación
# --------------------------------------------------------------------------- #
def ingest_file(path: Path, openai_client: OpenAI, supabase: Client) -> int:
    """Procesa un archivo completo y devuelve el nº de chunks guardados."""
    text = load_document(path)
    chunks = chunk_words(text)
    if not chunks:
        log.warning("Sin texto extraíble: %s", path)
        return 0

    embeddings = embed_texts(openai_client, chunks)
    store_chunks(
        supabase,
        source=path.name,
        chunks=chunks,
        embeddings=embeddings,
        metadata={"filename": path.name, "type": path.suffix.lower().lstrip(".")},
    )
    return len(chunks)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Falta la variable de entorno {name} (ver .env.example)")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de documentos para RAG")
    parser.add_argument("paths", nargs="+", help="Archivos (.txt/.md/.pdf) o carpetas")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv()

    openai_client = OpenAI(api_key=require_env("OPENAI_API_KEY"))
    supabase = create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SERVICE_KEY"))

    total = 0
    for path in discover_files(args.paths):
        try:
            n = ingest_file(path, openai_client, supabase)
            log.info("%s -> %d chunks", path, n)
            total += n
        except Exception:
            log.exception("Error procesando %s", path)
    log.info("Ingesta terminada: %d chunks guardados", total)


if __name__ == "__main__":
    main()
