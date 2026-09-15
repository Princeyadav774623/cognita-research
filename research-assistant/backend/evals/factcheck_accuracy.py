"""Measure whether "verified" actually means "true".

The product reports a confidence score per claim. Nothing has ever checked that
score against reality — only that the pipeline produced one. This is the
measurement that decides whether the number is worth showing, and it is the
number the whole architecture exists to earn.

It cannot be automated. A model grading its own verdicts reproduces its own
blind spots, so the labels have to come from a person:

    1. python -m evals.factcheck_accuracy --export run.jsonl
         Pulls the claims and verdicts out of stored sessions into a file with
         a blank `human_verdict` on every row.

    2. Fill in each `human_verdict`: true / false / unclear.
       "unclear" is not a cop-out — it is the honest answer when the sources
       genuinely do not settle it, and those rows are excluded rather than
       counted as either outcome.

    3. python -m evals.factcheck_accuracy --score run.jsonl
         Reports precision, recall and calibration against those labels.

Precision is the one that matters commercially: of the claims shown to a user
as verified, how many were actually true. A confident wrong answer is the
failure mode a research tool cannot afford.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VALID_LABELS = {"true", "false", "unclear"}


def export_claims(out_path: Path, limit: int, user_id: str) -> int:
    """Write one user's stored claims to a labelling file, one JSON object per line.

    Scoped to a user because Row-Level Security applies to the runtime role:
    an unscoped session sees nothing at all, by design. Pass the user whose
    sessions you want to audit.
    """
    from db import ResearchSessionRecord, tenant_session

    with tenant_session(user_id) as db:
        rows = (
            db.query(ResearchSessionRecord)
            .filter(ResearchSessionRecord.user_id == user_id)
            .order_by(ResearchSessionRecord.created_at.desc())
            .limit(limit)
            .all()
        )

    written = 0
    with out_path.open("w") as fh:
        for row in rows:
            for claim in (row.verified_claims or []):
                fh.write(json.dumps({
                    "session_id": row.id,
                    "query": row.query,
                    "claim": claim.get("claim", ""),
                    "machine_verified": bool(claim.get("verified")),
                    "machine_confidence": float(claim.get("confidence", 0.0)),
                    "independently_corroborated": bool(claim.get("independently_corroborated")),
                    "cited_source": claim.get("source", ""),
                    "human_verdict": "",      # <- fill in: true | false | unclear
                }) + "\n")
                written += 1
    return written


def score(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    labelled = [r for r in rows if r.get("human_verdict", "").strip().lower() in VALID_LABELS]
    bad = [r for r in rows if r.get("human_verdict", "").strip() and r not in labelled]
    if bad:
        print(f"warning: {len(bad)} row(s) have a label outside {sorted(VALID_LABELS)} — ignored")

    decided = [r for r in labelled if r["human_verdict"].lower() != "unclear"]
    if not decided:
        return {"error": "no rows carry a true/false label yet"}

    tp = sum(1 for r in decided if r["machine_verified"] and r["human_verdict"] == "true")
    fp = sum(1 for r in decided if r["machine_verified"] and r["human_verdict"] == "false")
    fn = sum(1 for r in decided if not r["machine_verified"] and r["human_verdict"] == "true")
    tn = sum(1 for r in decided if not r["machine_verified"] and r["human_verdict"] == "false")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    # Calibration: among claims the model was confident about, how often was it
    # right? A score that does not track truth is worse than no score, because
    # the interface presents it as if it does.
    buckets = {"0.0-0.5": [], "0.5-0.7": [], "0.7-0.9": [], "0.9-1.0": []}
    for r in decided:
        c = r["machine_confidence"]
        key = "0.0-0.5" if c < 0.5 else "0.5-0.7" if c < 0.7 else "0.7-0.9" if c < 0.9 else "0.9-1.0"
        buckets[key].append(1 if r["human_verdict"] == "true" else 0)

    # Does the independent-corroboration flag actually predict truth? If it
    # does not, the extra Tavily calls per claim are buying nothing.
    corr = [r for r in decided if r["independently_corroborated"]]
    uncorr = [r for r in decided if not r["independently_corroborated"]]

    def hit_rate(rows_):
        return round(sum(1 for r in rows_ if r["human_verdict"] == "true") / len(rows_), 3) if rows_ else None

    return {
        "rows_total": len(rows),
        "rows_labelled": len(labelled),
        "rows_unclear_excluded": len(labelled) - len(decided),
        "confusion": {"true_positive": tp, "false_positive": fp,
                      "false_negative": fn, "true_negative": tn},
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "calibration": {k: {"n": len(v), "actually_true": round(sum(v) / len(v), 3)}
                        for k, v in buckets.items() if v},
        "independently_corroborated_accuracy": hit_rate(corr),
        "not_corroborated_accuracy": hit_rate(uncorr),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--export", metavar="FILE", help="write stored claims to a labelling file")
    p.add_argument("--score", metavar="FILE", help="score a labelled file")
    p.add_argument("--limit", type=int, default=50, help="sessions to export from (default 50)")
    p.add_argument("--user", default="dev-guest-user-001",
                   help="whose sessions to audit; RLS means this cannot be omitted")
    args = p.parse_args()

    if args.export:
        out = Path(args.export)
        n = export_claims(out, args.limit, args.user)
        print(f"Wrote {n} claim(s) to {out}. Fill in human_verdict on each row, then --score it.")
        if n == 0:
            print(f"No claims found for user {args.user!r}. Run some research first, "
                  "or pass --user for the right account.")
        return 0

    if args.score:
        result = score(Path(args.score))
        print(json.dumps(result, indent=2))
        if "error" in result:
            return 1
        prec = result["precision"]
        if prec is not None and prec < 0.8:
            print(f"\nPrecision {prec:.0%}: more than one in five claims shown as verified was not true.")
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
