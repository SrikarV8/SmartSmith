"""
evaluate_agents.py

Benchmark script to compare a single-agent runtime against a multi-agent runtime
for a business-creation assistant.

What it measures:
- latency
- predicted domain / routing accuracy
- tool usage / tool match
- answer length
- approximate token count
- success / failure
- exports detailed rows to CSV + JSON
- leaves blank manual scoring columns for later review

Expected default module names:
- single-agent file: runtime_loop.py
- multi-agent file:  runtime_loop_multi_agent.py

You can change those below if your filenames differ.
"""

from __future__ import annotations

import csv
import importlib
import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------
# Config
# ---------------------------

SINGLE_AGENT_MODULE = "runtime_loop"
MULTI_AGENT_MODULE = "runtime_loop_multi_agent"

OUTPUT_DIR = Path("evaluation_outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEST_CASES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "query": "How do I register an LLC in Texas for a mobile coffee cart?",
        "expected_domain": "legal",
        "expected_tools": [],
    },
    {
        "id": 2,
        "query": "What funding options do I have for a small startup business?",
        "expected_domain": "finance",
        "expected_tools": [],
    },
    {
        "id": 3,
        "query": "Help me create a launch plan for a skincare brand targeting college students.",
        "expected_domain": "planning",
        "expected_tools": [],
    },
    {
        "id": 4,
        "query": "How much would it cost to start a mobile coffee cart business in Austin?",
        "expected_domain": "budget",
        "expected_tools": [],
    },
    {
        "id": 5,
        "query": "Create a business setup checklist and export it as a PDF.",
        "expected_domain": "planning",
        "expected_tools": ["pdf"],
    },
    {
        "id": 6,
        "query": "Turn the previous answer into a DOCX file.",
        "expected_domain": "general",
        "expected_tools": ["docx"],
    },
    {
        "id": 7,
        "query": "Draft an email summarizing the startup plan to founder@example.com.",
        "expected_domain": "general",
        "expected_tools": ["email"],
    },
    {
        "id": 8,
        "query": "Create an image concept for a coffee cart startup brand.",
        "expected_domain": "general",
        "expected_tools": ["image"],
    },
    {
        "id": 9,
        "query": "What are current trends in mobile food businesses?",
        "expected_domain": "general",
        "expected_tools": [],
    },
    {
        "id": 10,
        "query": "Compare LLC vs sole proprietorship and give a simple budget range for starting.",
        "expected_domain": "legal",  # mixed query; choose whichever you want as expected primary domain
        "expected_tools": [],
    },
]

# ---------------------------
# Utility helpers
# ---------------------------

def normalize_tools(tools: Any) -> List[str]:
    if tools is None:
        return []
    if isinstance(tools, str):
        return [tools]
    if isinstance(tools, list):
        return [str(x).strip().lower() for x in tools if str(x).strip()]
    return []


