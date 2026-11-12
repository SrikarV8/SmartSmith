# runtime_loop_multi_agent.py

import html
import json
import math
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from dotenv import load_dotenv
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from supabase import Client, create_client
from tavily import TavilyClient

from llm import PROVIDER, TABLE, chat_text, embed_one, missing_env
from prepare_db import fetch_page_text, chunk_text, embed_texts, insert_chunks
from fast_rag import DocCache, run_in_background

load_dotenv()

# ---------------------------
# Environment
# ---------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")


if missing_env():
    raise ValueError(f"Missing required environment variables: {missing_env()}")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
from runtime_loop import doc_cache  # shared in-memory embedding cache
tavily = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None

# ---------------------------
# Static user/business metadata
# ---------------------------

USER_CONTEXT = {
    "company_name": "Lone Star Candle Co.",
    "location": "Austin, Texas",
    "industry": "handmade consumer goods / e-commerce",
    "business_stage": "early-stage startup",
    "target_customer": "college students and young professionals",
    "business_goal": "grow online sales and improve customer retention",
}

# ---------------------------
# Output directories
# ---------------------------

OUTPUT_DIR = Path("outputs")
PDF_DIR = OUTPUT_DIR / "pdf"
DOCX_DIR = OUTPUT_DIR / "docx"
EMAIL_DIR = OUTPUT_DIR / "email"
IMAGE_DIR = OUTPUT_DIR / "image"

for directory in [OUTPUT_DIR, PDF_DIR, DOCX_DIR, EMAIL_DIR, IMAGE_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Prompts / routing config
# ---------------------------

DOMAIN_SYSTEM_PROMPTS = {
    "legal": (
        "You are the Legal Agent for a business-creation assistant. "
        "Focus on business formation, permits, compliance, filings, risk, and next legal steps. "
        "Be practical. Do not give false certainty."
    ),
    "finance": (
        "You are the Finance Agent for a business-creation assistant. "
        "Focus on funding, pricing, revenue model, margins, taxes at a high level, and financial tradeoffs."
    ),
    "planning": (
        "You are the Planning Agent for a business-creation assistant. "
        "Focus on business idea validation, customer segments, value proposition, launch sequencing, and roadmaps."
    ),
    "budget": (
        "You are the Budget Agent for a business-creation assistant. "
        "Focus on startup costs, operating expenses, budget ranges, cost categories, and simple cost planning."
    ),
    "general": (
        "You are the General Research Agent for a business-creation assistant. "
        "Use available context to answer clearly and practically. "
        "If context is weak, say what is uncertain."
    ),
}

DOMAIN_KEYWORDS = {
    "legal": [
        "llc", "incorporate", "inc", "sole proprietorship", "partnership",
        "legal", "permit", "license", "registration", "registered agent",
        "compliance", "trademark", "terms", "privacy policy", "tax id", "ein"
    ],
    "finance": [
        "funding", "revenue", "profit", "margin", "pricing", "finance",
        "break even", "break-even", "investor", "loan", "cash flow", "sales forecast"
    ],
    "planning": [
        "plan", "planning", "validate", "business idea", "roadmap", "strategy",
        "go to market", "go-to-market", "customer", "target market", "persona",
        "launch", "mvp", "positioning"
    ],
    "budget": [
        "budget", "cost", "expenses", "startup costs", "opex",
        "capex", "how much will it cost", "spend", "afford"
    ],
}

TOOL_PATTERNS = {
    "pdf": [r"\bpdf\b", r"export.*pdf", r"save.*pdf", r"download.*pdf"],
    "docx": [r"\bdocx\b", r"\bword\b", r"export.*docx", r"save.*docx"],
    "email": [r"\bemail\b", r"send.*email", r"draft.*email", r"mail this"],
    "image": [r"\bimage\b", r"\bgraphic\b", r"\blogo\b", r"\bicon\b", r"\bmockup\b", r"\billustration\b"],
}

EXPORT_ONLY_PATTERNS = [
    "export this",
    "save this",
    "turn this into",
    "make this a pdf",
    "make this into a pdf",
    "make this a docx",
    "make this into a docx",
    "email this",
    "make an image of this",
    "create an image of this",
]

# ---------------------------
# User context helpers
# ---------------------------

def format_user_context(user_context: dict) -> str:
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
    if not user_context_text.strip():
        return query

    return f"""
User question:
{query}

Relevant user/business context:
{user_context_text}
""".strip()

# ---------------------------
# Chat memory helpers
# ---------------------------

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

# ---------------------------
# General helpers
# ---------------------------

def slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len] or "output"


