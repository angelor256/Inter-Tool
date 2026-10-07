-- =============================================================================
-- Esquema RAG para Supabase (pgvector)
-- Ejecutar en: Supabase Dashboard -> SQL Editor
-- =============================================================================

-- 1. Habilitar la extensión pgvector (en Supabase vive en el schema "extensions")
create extension if not exists vector with schema extensions;

-- 2. Tabla de fragmentos (chunks) de documentos
--    text-embedding-3-small devuelve vectores de 1536 dimensiones.
create table if not exists public.documents (
    id           bigserial primary key,
    source       text        not null,                 -- nombre/ruta del documento origen
    chunk_index  integer     not null,                 -- posición del fragmento dentro del documento
    content      text        not null,                 -- texto del fragmento
    metadata     jsonb       not null default '{}'::jsonb,  -- datos libres (página, idioma, tenant...)
    embedding    extensions.vector(1536) not null,
    created_at   timestamptz not null default now(),
    unique (source, chunk_index)                       -- evita duplicados al reingerir
);

-- 3. Índice HNSW para búsqueda aproximada rápida por distancia coseno
create index if not exists documents_embedding_idx
    on public.documents
    using hnsw (embedding extensions.vector_cosine_ops);

-- 4. Índice GIN para filtrar por metadata (operador @>)
create index if not exists documents_metadata_idx
    on public.documents using gin (metadata);

-- 5. Función de búsqueda por similitud de coseno
--    similarity = 1 - distancia_coseno  (1 = idéntico, 0 = ortogonal)
create or replace function public.match_documents (
    query_embedding extensions.vector(1536),
    match_threshold float default 0.5,
    match_count     int   default 5,
    filter          jsonb default '{}'::jsonb
)
returns table (
    id          bigint,
    source      text,
    chunk_index integer,
    content     text,
    metadata    jsonb,
    similarity  float
)
language sql stable
set search_path = public, extensions
as $$
    select
        d.id,
        d.source,
        d.chunk_index,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) as similarity
    from public.documents d
    where d.metadata @> filter
      and 1 - (d.embedding <=> query_embedding) > match_threshold
    order by d.embedding <=> query_embedding   -- usa el índice HNSW
    limit match_count;
$$;

-- 6. Seguridad: el backend usa la service_role key (ignora RLS).
--    Activamos RLS sin políticas para bloquear acceso con la anon key.
alter table public.documents enable row level security;