def approx_token_count(text: str) -> int:
    # Simple approximation for evaluation logs
    return max(1, len(text) // 4) if text else 0


def tool_match_score(expected_tools: List[str], predicted_tools: List[str]) -> bool:
    return set(normalize_tools(expected_tools)) == set(normalize_tools(predicted_tools))


def safe_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise ImportError(f"Could not import module '{module_name}': {exc}") from exc

# ---------------------------
# Adapters
# ---------------------------

def run_single_agent(query: str) -> Dict[str, Any]:
    """
    Adapter for your single-agent runtime.

    Works in this order:
    1. If the module defines run_single_agent(query), use it.
    2. If the module defines run_query(query), use it.
    3. Otherwise try to reconstruct the earlier runtime_loop flow from helper functions.
    """
    module = safe_import(SINGLE_AGENT_MODULE)

    if hasattr(module, "run_single_agent"):
        result = module.run_single_agent(query)
        return result if isinstance(result, dict) else {"answer": str(result), "domain": "general", "tools": []}

    if hasattr(module, "run_query"):
        result = module.run_query(query)
        return result if isinstance(result, dict) else {"answer": str(result), "domain": "general", "tools": []}

    needed = [
        "retrieve_similar_chunks",
        "decide_sources",
        "format_vector_context",
        "ask_llm",
    ]
    if not all(hasattr(module, name) for name in needed):
        raise RuntimeError(
            "Single-agent adapter could not find a compatible interface.\n"
            "Add a function like:\n"
            "def run_single_agent(query: str) -> dict:\n"
            "    return {'answer': ..., 'domain': 'general', 'tools': []}\n"
        )

    similar_chunks = module.retrieve_similar_chunks(query, top_k=5)
    source_mode = module.decide_sources(similar_chunks)

    vector_context = ""
    web_context = ""

    if source_mode in {"vector_only", "hybrid"} and hasattr(module, "format_vector_context"):
        vector_context = module.format_vector_context(similar_chunks)

    search_fn = None
    format_web_fn = None

    if hasattr(module, "web_search"):
        search_fn = module.web_search
    elif hasattr(module, "google_search"):
        search_fn = module.google_search

    if hasattr(module, "format_web_context"):
        format_web_fn = module.format_web_context
    elif hasattr(module, "format_google_context"):
        format_web_fn = module.format_google_context

    if source_mode in {"google_only", "web_only", "hybrid"} and search_fn and format_web_fn:
        web_results = search_fn(query, num_results=5)
        web_context = format_web_fn(web_results)

    answer = module.ask_llm(query, vector_context, web_context, source_mode)

    return {
        "answer": answer,
        "domain": "general",
        "tools": [],
        "retrieval_mode": source_mode,
    }


def run_multi_agent(query: str) -> Dict[str, Any]:
    """
    Adapter for your multi-agent runtime.

    Works in this order:
    1. If the module defines run_multi_agent(query), use it.
    2. If the module defines run_query(query), use it.
    3. Otherwise reconstruct the earlier runtime_loop_multi_agent flow:
       route_query -> run_domain_agent/run_general_agent.
    """
    module = safe_import(MULTI_AGENT_MODULE)

    if hasattr(module, "run_multi_agent"):
        result = module.run_multi_agent(query)
        return result if isinstance(result, dict) else {"answer": str(result), "domain": "general", "tools": []}

    if hasattr(module, "run_query"):
        result = module.run_query(query)
        return result if isinstance(result, dict) else {"answer": str(result), "domain": "general", "tools": []}

    needed = ["route_query", "run_domain_agent", "run_general_agent"]
    if not all(hasattr(module, name) for name in needed):
        raise RuntimeError(
            "Multi-agent adapter could not find a compatible interface.\n"
            "Add a function like:\n"
            "def run_multi_agent(query: str) -> dict:\n"
            "    return {'answer': ..., 'domain': ..., 'tools': [...]}\n"
        )

    routing = module.route_query(query)
    domain = routing.get("domain", "general")
    tools = normalize_tools(routing.get("tools", []))

    if domain in {"legal", "finance", "planning", "budget"}:
        result = module.run_domain_agent(query, domain)
    else:
        result = module.run_general_agent(query)

    return {
        "answer": result.get("answer", ""),
        "domain": result.get("domain", domain),
        "tools": tools,
        "retrieval_mode": result.get("retrieval_mode", ""),
    }

# ---------------------------
# Evaluation core
# ---------------------------

def evaluate_one_system(
    system_name: str,
    runner,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    query = case["query"]
    expected_domain = case.get("expected_domain", "")
    expected_tools = normalize_tools(case.get("expected_tools", []))

    start = time.perf_counter()
    success = True
    error = ""
    result: Dict[str, Any] = {}

    try:
        result = runner(query)
        if not isinstance(result, dict):
            result = {"answer": str(result)}
    except Exception as exc:
        success = False
        error = f"{type(exc).__name__}: {exc}"
        result = {"answer": ""}
        traceback.print_exc()

    latency_seconds = time.perf_counter() - start

    answer = str(result.get("answer", "") or "")
    predicted_domain = str(result.get("domain", ""))
    predicted_tools = normalize_tools(result.get("tools", []))
    retrieval_mode = str(result.get("retrieval_mode", ""))

    row = {
        "case_id": case.get("id", ""),
        "system": system_name,
        "query": query,
        "success": success,
        "error": error,
        "expected_domain": expected_domain,
        "predicted_domain": predicted_domain,
        "routing_correct": (predicted_domain == expected_domain) if predicted_domain else False,
        "expected_tools": ",".join(expected_tools),
        "predicted_tools": ",".join(predicted_tools),
        "tool_match": tool_match_score(expected_tools, predicted_tools),
        "retrieval_mode": retrieval_mode,
        "latency_seconds": round(latency_seconds, 4),
        "answer_chars": len(answer),
        "answer_approx_tokens": approx_token_count(answer),
        "answer": answer,
        # manual review columns
        "manual_quality_score_1_to_5": "",
        "manual_correctness_score_1_to_5": "",
        "manual_usefulness_score_1_to_5": "",
        "manual_hallucination_flag": "",
        "notes": "",
    }
    return row


def evaluate_all_cases() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for case in TEST_CASES:
        print(f"\n=== Case {case.get('id', '')}: {case['query']} ===")

        single_row = evaluate_one_system("single_agent", run_single_agent, case)
        print(
            f"[single_agent] success={single_row['success']} "
            f"latency={single_row['latency_seconds']}s "
            f"domain={single_row['predicted_domain']} "
            f"tools={single_row['predicted_tools']}"
        )
        rows.append(single_row)

        multi_row = evaluate_one_system("multi_agent", run_multi_agent, case)
        print(
            f"[multi_agent]  success={multi_row['success']} "
            f"latency={multi_row['latency_seconds']}s "
            f"domain={multi_row['predicted_domain']} "
            f"tools={multi_row['predicted_tools']}"
        )
        rows.append(multi_row)

    return rows

# ---------------------------
# Output writers
# ---------------------------

def write_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: List[Dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

# ---------------------------
# Summaries
# ---------------------------

def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}

    for system_name in {"single_agent", "multi_agent"}:
        system_rows = [r for r in rows if r["system"] == system_name]
        if not system_rows:
            continue

        successes = [r for r in system_rows if r["success"]]
        routing_hits = [r for r in system_rows if r["routing_correct"]]
        tool_hits = [r for r in system_rows if r["tool_match"]]
        latencies = [float(r["latency_seconds"]) for r in system_rows]
        answer_tokens = [int(r["answer_approx_tokens"]) for r in system_rows]

        summary[system_name] = {
            "num_cases": len(system_rows),
            "success_rate": round(len(successes) / len(system_rows), 4),
            "routing_accuracy": round(len(routing_hits) / len(system_rows), 4),
            "tool_match_rate": round(len(tool_hits) / len(system_rows), 4),
            "avg_latency_seconds": round(sum(latencies) / len(latencies), 4) if latencies else 0.0,
            "avg_answer_approx_tokens": round(sum(answer_tokens) / len(answer_tokens), 2) if answer_tokens else 0.0,
        }

    return summary


def write_summary(summary: Dict[str, Dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

# ---------------------------
# Main
# ---------------------------

def main() -> None:
    rows = evaluate_all_cases()

    csv_path = OUTPUT_DIR / "evaluation_results.csv"
    json_path = OUTPUT_DIR / "evaluation_results.json"
    summary_path = OUTPUT_DIR / "evaluation_summary.json"

    write_csv(rows, csv_path)
    write_json(rows, json_path)

    summary = summarize(rows)
    write_summary(summary, summary_path)

    print("\n=== Summary ===")
    for system_name, stats in summary.items():
        print(f"\n{system_name}")
        for key, value in stats.items():
            print(f"  {key}: {value}")

    print(f"\nWrote CSV:    {csv_path}")
    print(f"Wrote JSON:   {json_path}")
    print(f"Wrote summary:{summary_path}")
    print("\nYou can now manually score quality/correctness/usefulness in the CSV.")


if __name__ == "__main__":
    main()
