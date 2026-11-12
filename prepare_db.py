import hashlib
import os
import re
from typing import List, Set

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from supabase import Client, create_client
from tavily import TavilyClient
from llm import TABLE, embed_texts as _embed_texts, missing_env
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if missing_env(["TAVILY_API_KEY"]):
    raise ValueError(f"Missing required environment variables: {missing_env(['TAVILY_API_KEY'])}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

# Direct URLs to ingest
WEBSITES = [
    "https://www.sba.gov/business-guide/launch-your-business",
    "https://www.irs.gov/businesses/small-businesses-self-employed/starting-a-business",
]

# Search prompts that Tavily will use to discover good pages
SEARCH_PROMPTS = [
    "How do I start a small business in the United States?",
    "What are the first steps to starting a business?",
    "How do I validate a business idea?",
    "How do I choose a business name?",
    "How do I register a business legally?",
    "What licenses or permits might a new business need?",
    "What is the difference between a sole proprietorship, LLC, and corporation?",
    "How do I choose the right business structure?",
    "How do I write a business plan?",
    "What should be included in a startup business plan?",
    "How do I define a target market?",
    "How do I create a value proposition?",
    "How do I identify competitors for a new business?",
    "How do I estimate startup costs?",
    "How do I create revenue projections for a small business?",
    "How do I fund a startup?",
    "What are the best funding options for small businesses?",
    "How do small business loans work?",
    "How do I create a startup budget?",
    "How do I manage cash flow in a small business?",
    "What financial statements should a new business track?",
    "How do I price my product or service?",
    "How do I break even on a business idea?",
    "What taxes does a small business need to pay?",
    "How do quarterly estimated taxes work?",
    "What business records should I keep for taxes?",
    "What contracts should a new business have?",
    "What legal risks should a startup watch out for?",
    "What are common compliance requirements for a small business?",
    "How do I market a new business with a small budget?",
    "What are the best marketing channels for a startup?",
    "How do I find my first customers?",
    "How do I create a sales strategy for a small business?",
    "How do I build a brand for a new business?",
    "How do I use social media to grow a business?",
    "How do I create a customer acquisition strategy?",
    "How do I improve customer retention?",
    "How do I set up business operations for a startup?",
    "What tools do I need to run a small business?",
    "How do I manage inventory for a small business?",
    "How do I create efficient business processes?",
    "How do I decide what to outsource?",
    "What are best practices for customer service in a small business?",
    "When should a startup hire its first employee?",
    "How do I hire my first employee?",
    "Should I use contractors or employees?",
    "How do I build a startup team?",
    "How do I create roles and responsibilities in a small business?",
    "What payroll basics should a business owner know?",
    "How do I scale a small business?",
    "What are common reasons startups fail?",
    "How do I know when to pivot a business idea?",
    "How do I expand into a new market?",
    "How do I measure business growth?",
    "What KPIs should a small business track?",
    "How do I improve profit margins?",
    "How do I build a sustainable competitive advantage?",
    "How do I start an online business?",
    "How do I choose a platform for selling online?",
    "How do I build a website for a small business?",
    "How do I accept payments online?",
    "What are best practices for online customer support?",
    "What mistakes do first-time founders commonly make?",
    "How should a founder prioritize early tasks?",
    "How do I balance product development and customer acquisition?",
    "How do I decide whether a business idea is worth pursuing?",
    "What should a founder do in the first 90 days?",
    "How do I handle uncertainty as a new entrepreneur?",
    "What advice would a business mentor give to a first-time founder?"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"#.*$", "", url)
    url = re.sub(r"/+$", "", url)
    return url


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_existing_content_hashes() -> Set[str]:
    response = supabase.table(TABLE).select("content").execute()
    rows = response.data or []
    return {hash_text(row["content"]) for row in rows if row.get("content")}


def get_existing_urls() -> Set[str]:
    response = supabase.table(TABLE).select("url").execute()
    rows = response.data or []
    return {normalize_url(row["url"]) for row in rows if row.get("url")}


def discover_urls_from_prompts(prompts: List[str], max_results: int = 5) -> List[str]:
    discovered_urls = []

    for prompt in prompts:
        print(f"\nSearching Tavily for: {prompt}")
        try:
            response = tavily.search(query=prompt, max_results=max_results)
            results = response.get("results", [])

            print("[Tavily URLs]")
            for item in results:
                url = normalize_url(item.get("url", ""))
                if url:
                    discovered_urls.append(url)
                    print("-", url)

        except Exception as exc:
            print(f"Tavily search failed for prompt '{prompt}': {exc}")

    return discovered_urls


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch_page_text(url: str) -> str:
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=HEADERS) as http:
        response = http.get(url)
        # print(f"Status for {url}: {response.status_code}")

        if response.status_code != 200:
            return ""

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup([
        "script", "style", "noscript",
        "header", "footer", "svg",
        "nav", "aside", "form", "button"
    ]):
        tag.decompose()

    text = soup.body.get_text(separator=" ") if soup.body else soup.get_text(separator=" ")
    return clean_text(text)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap.")

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == text_len:
            break
        start += chunk_size - overlap

    return chunks


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def embed_texts(texts: List[str]) -> List[List[float]]:
    return _embed_texts(texts)


