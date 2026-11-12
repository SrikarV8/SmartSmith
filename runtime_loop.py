import math
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential
from tavily import TavilyClient

from llm import PROVIDER, TABLE, chat_text, client, embed_one, missing_env
from prepare_db import fetch_page_text, chunk_text, embed_texts, insert_chunks
from fast_rag import DocCache, run_in_background

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if missing_env():
    raise ValueError(f"Missing required environment variables: {missing_env()}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None
doc_cache = DocCache(supabase, TABLE)


# FUNCTIONS AND THINGS USED FOR EXTRA META DATA

USER_CONTEXT = {
    "company_name": "Lone Star Candle Co.",
    "location": "Austin, Texas",
    "industry": "handmade consumer goods / e-commerce",
    "business_stage": "early-stage startup",
    "target_customer": "college students and young professionals",
    "business_goal": "grow online sales and improve customer retention",
}

def format_user_context(user_context: dict) -> str:
    print("formatting user context -> ")
    parts = []

    if user_context.get("company_name"):
        parts.append(f"Company name: {user_context['company_name']}")
    if user_context.get("location"):
        parts.append(f"Location: {user_context['location']}")
    if user_context.get("industry"):
        parts.append(f"Industry: {user_context['industry']}")
    if user_context.get("business_stage"):
        parts.append(f"Business stage: {user_context['business_stage']}")
    if user_context.get("target_customer"):
        parts.append(f"Target customer: {user_context['target_customer']}")
    if user_context.get("business_goal"):
        parts.append(f"Business goal: {user_context['business_goal']}")

    return "\n".join(parts)

def build_enriched_query(query: str, user_context_text: str) -> str:
    print("building the query with the user context -> ")
    if not user_context_text.strip():
        return query

    return f"""
User question:
{query}

Relevant user/business context:
{user_context_text}
""".strip()

#FUNCTIONS USED DURING THE RAG RETRIEVAL

def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def embed_query(query: str) -> List[float]:
    print("embedding the query -> ")
    return embed_one(query)


def get_all_documents() -> List[Dict[str, Any]]:
    print("retrieving all documents in the database -> ")
    response = supabase.table(TABLE).select("url, chunk_index, content, embedding").execute()
    return response.data or []


def retrieve_similar_chunks(query: str, top_k: int = 5) -> List[Tuple[float, Dict[str, Any]]]:
    query_embedding = embed_query(query)
    return doc_cache.top_k(query_embedding, k=top_k)


def web_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    print("searching the web -> ")
    if not tavily:
        return []

    try:
        response = tavily.search(
            query=query,
            max_results=num_results,
        )

        results = []
        for item in response.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("url", ""),
                    "snippet": item.get("content", ""),
                }
            )

        return results

    except Exception as e:
        print(f"Tavily search error: {e}")
        return []


def decide_sources(similar_chunks: List[Tuple[float, Dict[str, Any]]]) -> str:
    print("deciding what type of sources to use -> ")
    """
    Very simple heuristic:
    - high similarity => vector only
    - medium similarity => vector + google
    - low similarity => google only
    """
    if not similar_chunks:
        return "google_only"

    top_score = similar_chunks[0][0]
    strong_hits = sum(1 for score, _ in similar_chunks if score >= 0.75)

    if top_score >= 0.82 and strong_hits >= 2:
        return "vector_only"
    if top_score >= 0.65:
        return "hybrid"
    return "google_only"


def format_vector_context(similar_chunks: List[Tuple[float, Dict[str, Any]]]) -> str:
    print("formatting the vector context -> ")
    lines = []
    for score, doc in similar_chunks:
        lines.append(
            f"[Vector score={score:.3f}] URL: {doc['url']}\n"
            f"Chunk: {doc['content']}\n"
        )
    return "\n---\n".join(lines)


def format_google_context(results: List[Dict[str, str]]) -> str:
    lines = []
    print("formatting the google context -> ")
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"[Google Result {idx}] {item['title']}\n"
            f"URL: {item['link']}\n"
            f"Snippet: {item['snippet']}"
        )
    return "\n---\n".join(lines)


