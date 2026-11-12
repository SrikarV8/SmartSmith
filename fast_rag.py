"""
Speed helpers shared by the single-agent and multi-agent pipelines.

- DocCache: loads the `documents` table once (paginated, so the 1000-row
  Supabase default limit can't truncate it), keeps the embeddings in a
  normalised numpy matrix, and answers top-k queries with one matrix product
  instead of a pure-Python cosine loop over every row on every request.
- llm_text: calls the OpenAI Responses API and, when an `on_token` callback is
  given, streams tokens to it as they are generated.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

PAGE_SIZE = 150  # embeddings are large; bigger pages hit Supabase's statement timeout


class DocCache:
    def __init__(self, supabase_client: Any, table: str = "documents") -> None:
        self._sb = supabase_client
        self._table = table
        self._lock = threading.Lock()
        self._docs: List[Dict[str, Any]] = []
        self._mat: Optional[np.ndarray] = None
        self._loaded = False

    def invalidate(self) -> None:
        with self._lock:
            self._loaded = False

    def add(
        self,
        url: str,
        chunks: List[str],
        embeddings: List[List[float]],
        domain: Optional[str] = None,
    ) -> None:
        """Append freshly stored chunks without reloading the whole table."""
        from prepare_db import infer_domain

        with self._lock:
            if not self._loaded or not chunks:
                return
            new_docs = [
                {
                    "url": url,
                    "chunk_index": i,
                    "content": chunk,
                    "embedding": emb,
                    "domain": domain if domain is not None else infer_domain(url, chunk),
                }
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ]
            new_mat = np.asarray(embeddings, dtype=np.float32)
            norms = np.linalg.norm(new_mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            new_mat = new_mat / norms
            self._mat = new_mat if self._mat is None else np.vstack([self._mat, new_mat])
            self._docs = self._docs + new_docs

    def _fetch_page(self, start: int) -> List[Dict[str, Any]]:
        last_exc: Optional[Exception] = None
        for attempt in range(4):
            try:
                return (
                    self._sb.table(self._table)
                    .select("id, url, chunk_index, content, embedding, domain")
                    .order("id")
                    .range(start, start + PAGE_SIZE - 1)
                    .execute()
                    .data
                    or []
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def _load(self) -> None:
        rows: List[Dict[str, Any]] = []
        start = 0
        while True:
            page = self._fetch_page(start)
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE

        docs: List[Dict[str, Any]] = []
        vecs: List[List[float]] = []
        for row in rows:
            emb = row.get("embedding")
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except ValueError:
                    continue
            if not emb:
                continue
            row["embedding"] = emb
            docs.append(row)
            vecs.append(emb)

        if vecs:
            mat = np.asarray(vecs, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat = mat / norms
        else:
            mat = None

        self._docs, self._mat, self._loaded = docs, mat, True

    def get(self) -> Tuple[List[Dict[str, Any]], Optional[np.ndarray]]:
        with self._lock:
            if not self._loaded:
                self._load()
            return self._docs, self._mat

    def top_k(
        self,
        query_embedding: List[float],
        k: int = 5,
        domain: Optional[str] = None,
    ) -> List[Tuple[float, Dict[str, Any]]]:
        docs, mat = self.get()
        if mat is None or not docs:
            return []

        q = np.asarray(query_embedding, dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm == 0:
            return []
        scores = mat @ (q / norm)

        if domain:
            mask = np.array(
                [d.get("domain") is None or d.get("domain") == domain for d in docs]
            )
            scores = np.where(mask, scores, -np.inf)

        k = min(k, len(docs))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx])]
        return [(float(scores[i]), docs[i]) for i in idx if np.isfinite(scores[i])]

    def max_similarity(self, embedding: List[float]) -> float:
        top = self.top_k(embedding, k=1)
        return top[0][0] if top else 0.0


def llm_text(
    client: Any,
    model: str,
    messages: List[Dict[str, str]],
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """Provider-agnostic reply (client/model kept for backward compatibility)."""
    from llm import chat_text

    return chat_text(messages, on_token)


def run_in_background(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# ── Per-chat conversation context ────────────────────────────────────────────

MAX_HISTORY_MESSAGES = 20
_FOLLOW_UP_WORDS = {
    "it", "its", "that", "this", "those", "these", "they", "them", "he", "she", "there",
    "also", "again", "another", "more", "else", "first", "second", "third", "last", "previous",
    "above", "same", "instead", "then",
}


def clean_history(history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Keep only real, recent turns of THIS chat (no blanks, errors, or runaway length)."""
    cleaned: List[Dict[str, str]] = []
    for turn in history or []:
        role, content = turn.get("role"), (turn.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if content.startswith("_[error]") or content.startswith("_[generation stopped]"):
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned[-MAX_HISTORY_MESSAGES:]


def contextual_query(query: str, history: Optional[List[Dict[str, str]]]) -> str:
    """
    Build the text used for document search / routing / web search.
    A short or pronoun-heavy follow-up ("what about the second one?") is searched together
    with the previous question from the SAME chat; a self-contained question is left alone.
    """
    previous_user = [t["content"] for t in clean_history(history) if t["role"] == "user"]
    if not previous_user:
        return query
    words = [w.strip(".,!?;:'\"").lower() for w in query.split()]
    is_follow_up = len(words) <= 8 or any(w in _FOLLOW_UP_WORDS for w in words)
    if not is_follow_up:
        return query
    return f"{previous_user[-1][:300]} — follow-up: {query}"
