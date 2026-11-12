"""
Copy the knowledge base into the Gemini table, re-embedding each chunk with Gemini.

No web scraping or search credits are used: chunk text is read from the existing
`documents` table (OpenAI era) and only the embeddings are recomputed.
Safe to re-run; chunks already present in the target table are skipped.

Usage:  LLM_PROVIDER=gemini python migrate_to_gemini.py
"""

import os
import sys
import time

os.environ.setdefault("LLM_PROVIDER", "gemini")

from supabase import create_client  # noqa: E402

import llm  # noqa: E402

if llm.PROVIDER != "gemini":
    sys.exit("Set LLM_PROVIDER=gemini in .env (or the environment) first.")
if llm.missing_env():
    sys.exit(f"Missing in .env: {llm.missing_env()}")

SOURCE = os.getenv("SOURCE_TABLE", "documents")
TARGET = llm.TABLE
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
PAGE = 500


def fetch_all(table, columns):
    rows, start = [], 0
    while True:
        for attempt in range(5):
            try:
                page = sb.table(table).select(columns).order("id").range(start, start + PAGE - 1).execute().data or []
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 4:
                    raise
                time.sleep(1 + attempt)
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        start += PAGE


def main():
    print(f"Reading chunks from `{SOURCE}` ...")
    src = fetch_all(SOURCE, "id, url, chunk_index, content, domain")
    print(f"  {len(src)} chunks")
    try:
        done = {(r["url"], r["chunk_index"]) for r in fetch_all(TARGET, "id, url, chunk_index")}
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Cannot read `{TARGET}` - did you run schema_gemini.sql? ({str(exc)[:150]})")
    todo = [r for r in src if (r["url"], r["chunk_index"]) not in done]
    print(f"  {len(done)} already migrated, {len(todo)} to go")

    batch_size = 50
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        embeddings = llm.embed_texts([r["content"][:6000] for r in batch])
        rows = [
            {
                "url": r["url"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "embedding": emb,
                "domain": r.get("domain"),
            }
            for r, emb in zip(batch, embeddings)
        ]
        sb.table(TARGET).insert(rows).execute()
        print(f"  migrated {min(i + batch_size, len(todo))}/{len(todo)}", flush=True)
    print("Done.")


if __name__ == "__main__":
    main()