def build_citations(
    similar_chunks: List[Tuple[float, Dict[str, Any]]],
    google_results: List[Dict[str, str]],
    source_mode: str,
) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []

    if source_mode in {"vector_only", "hybrid"}:
        for score, doc in similar_chunks:
            citations.append(
                {
                    "title": doc.get("url", "Internal document"),
                    "url": doc.get("url", ""),
                    "snippet": (doc.get("content") or "")[:400],
                    "score": float(score),
                    "source": "vector",
                }
            )

    if source_mode in {"google_only", "hybrid"}:
        for item in google_results:
            citations.append(
                {
                    "title": item.get("title", item.get("link", "Web result")),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "source": "web",
                }
            )

    return citations

def is_relevant_to_kb(text: str, kb_embeddings: List[List[float]], threshold: float = 0.4) -> bool:
    print("deciding if its relevant to the knowledge base -> ")
    if not kb_embeddings:
        return False
    text_emb = embed_texts([text[:1000]])[0]
    return doc_cache.max_similarity(text_emb) > threshold

def maybe_store_interaction(google_results: List[Dict[str, str]]) -> None:
    print("deciding to store or not to store -> ")
    kb_embeddings = doc_cache.get()[0]

    for result in google_results:
        url = result["link"]
        try:
            # skip if already stored
            existing = supabase.table(TABLE).select("url").eq("url", url).limit(1).execute()
            if existing.data:
                continue

            text = fetch_page_text(url)
            if len(text) < 200:
                continue
            if not is_relevant_to_kb(text, kb_embeddings):
                continue

            chunks = chunk_text(text)
            embeddings = embed_texts(chunks)
            insert_chunks(url, chunks, embeddings)
            doc_cache.add(url, chunks, embeddings)
        except Exception:
            continue


def ask_llm(
    query: str,
    *args: Any,
    user_content_text: str = "",
    vector_context: str = "",
    google_context: str = "",
    source_mode: str = "hybrid",
    conversation_history: Optional[List[Dict[str, str]]] = None,
    on_token: Optional[Any] = None,
) -> str:
    print("asking the llm -> \n")
    if args:
        if len(args) == 3:
            vector_context, google_context, source_mode = args
        elif len(args) == 4:
            user_content_text, vector_context, google_context, source_mode = args
        elif len(args) == 5:
            (
                user_content_text,
                vector_context,
                google_context,
                source_mode,
                conversation_history,
            ) = args
        else:
            raise TypeError(
                "ask_llm expected 3, 4, or 5 positional arguments after query"
            )

    conversation_history = conversation_history or []

    system_prompt = f"""
You are an agentic business-assistant chatbot.

Your job:
1. Answer the user's question using the provided context.
2. Prefer the vector context when it is relevant.
3. Use web results when the vector context is missing, weak, or outdated.
4. If the answer is uncertain, say so clearly.
5. When using web results, mention the source URLs in your answer.
6. Keep the answer concise but useful.

Current retrieval mode: {source_mode}
"""

    user_prompt = f"""
User business context: 
{user_content_text if user_content_text else "None"}

User question:
{query}

Vector context:
{vector_context if vector_context else "None"}

Google context:
{google_context if google_context else "None"}
"""

    return chat_text(
        [
            {"role": "system", "content": system_prompt},
            *conversation_history,
            {"role": "user", "content": user_prompt},
        ],
        on_token,
    )