def extract_email_address(text: str) -> Optional[str]:
    match = re.search(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    return match.group(1) if match else None


def derive_title(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", query).strip()
    words = cleaned.split()
    title = " ".join(words[:8]).strip()
    return title.title() if title else "Agent Output"


def is_tool_only_request(query: str) -> bool:
    lower = query.lower()
    return any(pattern in lower for pattern in EXPORT_ONLY_PATTERNS)


def extract_requested_tools(query: str) -> List[str]:
    lower = query.lower()
    tools: List[str] = []

    for tool_name, patterns in TOOL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, lower):
                tools.append(tool_name)
                break

    return list(dict.fromkeys(tools))


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_text(text: str) -> List[float]:
    return embed_one(text)


def get_all_documents() -> List[Dict[str, Any]]:
    response = supabase.table(TABLE).select("*").execute()
    return response.data or []


def retrieve_similar_chunks(
    query: str,
    domain: Optional[str] = None,
    top_k: int = 5,
) -> List[Tuple[float, Dict[str, Any]]]:
    query_embedding = embed_text(query)
    return doc_cache.top_k(query_embedding, k=top_k, domain=domain)


def format_vector_context(similar_chunks: List[Tuple[float, Dict[str, Any]]]) -> str:
    if not similar_chunks:
        return ""

    parts = []
    for score, doc in similar_chunks:
        url = doc.get("url", "unknown")
        chunk = doc.get("content", "")
        doc_domain = doc.get("domain", "unknown")
        parts.append(
            f"[Vector score={score:.3f}] domain={doc_domain} url={url}\n{chunk}"
        )
    return "\n\n---\n\n".join(parts)


def web_search(query: str, num_results: int = 5) -> List[Dict[str, str]]:
    if not tavily:
        return []

    try:
        response = tavily.search(query=query, max_results=num_results)

        results: List[Dict[str, str]] = []
        urls: List[str] = []

        for item in response.get("results", []):
            url = item.get("url", "")
            urls.append(url)
            results.append(
                {
                    "title": item.get("title", ""),
                    "link": url,
                    "snippet": item.get("content", ""),
                }
            )

        print("\n[Tavily Sources]")
        for url in urls:
            print("-", url)
        print()

        return results

    except Exception as e:
        print(f"Tavily search error: {e}")
        return []


def format_web_context(results: List[Dict[str, str]]) -> str:
    if not results:
        return ""

    parts = []
    for idx, item in enumerate(results, start=1):
        parts.append(
            f"[Web result {idx}] {item['title']}\n"
            f"URL: {item['link']}\n"
            f"Snippet: {item['snippet']}"
        )
    return "\n\n---\n\n".join(parts)


def build_citations(
    similar_chunks: List[Tuple[float, Dict[str, Any]]],
    web_results: List[Dict[str, str]],
    retrieval_mode: str,
) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []

    if retrieval_mode in {"vector_only", "hybrid"}:
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

    if retrieval_mode in {"google_only", "hybrid"}:
        for item in web_results:
            citations.append(
                {
                    "title": item.get("title", item.get("link", "Web result")),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "source": "web",
                }
            )

    return citations


def is_relevant_to_kb(
    text: str,
    kb_embeddings: List[List[float]],
    threshold: float = 0.4
) -> bool:
    if not kb_embeddings:
        return False

    text_emb = embed_texts([text[:1000]])[0]
    return doc_cache.max_similarity(text_emb) > threshold


def maybe_store_interaction(
    web_results: List[Dict[str, str]],
    domain: Optional[str] = None
) -> None:
    print("deciding to store or not to store -> ")
    kb_embeddings = doc_cache.get()[0]

    for result in web_results:
        url = result["link"]
        try:
            existing = (
                supabase
                .table(TABLE)
                .select("url")
                .eq("url", url)
                .limit(1)
                .execute()
            )
            if existing.data:
                continue

            text = fetch_page_text(url)
            if len(text) < 200:
                continue

            if not is_relevant_to_kb(text, kb_embeddings):
                continue

            chunks = chunk_text(text)
            embeddings = embed_texts(chunks)
            insert_chunks(url, chunks, embeddings, domain=domain)
            doc_cache.add(url, chunks, embeddings, domain=domain)

        except Exception:
            continue


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def heuristic_domain_router(query: str) -> str:
    lower = query.lower()
    scores = {domain: 0 for domain in DOMAIN_KEYWORDS}

    for domain, keywords in DOMAIN_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                scores[domain] += 1

    best_domain = max(scores, key=scores.get)
    return best_domain if scores[best_domain] > 0 else "general"


def llm_domain_router(query: str) -> str:
    system_prompt = (
        "You route user requests for a business-creation website.\n"
        "Valid domains: legal, finance, planning, budget, general.\n"
        "Return ONLY valid JSON like {\"domain\":\"legal\"}.\n"
        "Choose general if the query does not clearly fit one of the domain agents."
    )

    try:
        reply = chat_text(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]
        )
        parsed = extract_json_object(reply)
        if parsed and parsed.get("domain") in {"legal", "finance", "planning", "budget", "general"}:
            return parsed["domain"]
    except Exception:
        pass

    return heuristic_domain_router(query)


