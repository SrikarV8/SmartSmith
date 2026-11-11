-- SmartSmith / FillFlow Supabase schema.
-- Paste into Supabase Dashboard -> SQL Editor -> Run.
-- Embeddings are stored as jsonb so they come back to Python as plain lists
-- (similarity is computed in Python, not in Postgres).

create extension if not exists "pgcrypto";

create table if not exists documents (
  id bigint generated always as identity primary key,
  url text not null,
  chunk_index integer not null,
  content text not null,
  embedding jsonb,
  domain text,
  created_at timestamptz not null default now()
);
create index if not exists documents_url_idx on documents (url);
create index if not exists documents_domain_idx on documents (domain);

create table if not exists chats (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  created_at timestamptz not null default now()
);

create table if not exists conversations (
  id bigint generated always as identity primary key,
  user_id text not null,
  chat_id uuid not null references chats(id) on delete cascade,
  role text not null,
  content text not null,
  created_at timestamptz not null default now()
);
create index if not exists conversations_chat_idx on conversations (chat_id, created_at);

-- Backend uses a single server-side key; RLS is on with no policies: only the secret/service_role key can access these tables
-- (use the service_role key in .env, or leave RLS disabled).
alter table documents enable row level security;
alter table chats enable row level security;
alter table conversations enable row level security;
