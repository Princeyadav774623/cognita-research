# Golden evaluation set

Measures whether the retrieval and answering pipeline actually works, and fails
the build when it regresses.

```bash
cd backend
python -m evals.run              # retrieval only (~25s, no LLM calls)
python -m evals.run --answers    # also generate and grade answers (~2.5min)
python -m evals.run --update     # accept current scores as the new baseline
```

Exits non-zero when a metric drops more than 0.05 below `baseline.json`.

## Metrics

| Metric | Meaning | Baseline |
|---|---|---|
| `retrieval_recall` | Answerable questions where the loop surfaced the correct source document | 1.00 |
| `answer_accuracy` | Answers containing the expected fact | 1.00 |
| `refusal_rate` | Unanswerable questions correctly declined instead of invented | 1.00 |
| `unanswerable_retrieved_something` | Unanswerable questions that still pulled chunks (lower is better) | 1.00 |

That last metric sits at its worst value and that is expected, not a defect:
`agentic_retrieve` returns best-effort chunks even when its grader is
unconvinced. What matters is that the answer layer then declines anyway —
`refusal_rate` is the metric that carries the anti-hallucination guarantee.
It is tracked so a change that starts *answering* those questions is visible.

## Why the corpus is synthetic

Real documents let a model answer from what it already knows, so a retrieval
failure can hide behind parametric knowledge. Facts here (`Project Atlas`
reduced ungrounded answers from 21.7% to 4.2%) exist nowhere else, so an
answer containing them proves retrieval worked.

The four unanswerable questions are the most valuable rows in the set. They sit
deliberately close to real content — asking Atlas's MMLU score when Atlas is
real but that benchmark is not — because that adjacency is where a grounded
system is most tempted to invent.

## Adding cases

Add a `Question` to `dataset.py` with the source document and the strings a
correct answer must contain, then re-run with `--update`. Note the `probes`
field: it explains why the case exists and is printed on failure, so a future
failure is diagnosable rather than mysterious.

## Grading

Answers are matched after Unicode normalization. This is not cosmetic: models
emit `8 minutes` (narrow no-break space) and non-breaking hyphens, and a
naive substring test scored four perfect answers as failures — reporting 0.60
when the true figure was 1.00. A harness that invents failures gets ignored,
so `normalize()` is covered by its own unit tests.