def route_query(query: str) -> Dict[str, Any]:
    tools = extract_requested_tools(query)
    domain = heuristic_domain_router(query)
    if domain == "general":
        domain = llm_domain_router(query)
    return {"domain": domain, "tools": tools}

# ---------------------------
# LLM answer function with memory
# ---------------------------

def answer_with_context(
    query: str,
    domain: str,
    user_context_text: str,
    vector_context: str,
    web_context: str,
    retrieval_mode: str,
    conversation_history: List[Dict[str, str]],
    on_token: Optional[Any] = None,
) -> str:
    system_prompt = (
        f"{DOMAIN_SYSTEM_PROMPTS[domain]}\n\n"
        "Instructions:\n"
        "1. Answer the user's question clearly.\n"
        "2. Prefer vector context when it is relevant.\n"
        "3. Use web context when vector context is weak, missing, or outdated.\n"
        "4. Use the prior conversation only when it is relevant to the current question.\n"
        "5. If the context is weak, say what is uncertain.\n"
        "6. If web context is used, mention the supporting URLs naturally.\n"
        "7. If neither vector nor web context exists, answer carefully from general knowledge and say that no retrieved context was available.\n"
        "8. Keep the answer practical and structured.\n\n"
        f"Current retrieval mode: {retrieval_mode}"
    )

    user_prompt = (
        f"User business context:\n{user_context_text or 'None'}\n\n"
        f"User question:\n{query}\n\n"
        f"Vector context:\n{vector_context or 'None'}\n\n"
        f"Web context:\n{web_context or 'None'}"
    )

    return chat_text(
        [
            {"role": "system", "content": system_prompt},
            *conversation_history,
            {"role": "user", "content": user_prompt},
        ],
        on_token,
    )

# ---------------------------
# Domain / general agents
# ---------------------------

def run_domain_agent(
    query: str,
    domain: str,
    user_context_text: str,
    conversation_history: List[Dict[str, str]],
    on_token: Optional[Any] = None,
) -> Dict[str, Any]:
    enriched_query = build_enriched_query(query, user_context_text)
    similar_chunks = retrieve_similar_chunks(enriched_query, domain=domain, top_k=5)
    top_score = similar_chunks[0][0] if similar_chunks else 0.0

    vector_context = format_vector_context(similar_chunks)

    web_context = ""
    web_results: List[Dict[str, str]] = []
    retrieval_mode = "vector_only"

    if not similar_chunks or top_score < 0.78:
        retrieval_mode = "hybrid"
        web_results = web_search(f"{domain} business question: {enriched_query}", num_results=5)
        web_context = format_web_context(web_results)

    answer = answer_with_context(
        query=query,
        domain=domain,
        user_context_text=user_context_text,
        vector_context=vector_context,
        web_context=web_context,
        retrieval_mode=retrieval_mode,
        conversation_history=conversation_history,
        on_token=on_token,
    )

    if web_results:
        run_in_background(maybe_store_interaction, web_results, domain=domain)

    return {
        "domain": domain,
        "retrieval_mode": retrieval_mode,
        "source_mode": retrieval_mode,
        "answer": answer,
        "citations": build_citations(similar_chunks, web_results, retrieval_mode),
        "vector_context": vector_context,
        "web_context": web_context,
    }


