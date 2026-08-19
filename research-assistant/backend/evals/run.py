"""Run the golden evaluation set and compare against the committed baseline.

    python -m evals.run              # retrieval only — fast, no LLM calls
    python -m evals.run --answers    # also generate and grade answers
    python -m evals.run --update     # rewrite baseline.json from this run

Retrieval and answering are measured separately on purpose. Retrieval is
deterministic given the same embeddings and index, so it is the part worth
gating on; answer generation depends on a rate-limited model and is slower and
noisier, so it stays opt-in.

Exits non-zero when a metric falls below its baseline by more than TOLERANCE,
which is what makes this usable as a CI gate rather than a report you read and
forget.
"""

import argparse
import json
import re
import unicodedata
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import DOCS, QUESTIONS, ANSWERABLE, UNANSWERABLE  # noqa: E402

BASELINE_PATH = Path(__file__).with_name("baseline.json")
# Scores move a little run to run (the reranker and the judge are not
# deterministic). Only a real drop should fail the build.
TOLERANCE = 0.05


def normalize(text: str) -> str:
    """Fold the typographic characters models emit into their plain
    equivalents before matching.

    Without this the grader reports false failures: the model writes
    "8\u202fminutes" using a narrow no-break space, and a naive substring test
    for "8 minutes" misses a completely correct answer. An eval harness that
    invents failures is worse than no harness, because it trains you to ignore
    it. NFKC also folds non-breaking hyphens, full-width digits and ligatures.
    """
    folded = unicodedata.normalize("NFKC", text)
    # NFKC leaves the dash family and U+00A0/U+202F alone, so fold those by
    # hand — models reach for typographic dashes and thin spaces constantly.
    folded = folded.translate({
        0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-",
        0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
    })
    return re.sub(r"\s+", " ", folded).lower().strip()


def _ingest(user_id: str) -> None:
    from rag.retrieval import ingest_document
    for doc in DOCS:
        result = ingest_document(user_id, doc.filename, doc.text.encode())
        if result["status"] != "ready":
            raise RuntimeError(f"fixture failed to ingest: {doc.filename}: {result.get('error')}")


def evaluate_retrieval(user_id: str, threshold: float) -> dict:
    """Did the loop surface the document that actually holds the answer?"""
    from rag.chat_agent import agentic_retrieve

    hits = misses = 0
    false_positives = 0
    failures = []

    for q in QUESTIONS:
        chunks, _, _ = agentic_retrieve(user_id, q.q, [], top_k=4, similarity_threshold=threshold)
        files = {c["filename"] for c in chunks}

        if q.answerable:
            if q.source in files:
                hits += 1
            else:
                misses += 1
                failures.append(f"MISS  {q.q}\n        wanted {q.source}, got {sorted(files) or 'nothing'}"
                                f"\n        probes: {q.probes}")
        else:
            # An unanswerable question retrieving nothing is the ideal;
            # retrieving something is only a problem if it then gets answered,
            # which the answer pass measures.
            if chunks:
                false_positives += 1

    total = len(ANSWERABLE)
    return {
        "retrieval_recall": round(hits / total, 3) if total else 0.0,
        "unanswerable_retrieved_something": round(false_positives / len(UNANSWERABLE), 3),
        "_failures": failures,
    }


def evaluate_answers(user_id: str, threshold: float) -> dict:
    """Does the answer contain the fact — and does it decline when it should?"""
    from rag.chat_agent import chat

    correct = 0
    grounded_refusals = 0
    failures = []

    for q in ANSWERABLE:
        result = chat(user_id, None, q.q, top_k=4, similarity_threshold=threshold)
        answer = normalize(result["answer"])
        if any(normalize(e) in answer for e in q.expect_any):
            correct += 1
        else:
            failures.append(f"WRONG {q.q}\n        expected one of {q.expect_any}"
                            f"\n        got: {result['answer'][:160].strip()}")

    for q in UNANSWERABLE:
        result = chat(user_id, None, q.q, top_k=4, similarity_threshold=threshold)
        answer = normalize(result["answer"])
        declined = any(m in answer for m in
                       ("nothing in them supports", "don't have any documents",
                        "not contain", "no information", "doesn't mention",
                        "does not mention", "not mentioned", "cannot find",
                        "no mention", "unable to find"))
        if declined:
            grounded_refusals += 1
        else:
            failures.append(f"HALLUCINATED {q.q}\n        should have declined; got: "
                            f"{result['answer'][:160].strip()}\n        probes: {q.probes}")

    return {
        "answer_accuracy": round(correct / len(ANSWERABLE), 3),
        "refusal_rate": round(grounded_refusals / len(UNANSWERABLE), 3),
        "_failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="also generate and grade answers (slow)")
    parser.add_argument("--update", action="store_true", help="write these scores as the new baseline")
    parser.add_argument("--threshold", type=float, default=0.55)
    args = parser.parse_args()

    import logging
    logging.disable(logging.INFO)

    from rag.store import init_rag_db, delete_all_user_rag_data

    user_id = "eval-" + uuid.uuid4().hex[:8]
    init_rag_db()
    print(f"Golden set: {len(DOCS)} documents, {len(ANSWERABLE)} answerable, "
          f"{len(UNANSWERABLE)} unanswerable  (threshold {args.threshold})\n")

    scores, failures = {}, []
    try:
        _ingest(user_id)

        t = time.time()
        r = evaluate_retrieval(user_id, args.threshold)
        failures += r.pop("_failures")
        scores.update(r)
        print(f"retrieval  ({time.time() - t:.0f}s)")

        if args.answers:
            t = time.time()
            a = evaluate_answers(user_id, args.threshold)
            failures += a.pop("_failures")
            scores.update(a)
            print(f"answers    ({time.time() - t:.0f}s)")
    finally:
        delete_all_user_rag_data(user_id)

    baseline = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {}

    print(f"\n{'METRIC':38} {'SCORE':>7} {'BASE':>7}  RESULT")
    print("-" * 70)
    regressed = False
    for name, value in sorted(scores.items()):
        base = baseline.get(name)
        # For this metric lower is better; everything else is higher-is-better.
        lower_better = name == "unanswerable_retrieved_something"
        if base is None:
            verdict = "new"
        elif lower_better:
            drop = value - base
            verdict = "OK" if drop <= TOLERANCE else "REGRESSED"
        else:
            drop = base - value
            verdict = "OK" if drop <= TOLERANCE else "REGRESSED"
        if verdict == "REGRESSED":
            regressed = True
        print(f"{name:38} {value:>7.3f} {('—' if base is None else f'{base:.3f}'):>7}  {verdict}")

    if failures:
        print(f"\n{len(failures)} case(s) needing attention:")
        for f in failures:
            print("  " + f)

    if args.update:
        BASELINE_PATH.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
        print(f"\nbaseline written to {BASELINE_PATH.name}")
        return 0

    if regressed:
        print("\nFAIL — a metric dropped more than the tolerance below baseline.")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
