"""
One place for every LLM / embedding call, so the app can run on either provider.

Select with LLM_PROVIDER in .env:
  openai (default) - OpenAI Responses API + text-embedding-3-small
  gemini           - Google Gemini via its OpenAI-compatible endpoint

Embeddings from different providers are NOT comparable, so each provider reads and
writes its own table (DOCUMENTS_TABLE; defaults to `documents` for OpenAI and
`documents_gemini` for Gemini).
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
if PROVIDER not in {"openai", "gemini"}:
    raise ValueError("LLM_PROVIDER must be 'openai' or 'gemini'.")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

if PROVIDER == "gemini":
    API_KEY_NAME = "GEMINI_API_KEY"
    API_KEY = os.getenv(API_KEY_NAME)
    CHAT_MODELS = [
        m.strip()
        for m in os.getenv(
            "GEMINI_CHAT_MODEL",
            "gemini-3.1-flash-lite,gemini-flash-lite-latest,gemini-3-flash-preview",
        ).split(",")
        if m.strip()
    ]
    EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    EMBEDDING_DIMS: Optional[int] = int(os.getenv("GEMINI_EMBEDDING_DIMS", "768"))
    TABLE = os.getenv("DOCUMENTS_TABLE", "documents_gemini")
    client = OpenAI(api_key=API_KEY or "missing", base_url=GEMINI_BASE_URL, timeout=45.0, max_retries=0)
else:
    API_KEY_NAME = "OPENAI_API_KEY"
    API_KEY = os.getenv(API_KEY_NAME)
    CHAT_MODELS = [os.getenv("OPENAI_MODEL", "gpt-4.1-mini")]
    EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMS = None
    TABLE = os.getenv("DOCUMENTS_TABLE", "documents")
    client = OpenAI(api_key=API_KEY or "missing")

EMBED_BATCH = 64

# Embeddings can come from the chat provider or run locally (free, no quota, no network).
# Local is the default with Gemini because its free tier caps embeddings at 1,000/day.
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local" if PROVIDER == "gemini" else PROVIDER).strip().lower()
LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from fastembed import TextEmbedding  # imported lazily so OpenAI-only setups don't need it

        cache = os.getenv("FASTEMBED_CACHE", os.path.join(os.path.dirname(__file__), ".cache", "fastembed"))
        _local_model = TextEmbedding(model_name=LOCAL_EMBEDDING_MODEL, cache_dir=cache)
    return _local_model


def missing_env(extra: Optional[List[str]] = None) -> List[str]:
    """Names of required variables that are unset for the active provider."""
    needed = [API_KEY_NAME, "SUPABASE_URL", "SUPABASE_KEY"] + (extra or [])
    return [name for name in needed if not os.getenv(name)]


def _retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("429", "503", "500", "rate", "quota", "overloaded", "high demand", "timeout", "connection", "nodename"))


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed many texts, batching and backing off on rate limits."""
    if EMBEDDING_PROVIDER == "local":
        return [v.tolist() for v in _get_local_model().embed(texts, batch_size=EMBED_BATCH)]
    out: List[List[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        kwargs: Dict[str, Any] = {"model": EMBEDDING_MODEL, "input": batch}
        if EMBEDDING_DIMS:
            kwargs["dimensions"] = EMBEDDING_DIMS
        for attempt in range(15):
            try:
                resp = client.embeddings.create(**kwargs)
                out.extend(item.embedding for item in resp.data)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 14 or not _retryable(exc):
                    raise
                # Free-tier limits reset per minute, so wait long enough for the window to roll over.
                time.sleep(min(10 * (attempt + 1), 65) if "429" in str(exc) else min(2 ** attempt, 30))
    return out


def embed_one(text: str) -> List[float]:
    """Embed a search query (BGE models use a query instruction prefix)."""
    if EMBEDDING_PROVIDER == "local":
        return next(iter(_get_local_model().query_embed(text))).tolist()
    return embed_texts([text])[0]


def chat_text(
    messages: List[Dict[str, str]],
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """Return the model's reply; stream deltas to on_token when given."""
    if PROVIDER == "openai":
        model = CHAT_MODELS[0]
        if on_token is None:
            return client.responses.create(model=model, input=messages).output_text.strip()
        parts: List[str] = []
        stream = client.responses.create(model=model, input=messages, stream=True)
        for event in stream:
            if getattr(event, "type", "") == "response.output_text.delta":
                parts.append(event.delta)
                on_token(event.delta)
        return "".join(parts).strip()

    # Gemini: try each configured model until one answers (some are briefly overloaded).
    last_exc: Optional[Exception] = None
    for model in CHAT_MODELS:
        emitted = False
        try:
            if on_token is None:
                resp = client.chat.completions.create(model=model, messages=messages)
                return (resp.choices[0].message.content or "").strip()
            parts = []
            stream = client.chat.completions.create(model=model, messages=messages, stream=True)
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    emitted = True
                    parts.append(delta)
                    on_token(delta)
            return "".join(parts).strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if emitted:  # already streamed part of an answer; don't mix models
                raise
            continue
    raise last_exc  # type: ignore[misc]