def run_general_agent(
    query: str,
    user_context_text: str,
    conversation_history: List[Dict[str, str]],
    on_token: Optional[Any] = None,
) -> Dict[str, Any]:
    enriched_query = build_enriched_query(query, user_context_text)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        chunks_future = pool.submit(retrieve_similar_chunks, enriched_query, None, 5)
        web_future = pool.submit(web_search, enriched_query, 5)
        similar_chunks = chunks_future.result()
        web_results = web_future.result()
    vector_context = format_vector_context(similar_chunks)
    web_context = format_web_context(web_results)

    answer = answer_with_context(
        query=query,
        domain="general",
        user_context_text=user_context_text,
        vector_context=vector_context,
        web_context=web_context,
        retrieval_mode="hybrid",
        conversation_history=conversation_history,
        on_token=on_token,
    )

    if web_results:
        run_in_background(maybe_store_interaction, web_results, domain="general")

    return {
        "domain": "general",
        "retrieval_mode": "hybrid",
        "source_mode": "hybrid",
        "answer": answer,
        "citations": build_citations(similar_chunks, web_results, "hybrid"),
        "vector_context": vector_context,
        "web_context": web_context,
    }

# ---------------------------
# Tool agents
# ---------------------------

def export_pdf_tool(title: str, body: str) -> str:
    file_path = PDF_DIR / f"{slugify(title)}.pdf"

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(file_path), pagesize=letter)
    story = []

    story.append(Paragraph(html.escape(title), styles["Title"]))
    story.append(Spacer(1, 0.3 * inch))

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for paragraph in paragraphs:
        safe_paragraph = html.escape(paragraph).replace("\n", "<br/>")
        story.append(Paragraph(safe_paragraph, styles["BodyText"]))
        story.append(Spacer(1, 0.18 * inch))

    doc.build(story)
    return str(file_path)


def export_docx_tool(title: str, body: str) -> str:
    file_path = DOCX_DIR / f"{slugify(title)}.docx"

    doc = Document()
    doc.add_heading(title, level=1)

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    for paragraph in paragraphs:
        doc.add_paragraph(paragraph)

    doc.save(str(file_path))
    return str(file_path)


def draft_email_tool(subject: str, body: str, recipient: Optional[str] = None) -> str:
    file_path = EMAIL_DIR / f"{slugify(subject)}.eml"
    recipient = recipient or "recipient@example.com"

    eml_text = (
        f"To: {recipient}\n"
        f"Subject: {subject}\n"
        f"MIME-Version: 1.0\n"
        f"Content-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n"
    )

    file_path.write_text(eml_text, encoding="utf-8")
    return str(file_path)


def build_image_prompt(query: str, answer_text: str) -> str:
    system_prompt = (
        "You create concise, high-quality image prompts for a business-creation platform.\n"
        "Output only the prompt text. No bullets. No explanation."
    )

    user_prompt = (
        f"User request:\n{query}\n\n"
        f"Useful content to reflect:\n{answer_text}\n\n"
        "Write one polished image-generation prompt."
    )

    return chat_text(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )


def write_svg_preview(title: str, prompt: str, file_path: Path) -> None:
    wrapped_title = textwrap.wrap(title, width=28)[:2]
    wrapped_prompt = textwrap.wrap(prompt, width=42)[:8]

    y = 50
    lines = []

    for line in wrapped_title:
        lines.append(
            f'<text x="32" y="{y}" font-size="24" font-family="Arial" font-weight="bold" fill="#111827">{html.escape(line)}</text>'
        )
        y += 32

    y += 16
    for line in wrapped_prompt:
        lines.append(
            f'<text x="32" y="{y}" font-size="16" font-family="Arial" fill="#374151">{html.escape(line)}</text>'
        )
        y += 24

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700" viewBox="0 0 1000 700">
  <rect width="1000" height="700" fill="#F9FAFB"/>
  <rect x="20" y="20" width="960" height="660" rx="22" fill="#FFFFFF" stroke="#E5E7EB" stroke-width="2"/>
  <text x="32" y="24" opacity="0">.</text>
  {''.join(lines)}
