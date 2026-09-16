"""Evaluate retrieval and answering against SQuAD 2.0 — a set nobody here wrote.

The golden set in dataset.py is 14 questions over 3 documents written by this
project's author. It is a good regression check and worthless as evidence: a
perfect score on your own questions says the system does what you expected, not
that it works. SQuAD is a public benchmark with human-written questions over
Wikipedia paragraphs, and v2.0 includes questions that are deliberately
unanswerable from their paragraph — which is the behaviour this system most
needs to get right.

    python -m evals.squad --download
    python -m evals.squad --retrieval --questions 200     # free, no LLM calls
    python -m evals.squad --answers --questions 25        # ~25 min on Groq free

Retrieval and answering are separated because they cost very differently.
Embeddings run locally, so retrieval over hundreds of questions costs nothing
and takes seconds.

Answering spends roughly four Groq calls per question. The binding limit is not
the 8,000 tokens/minute shown in the response headers but a 200,000
tokens-per-day cap that appears only in the 429 body — so on the free tier
about 25 questions is one day's budget for the answer pass. Retrieval has no
such ceiling; run it over as many questions as you like.

Every question is checked against the paragraph it came from, so "did retrieval
find the right document" has an unambiguous answer.
"""

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SQUAD_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json"
DATA_PATH = Path(__file__).with_name("squad-dev-v2.0.json")
RESULTS_PATH = Path(__file__).with_name("squad-results.jsonl")

# A fixed seed so two runs are comparable. An eval that samples differently
# each time cannot tell a regression from a different draw.
SEED = 20260916

EVAL_USER = "squad-eval-user"


def download() -> None:
    import requests

    print(f"Downloading {SQUAD_URL} ...")
    resp = requests.get(SQUAD_URL, timeout=120)
    resp.raise_for_status()
    DATA_PATH.write_bytes(resp.content)
    print(f"Saved {DATA_PATH.name} ({len(resp.content):,} bytes)")


def load_samples(n_answerable: int, n_unanswerable: int) -> tuple[list[dict], list[dict]]:
    """Return (paragraphs, questions).

    One paragraph becomes one document. Questions carry the filename of the
    paragraph they came from, so retrieval has a ground truth to be scored
    against rather than a judgement call.
    """
    if not DATA_PATH.exists():
        raise SystemExit(f"{DATA_PATH.name} not found — run with --download first.")

    raw = json.loads(DATA_PATH.read_text())
    rng = random.Random(SEED)

    answerable, unanswerable, paragraphs = [], [], {}

    for article in raw["data"]:
        title = article["title"]
        for i, para in enumerate(article["paragraphs"]):
            filename = f"{_slug(title)}-{i}.txt"
            context = para["context"]
            for qa in para["qas"]:
                # SQuAD includes near-duplicate questions; one per paragraph
                # keeps the set from over-weighting a single passage.
                item = {
                    "question": qa["question"].strip(),
                    "source": filename,
                    "context": context,
                    "answers": sorted({a["text"] for a in qa.get("answers", [])}),
                    "answerable": not qa.get("is_impossible", False),
                }
                if item["answerable"] and item["answers"]:
                    answerable.append(item)
                elif not item["answerable"]:
                    unanswerable.append(item)
            paragraphs[filename] = context

    rng.shuffle(answerable)
    rng.shuffle(unanswerable)
    picked = answerable[:n_answerable] + unanswerable[:n_unanswerable]

    # Only ingest the paragraphs the sampled questions actually need. Ingesting
    # all 1,200 would make retrieval look harder than the questions require and
    # take far longer to embed.
    needed = {q["source"] for q in picked}
    docs = [{"filename": f, "text": paragraphs[f]} for f in sorted(needed)]
    return docs, picked


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "doc"


# Phrasings the system actually uses to decline. The first version of this
# checked for three literal strings and scored a 0.167 refusal rate that was
# really 0.667 — it missed "do not contain", "does not state" and "do not
# specify" while the model was declining perfectly well. A grader that invents
# failures is worse than no grader, because it sends you optimising something
# that was never broken.
_DECLINE = re.compile(
    r"(do(es)?\s+not|don'?t|cannot|can'?t|unable\s+to|no\s+information|"
    r"not\s+(stated|mentioned|specified|provided|included))"
    r"[^.]{0,80}?"
    r"(contain|mention|state|specify|provide|include|say|indicate|address|"
    r"answer|identify|determine|find|information|details?)",
    re.IGNORECASE,
)


