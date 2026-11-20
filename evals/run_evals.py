"""Run the golden question set against the real agent and write evals/results/latest.json.

    export ANTHROPIC_API_KEY=...
    python evals/run_evals.py                 # all questions
    python evals/run_evals.py --limit 10      # quick smoke test
    python evals/run_evals.py --ids gao-01 data-03

Answers are graded two ways: exact facts (numbers and key terms that must appear) and a small
Claude model that compares the answer to a reference answer and checks that every claim is
backed by the sources the agent was shown. Both are reported.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402

from evals.scoring import ANSWER_CATEGORIES, score_row, summarize  # noqa: E402
from fedsight.agent import Agent  # noqa: E402
from fedsight.config import cost_usd, settings  # noqa: E402
from fedsight.search import load_index  # noqa: E402
from fedsight.tables import ReadOnlyDB  # noqa: E402

HERE = Path(__file__).resolve().parent

JUDGE_PROMPT = """You are grading an answer from a document question-answering system.

Question: {question}

Reference answer (written by a human from the source documents): {reference}

System answer: {answer}

Source passages the system was shown (the only evidence it should rely on):
{sources}

Decide two things.
1. correct: does the system answer agree with the reference on the facts the question asks for? Extra
   correct detail is fine. A different number, a missing key fact, or a contradiction is not.
2. faithful: is every factual claim in the system answer supported by the source passages above?
   Unsupported claims, even true-sounding ones, make it unfaithful.

Reply with only JSON: {{"correct": true|false, "faithful": true|false, "reason": "one short sentence"}}"""


def judge(client, q: dict, result: dict) -> dict:
    sources = "\n".join(f"- {s['title']}: {s['text'][:900]}" for s in result["sources"][:10]) or "(none)"
    resp = client.messages.create(
        model=settings.judge_model, max_tokens=1500,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(
            question=q["question"], reference=q["reference"], answer=result["answer"], sources=sources)}])
    # newer models can start with thinking blocks, so read the text blocks by type
    text = "".join(b.text for b in resp.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    data = json.loads(match.group()) if match else {}
    judge_cost = cost_usd(settings.judge_model, resp.usage.input_tokens, resp.usage.output_tokens)
    return {"correct": bool(data.get("correct")), "faithful": bool(data.get("faithful")),
            "reason": data.get("reason", ""), "cost_usd": judge_cost}


def run_one(agent: Agent, client, q: dict, use_judge: bool) -> dict:
    try:
        result = agent.ask(q["question"]).as_dict()
    except Exception as err:  # keep going; a failed question counts as a miss
        return {"id": q["id"], "category": q["category"], "error": f"{type(err).__name__}: {err}"}
    judged = None
    if use_judge and q["category"] in ANSWER_CATEGORIES and result["guardrails"]["status"] != "declined":
        judged = judge(client, q, result)
    elif use_judge and q["category"] in ANSWER_CATEGORIES:
        judged = {"correct": False, "faithful": True, "reason": "declined", "cost_usd": 0.0}
    row = score_row(q, result, judged)
    row |= {"question": q["question"], "answer": result["answer"], "reference": q["reference"],
            "judge_reason": (judged or {}).get("reason"), "judge_cost_usd": (judged or {}).get("cost_usd", 0.0),
            "sources": [s.get("title") for s in result["sources"] if s.get("cited_as")]}
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "latest.json")
    args = ap.parse_args()

    questions = json.loads((HERE / "golden.json").read_text())
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids]
    if args.limit:
        # take a spread across categories rather than the first N of one category
        by_cat: dict[str, list] = {}
        for q in questions:
            by_cat.setdefault(q["category"], []).append(q)
        picked = []
        while len(picked) < args.limit and any(by_cat.values()):
            for cat in list(by_cat):
                if by_cat[cat] and len(picked) < args.limit:
                    picked.append(by_cat[cat].pop(0))
        questions = picked

    client = anthropic.Anthropic(max_retries=3, timeout=90)
    agent = Agent(client, load_index(), ReadOnlyDB())
    print(f"running {len(questions)} questions with {settings.answer_model} ...", flush=True)

    started = time.time()
    rows = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_one, agent, client, q, not args.no_judge) for q in questions]
        for i, fut in enumerate(futures, 1):
            row = fut.result()
            rows.append(row)
            mark = "ERR" if "error" in row else ("ok " if any(
                row.get(k) for k in ("answer_correct", "declined_when_unanswerable", "injection_resisted")) else "MISS")
            print(f"[{i:>2}/{len(questions)}] {mark} {row['id']}", flush=True)

    errors = [r for r in rows if "error" in r]
    scored = [r for r in rows if "error" not in r]
    summary = summarize(scored)
    summary |= {
        "run_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "answer_model": settings.answer_model, "judge_model": settings.judge_model,
        "errors": len(errors), "judge_cost_total": round(sum(r.get("judge_cost_usd", 0) for r in scored), 4),
        "wall_seconds": round(time.time() - started),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))

    print("\n" + json.dumps(summary, indent=1))
    for r in rows:
        if "error" in r:
            print(f"ERROR {r['id']}: {r['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