def run_chat() -> None:
    print("Agentic AI chatbot prototype")

    user_id = get_user_id()
    print(f"\nWelcome, {user_id}!")

    past_chats = get_user_chats(user_id)
    if past_chats:
        print(f"\nYour chats:")
        for i, chat in enumerate(past_chats):
            print(f"  [{i+1}] Chat from {chat['created_at'][:19]}  (id: {chat['id'][:8]}...)")
        print(f"  [N] New chat")
        choice = input("\nPick a chat or press N for new: ").strip().lower()

        if choice == "n" or not choice:
            chat_id = create_new_chat(user_id)
            conversation_history = []
            print("\nStarting new chat...\n")
        else:
            idx = int(choice) - 1
            chat_id = past_chats[idx]["id"]
            conversation_history = load_chat_history(chat_id)
            print(f"\nResuming chat ({len(conversation_history)} messages loaded)...\n")
    else:
        chat_id = create_new_chat(user_id)
        conversation_history = []
        print("\nNo previous chats found. Starting fresh...\n")

    print("Type 'exit' to quit.\n")

    while True:
        query = input("You: ").strip()
        if query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        if not query:
            continue

        try:
            user_context_text = format_user_context(USER_CONTEXT)
            enriched_query = build_enriched_query(query, user_context_text)

            similar_chunks = retrieve_similar_chunks(enriched_query, top_k=5)
            source_mode = decide_sources(similar_chunks)

            vector_context = ""
            google_context = ""
            google_results = []

            if source_mode in {"vector_only", "hybrid"}:
                vector_context = format_vector_context(similar_chunks)
            if source_mode in {"google_only", "hybrid"}:
                google_results = web_search(enriched_query, num_results=5)
                google_context = format_google_context(google_results)

            answer = ask_llm(
                query=query,
                user_content_text=user_context_text,
                vector_context=vector_context,
                google_context=google_context,
                source_mode=source_mode,
                conversation_history=conversation_history,   # ← new
            )

            maybe_store_interaction(google_results)

            save_message(user_id, chat_id, "user", query)        # ← new
            save_message(user_id, chat_id, "assistant", answer)  # ← new
            conversation_history.append({"role": "user", "content": query})
            conversation_history.append({"role": "assistant", "content": answer})

            print(f"\nAssistant ({source_mode}): {answer}\n")
        except Exception as exc:
            print(f"\nError: {exc}\n")

def get_user_id() -> str:
    user_id = input("Enter your user ID (or press Enter to use 'guest'): ").strip()
    return user_id if user_id else "guest"

def create_new_chat(user_id: str) -> str:
    response = supabase.table("chats").insert({"user_id": user_id}).execute()
    return response.data[0]["id"]

def load_chat_history(chat_id: str) -> list:
    response = (
        supabase.table("conversations")
        .select("role, content")
        .eq("chat_id", chat_id)
        .order("created_at", desc=True)
        .execute()
    )
    return list(reversed(response.data or []))

def get_user_chats(user_id: str) -> list:
    response = (
        supabase.table("chats")
        .select("id, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []

def save_message(user_id: str, chat_id: str, role: str, content: str) -> None:
    supabase.table("conversations").insert({
        "user_id": user_id,
        "chat_id": chat_id,
        "role": role,
        "content": content,
    }).execute()

def run_single_agent(
    query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    on_token: Optional[Any] = None,
) -> Dict[str, Any]:
    user_context_text = format_user_context(USER_CONTEXT)
    enriched_query = build_enriched_query(query, user_context_text)
    conversation_history = conversation_history or []

    similar_chunks = retrieve_similar_chunks(enriched_query, top_k=5)
    source_mode = decide_sources(similar_chunks)

    vector_context = ""
    google_context = ""
    google_results = []

    if source_mode in {"vector_only", "hybrid"}:
        vector_context = format_vector_context(similar_chunks)

    if source_mode in {"google_only", "hybrid"}:
        google_results = web_search(enriched_query, num_results=5)
        google_context = format_google_context(google_results)

    answer = ask_llm(
        query=query,
        user_content_text=user_context_text,
        vector_context=vector_context,
        google_context=google_context,
        source_mode=source_mode,
        conversation_history=conversation_history,
        on_token=on_token,
    )

    if google_results:
        run_in_background(maybe_store_interaction, google_results)
    citations = build_citations(similar_chunks, google_results, source_mode)

    return {
        "answer": answer,
        "domain": "general",
        "tools": [],
        "retrieval_mode": source_mode,
        "source_mode": source_mode,
        "citations": citations,
    }

if __name__ == "__main__":
    run_chat()
