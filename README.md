# SmartSmith

An AI guide for people starting a small business. Ask about legal structure, funding, budgets,
taxes, planning or finding customers and get a clear answer with the sources it came from.

Built at Texas BAXA.

## How it works

- **Retrieval (RAG):** business guidance (SBA, IRS and other small-business sources) is chunked,
  embedded with OpenAI and stored in Supabase. Each question is matched against that knowledge
  base; when matches are weak, the app also searches the web with Tavily and saves relevant new
  pages back to the knowledge base.
- **Two modes:**
  - *Single agent* — one pipeline over the whole knowledge base and the web.
  - *Multi-agent* — routes the question to a legal, finance, planning or budget specialist.
- **Speed:** embeddings are cached in memory (numpy) and answers stream token by token.
- **Frontend:** React + Tailwind chat UI with streaming answers, formatted markdown and a sources panel.

## Setup

Requires Python 3.9+, Node 18+, an OpenAI key, a Tavily key and a Supabase project.

1. **Supabase:** create a project, then run [`schema.sql`](schema.sql) in the SQL Editor.
2. **Keys:** `cp .env.example .env` and fill it in.
3. **Backend:**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python prepare_db.py      # one-time: builds the knowledge base (uses OpenAI + Tavily credits)
   bash start.sh             # API on http://localhost:8000
   ```
4. **Frontend:**
   ```bash
   bash start_frontend.sh    # UI on http://localhost:3000
   ```

## Layout

| Path | Purpose |
|---|---|
| `server.py` | FastAPI app, streams answers over SSE at `POST /chat` |
| `runtime_loop.py` | Single-agent pipeline |
| `multiagent_loop.py` | Multi-agent pipeline (domain router + specialists) |
| `fast_rag.py` | In-memory embedding cache and streaming helper |
| `prepare_db.py` | Builds the knowledge base |
| `evaluate_agents.py` | Evaluation harness (results in `evaluation_outputs/`) |
| `frontend/` | React UI |