def declined(answer: str) -> bool:
    """Did the system say the documents do not answer this?"""
    a = answer or ""
    return bool(_DECLINE.search(a)) or "nothing in them supports" in a.lower()


def token_f1(predicted: str, gold: str) -> float:
    """SQuAD's own overlap score.

    Exact substring matching punishes a correct answer for being written as
    prose or bullets — "very little work is needed to drive the pump" scored
    zero against "relatively little work is required to drive the pump". F1
    over tokens is what the benchmark itself uses, for exactly this reason.
    """
    p_tokens = normalize(predicted).split()
    g_tokens = normalize(gold).split()
    if not p_tokens or not g_tokens:
        return 0.0
    common = 0
    remaining = list(p_tokens)
    for t in g_tokens:
        if t in remaining:
            remaining.remove(t)
            common += 1
    if common == 0:
        return 0.0
    precision = common / len(p_tokens)
    recall = common / len(g_tokens)
    return 2 * precision * recall / (precision + recall)


def normalize(text: str) -> str:
    """SQuAD's own answer-matching normalisation: fold case, punctuation and
    articles, which are never what distinguishes a right answer from a wrong
    one."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ingest(docs: list[dict]) -> None:
    from rag.retrieval import ingest_document, list_documents, delete_document

    existing = {d["filename"]: d["id"] for d in list_documents(EVAL_USER)}
    for doc_id in existing.values():
        delete_document(doc_id, EVAL_USER)

    print(f"Ingesting {len(docs)} paragraphs...")
    for i, doc in enumerate(docs, 1):
        ingest_document(EVAL_USER, doc["filename"], doc["text"].encode())
        if i % 25 == 0:
            print(f"  {i}/{len(docs)}")
    print(f"  {len(docs)}/{len(docs)} done")


def evaluate_retrieval(questions: list[dict], top_k: int, threshold: float) -> dict:
    """Did the paragraph holding the answer come back? No LLM calls, so this is
    free and can run over hundreds of questions."""
    from rag.retrieval import retrieve_relevant_chunks

    answerable = [q for q in questions if q["answerable"]]
    hits = 0
    reciprocal_ranks = []
    matched_by = {"vector": 0, "keyword": 0, "both": 0}

    for q in answerable:
        chunks = retrieve_relevant_chunks(EVAL_USER, q["question"], top_k=top_k)
        files = [c["filename"] for c in chunks]
        if q["source"] in files:
            hits += 1
            rank = files.index(q["source"]) + 1
            reciprocal_ranks.append(1.0 / rank)
            matched_by[chunks[files.index(q["source"])].get("matched_by", "vector")] += 1
        else:
            reciprocal_ranks.append(0.0)

    total = len(answerable) or 1
    return {
        "questions": len(answerable),
        f"recall@{top_k}": round(hits / total, 3),
        "mrr": round(sum(reciprocal_ranks) / total, 3),
        "found_by": matched_by,
    }


def evaluate_answers(questions: list[dict], top_k: int, threshold: float) -> dict:
    """Does the answer contain the gold span, and does it decline when the
    paragraph genuinely does not answer the question?"""
    from rag.chat_agent import chat

    answerable = [q for q in questions if q["answerable"]]
    unanswerable = [q for q in questions if not q["answerable"]]

    correct = 0
    refused_correctly = 0
    judge_verdicts = {}
    wrong = []
    f1_scores: list[float] = []

    for i, q in enumerate(answerable, 1):
        # conversation_id=None every time: a fresh conversation per question,
        # so history from the previous one cannot leak into this answer.
        result = chat(EVAL_USER, None, q["question"],
                      top_k=top_k, similarity_threshold=threshold)
        raw = result.get("answer", "")
        answer = normalize(raw)
        # Exact containment is the strict reading; F1 is what SQuAD itself
        # scores, and is reported alongside because the strict number
        # under-counts answers that are right but phrased differently.
        exact = any(normalize(a) in answer for a in q["answers"])
        best_f1 = max((token_f1(raw, a) for a in q["answers"]), default=0.0)
        f1_scores.append(best_f1)
        if exact:
            correct += 1
        if not exact and best_f1 < 0.6:
            wrong.append({"q": q["question"], "expected": q["answers"],
                          "f1": round(best_f1, 2),
                          "got": raw[:160]})
        verdict = ((result.get("telemetry") or {}).get("llm_judge") or {}).get("verdict")
        judge_verdicts[verdict] = judge_verdicts.get(verdict, 0) + 1
        print(f"  answerable {i}/{len(answerable)}", end="\r", flush=True)

    for i, q in enumerate(unanswerable, 1):
        result = chat(EVAL_USER, None, q["question"],
                      top_k=top_k, similarity_threshold=threshold)
        # Declining means either returning no sources at all, or saying in
        # words that the documents do not answer this.
        if not result.get("sources") or declined(result.get("answer", "")):
            refused_correctly += 1
        print(f"  unanswerable {i}/{len(unanswerable)}", end="\r", flush=True)

    print(" " * 40, end="\r")
    return {
        "answerable": len(answerable),
        "answer_exact": round(correct / (len(answerable) or 1), 3),
        "answer_f1": round(sum(f1_scores) / (len(f1_scores) or 1), 3),
        "unanswerable": len(unanswerable),
        "refusal_rate": round(refused_correctly / (len(unanswerable) or 1), 3),
        "judge_verdicts": judge_verdicts,
        "_wrong": wrong[:5],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--download", action="store_true", help="fetch the SQuAD dev set")
    p.add_argument("--retrieval", action="store_true", help="retrieval metrics (free)")
    p.add_argument("--answers", action="store_true", help="answer metrics (spends Groq calls)")
    p.add_argument("--questions", type=int, default=25, help="answerable questions to sample")
    p.add_argument("--unanswerable", type=int, default=None,
                   help="unanswerable questions (default: a quarter of --questions)")
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--threshold", type=float, default=0.55)
    p.add_argument("--keep", action="store_true", help="leave the ingested paragraphs in place")
    args = p.parse_args()

    if args.download:
        download()
        if not (args.retrieval or args.answers):
            return 0

    if not (args.retrieval or args.answers):
        p.print_help()
        return 1

    n_unanswerable = args.unanswerable if args.unanswerable is not None else max(args.questions // 4, 1)
    docs, questions = load_samples(args.questions, n_unanswerable)

    print(f"SQuAD 2.0 — {len(docs)} paragraphs, "
          f"{sum(1 for q in questions if q['answerable'])} answerable, "
          f"{sum(1 for q in questions if not q['answerable'])} unanswerable\n")

    ingest(docs)
    print()

    report: dict = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "questions": args.questions, "top_k": args.top_k}

    if args.retrieval:
        start = time.time()
        r = evaluate_retrieval(questions, args.top_k, args.threshold)
        r["seconds"] = round(time.time() - start, 1)
        report["retrieval"] = r
        print("RETRIEVAL")
        for k, v in r.items():
            print(f"  {k:16} {v}")
        print()

    if args.answers:
        start = time.time()
        a = evaluate_answers(questions, args.top_k, args.threshold)
        a["seconds"] = round(time.time() - start, 1)
        wrong = a.pop("_wrong", [])
        report["answers"] = a
        print("ANSWERS")
        for k, v in a.items():
            print(f"  {k:16} {v}")
        if wrong:
            print("\n  first few misses:")
            for w in wrong:
                print(f"    Q: {w['q']}")
                print(f"       expected one of {w['expected']}")
                print(f"       got: {w['got']}")
        print()

    # Appended, not overwritten: one score is a snapshot, a series shows
    # whether a change helped.
    with RESULTS_PATH.open("a") as fh:
        fh.write(json.dumps(report) + "\n")
    print(f"Appended to {RESULTS_PATH.name}")

    if not args.keep:
        from rag.retrieval import list_documents, delete_document
        for d in list_documents(EVAL_USER):
            delete_document(d["id"], EVAL_USER)
        print("Cleaned up ingested paragraphs.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