from typing import List, Optional
import re


def infer_domain(url: str, text: str) -> str:
    combined = f"{url} {text}".lower()

    domain_keywords = {
        "legal": [
            "llc", "incorporate", "legal", "license", "permit",
            "registration", "registered agent", "compliance",
            "trademark", "ein", "tax id", "privacy policy", "terms"
        ],
        "finance": [
            "funding", "revenue", "profit", "margin", "finance",
            "investor", "loan", "cash flow", "pricing", "sales forecast"
        ],
        "planning": [
            "business plan", "planning", "strategy", "roadmap",
            "target market", "customer", "go to market", "launch",
            "mvp", "positioning", "value proposition"
        ],
        "budget": [
            "budget", "cost", "costs", "expenses", "startup costs",
            "opex", "capex", "afford", "spend", "pricing estimate"
        ],
    }

    scores = {key: 0 for key in domain_keywords}

    for domain_name, keywords in domain_keywords.items():
        for keyword in keywords:
            if keyword in combined:
                scores[domain_name] += 1

    best_domain = max(scores, key=scores.get)
    return best_domain if scores[best_domain] > 0 else "general"


def insert_chunks(
    url: str,
    chunks: List[str],
    embeddings: List[List[float]],
    domain: Optional[str] = None
) -> int:
    rows = []

    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        resolved_domain = domain if domain is not None else infer_domain(url, chunk)

        row = {
            "url": url,
            "chunk_index": idx,
            "content": chunk,
            "embedding": embedding,
            "domain": resolved_domain,
        }

        rows.append(row)

    inserted = 0
    batch_size = 50
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        supabase.table(TABLE).insert(batch).execute()
        inserted += len(batch)

    return inserted


def prepare_database() -> None:
    existing_urls = get_existing_urls()
    existing_content_hashes = get_existing_content_hashes()

    discovered_urls = discover_urls_from_prompts(SEARCH_PROMPTS, max_results=5)

    all_urls = []
    seen_urls_this_run = set()

    for url in WEBSITES + discovered_urls:
        normalized = normalize_url(url)
        if not normalized:
            continue
        if normalized in seen_urls_this_run:
            continue
        seen_urls_this_run.add(normalized)
        all_urls.append(normalized)

    print("\nFinal URL list:")
    for url in all_urls:
        print("-", url)

    for url in all_urls:
        print(f"\nProcessing: {url}")

        if url in existing_urls:
            print("  Skipped: URL already exists in database.")
            continue

        try:
            text = fetch_page_text(url)

            if len(text) < 200:
                print("  Skipped: not enough text found.")
                continue

            raw_chunks = chunk_text(text)

            # Filter out duplicate chunk content
            unique_chunks = []
            for chunk in raw_chunks:
                chunk_hash = hash_text(chunk)
                if chunk_hash not in existing_content_hashes:
                    unique_chunks.append(chunk)
                    existing_content_hashes.add(chunk_hash)

            if not unique_chunks:
                print("  Skipped: all chunks were duplicates.")
                continue

            embeddings = embed_texts(unique_chunks)
            inserted_count = insert_chunks(url, unique_chunks, embeddings)
            existing_urls.add(url)

            print(f"  Inserted {inserted_count} new chunks.")

        except Exception as exc:
            print(f"  Failed for {url}: {exc}")


if __name__ == "__main__":
    prepare_database()