-- Table for the Gemini provider (LLM_PROVIDER=gemini). Run once in Supabase -> SQL Editor.
-- Gemini and OpenAI embeddings are not comparable, so they live in separate tables.
create table if not exists documents_gemini (
  id bigint generated always as identity primary key,
  url text not null,
  chunk_index integer not null,
  content text not null,
  embedding jsonb,
  domain text,
  created_at timestamptz not null default now()
);
create index if not exists documents_gemini_url_idx on documents_gemini (url);
create index if not exists documents_gemini_domain_idx on documents_gemini (domain);
alter table documents_gemini enable row level security;
