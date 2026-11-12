"""
FastAPI wrapper around the single-agent and multi-agent runtimes.

Run with:
    uvicorn server:app --reload --port 8000

The frontend consumes the /chat endpoint as a Server-Sent Events
stream. We run the blocking retrieval pipeline in a worker thread,
then stream the final answer token-by-token so the UI still gets a
typing effect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from functools import partial
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Literal

# ── Preflight: catch missing .env / keys before runtime_loop crashes ──────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(_env_file)

from llm import missing_env  # noqa: E402

_missing = missing_env()
if _missing:
    print("\nSmartSmith backend cannot start - missing environment variables:")
    for key in _missing:
        print(f"  {key}")
    print(f"\nAdd them to {_env_file} and restart.\n")
    sys.exit(1)
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from runtime_loop import run_single_agent
from runtime_loop_multi_agent import run_multi_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smartsmith.server")

AgentMode = Literal["single", "multi"]
ChatRole = Literal["user", "assistant"]

app = FastAPI(title="SmartSmith API", version="0.2.0")


@app.on_event("startup")
async def _warm_cache() -> None:
    import threading

    from runtime_loop import doc_cache

    threading.Thread(target=doc_cache.get, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationTurn(BaseModel):
    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    query: str
    agent_mode: AgentMode = "single"
    conversation_history: List[ConversationTurn] = Field(default_factory=list)


def _sse_event(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def _split_preserving_whitespace(text: str) -> List[str]:
    import re

    return [token for token in re.split(r"(\s+)", text) if token != ""]


async def _stream_answer(
    query: str,
    agent_mode: AgentMode,
    conversation_history: List[Dict[str, str]],
) -> AsyncGenerator[str, None]:
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[str]" = asyncio.Queue()

    def on_token(delta: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, delta)

    try:
        runner = run_multi_agent if agent_mode == "multi" else run_single_agent
        task = loop.run_in_executor(
            None,
            partial(
                runner,
                query=query,
                conversation_history=conversation_history,
                on_token=on_token,
            ),
        )

        streamed = False
        while True:
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait(
                {getter, task}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                yield _sse_event("token", json.dumps(getter.result()))
                streamed = True
                continue
            getter.cancel()
            break

        result = await task
        while not queue.empty():
            yield _sse_event("token", json.dumps(queue.get_nowait()))
            streamed = True

        answer = str(result.get("answer", "")).strip()
        source_mode = str(
            result.get("source_mode")
            or result.get("retrieval_mode")
            or "hybrid"
        )
        citations = result.get("citations") or []

        if not streamed:
            for token in _split_preserving_whitespace(answer):
                yield _sse_event("token", json.dumps(token))

        yield _sse_event(
            "final",
            {
                "answer": answer,
                "source_mode": source_mode,
                "citations": citations,
                "agent_mode": agent_mode,
            },
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat pipeline error")
        yield _sse_event("error", {"message": str(exc)})


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "smartsmith",
        "agent_modes": ["single", "multi"],
    }


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    query = (req.query or "").strip()
    if not query:

        async def empty() -> AsyncGenerator[str, None]:
            yield _sse_event("error", {"message": "Empty query"})

        return StreamingResponse(empty(), media_type="text/event-stream")

    conversation_history = [
        {"role": turn.role, "content": turn.content}
        for turn in req.conversation_history
        if turn.content.strip()
    ]

    return StreamingResponse(
        _stream_answer(query, req.agent_mode, conversation_history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