</svg>
"""
    file_path.write_text(svg, encoding="utf-8")


def image_tool_agent(query: str, answer_text: str) -> Dict[str, str]:
    title = derive_title(query)
    prompt = build_image_prompt(query, answer_text)

    prompt_file = IMAGE_DIR / f"{slugify(title)}-prompt.txt"
    svg_file = IMAGE_DIR / f"{slugify(title)}-preview.svg"

    prompt_file.write_text(prompt, encoding="utf-8")
    write_svg_preview(title=title, prompt=prompt, file_path=svg_file)

    return {
        "prompt_file": str(prompt_file),
        "preview_file": str(svg_file),
    }

# ---------------------------
# Programmatic entrypoint
# ---------------------------

def run_multi_agent(
    query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    on_token: Optional[Any] = None,
) -> Dict[str, Any]:
    conversation_history = conversation_history or []
    user_context_text = format_user_context(USER_CONTEXT)

    routing = route_query(query)
    domain = routing["domain"]
    tools = routing["tools"]

    if domain in {"legal", "finance", "planning", "budget"}:
        result = run_domain_agent(
            query=query,
            domain=domain,
            user_context_text=user_context_text,
            conversation_history=conversation_history,
            on_token=on_token,
        )
    else:
        result = run_general_agent(
            query=query,
            user_context_text=user_context_text,
            conversation_history=conversation_history,
            on_token=on_token,
        )

    return {
        "answer": result["answer"],
        "domain": result["domain"],
        "tools": tools,
        "retrieval_mode": result["retrieval_mode"],
        "source_mode": result["source_mode"],
        "citations": result.get("citations", []),
    }

# ---------------------------
# Main loop with chat memory
# ---------------------------

def run_chat() -> None:
    print("Multi-agent business assistant")

    user_id = get_user_id()
    print(f"\nWelcome, {user_id}!")

    past_chats = get_user_chats(user_id)
    if past_chats:
        print("\nYour chats:")
        for i, chat in enumerate(past_chats):
            created_at = chat.get("created_at", "")
            print(f"  [{i+1}] Chat from {created_at[:19]}  (id: {chat['id'][:8]}...)")
        print("  [N] New chat")

        choice = input("\nPick a chat or press N for new: ").strip().lower()

        if choice == "n" or not choice:
            chat_id = create_new_chat(user_id)
            conversation_history: List[Dict[str, str]] = []
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

    last_answer = ""
    last_title = "Agent Output"

    while True:
        query = input("You: ").strip()
        if query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        if not query:
            continue

        try:
            routing = route_query(query)
            domain = routing["domain"]
            tools = routing["tools"]
            user_context_text = format_user_context(USER_CONTEXT)

            print(f"\n[Router] domain={domain} tools={tools if tools else ['none']}")

            use_previous_answer = bool(last_answer and tools and is_tool_only_request(query))

            if use_previous_answer:
                answer = last_answer
                title = last_title
                print("[Router] Using previous answer as tool input.\n")
            else:
                if domain in {"legal", "finance", "planning", "budget"}:
                    result = run_domain_agent(
                        query=query,
                        domain=domain,
                        user_context_text=user_context_text,
                        conversation_history=conversation_history,
                    )
                else:
                    result = run_general_agent(
                        query=query,
                        user_context_text=user_context_text,
                        conversation_history=conversation_history,
                    )

                answer = result["answer"]
                title = derive_title(query)
                last_answer = answer
                last_title = title

                save_message(user_id, chat_id, "user", query)
                save_message(user_id, chat_id, "assistant", answer)
                conversation_history.append({"role": "user", "content": query})
                conversation_history.append({"role": "assistant", "content": answer})

                print(f"[Agent] {result['domain']} via {result['retrieval_mode']}")
                print(f"\nAssistant ({result['domain']}):\n{answer}\n")

            created_files: List[str] = []

            if "pdf" in tools:
                pdf_path = export_pdf_tool(title=title, body=answer)
                created_files.append(pdf_path)

            if "docx" in tools:
                docx_path = export_docx_tool(title=title, body=answer)
                created_files.append(docx_path)

            if "email" in tools:
                recipient = extract_email_address(query)
                subject = f"{title} - Draft"
                email_path = draft_email_tool(subject=subject, body=answer, recipient=recipient)
                created_files.append(email_path)

            if "image" in tools:
                image_artifacts = image_tool_agent(query=query, answer_text=answer)
                created_files.extend(image_artifacts.values())

            if created_files:
                print("[Tool Output]")
                for path in created_files:
                    print("-", path)
                print()

        except Exception as exc:
            print(f"\nError: {exc}\n")


if __name__ == "__main__":
    run_chat()
