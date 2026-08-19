"""Golden evaluation set.

A small synthetic corpus with facts chosen so ground truth is exact and
verifiable. Synthetic on purpose: real documents would let the model answer
from parametric knowledge instead of retrieval, which is precisely what this
set has to be able to detect.

Every question declares the document it must be answered from, plus the fact
that has to appear in the answer. Questions marked `answerable=False` are the
most important cases in the file — they check the system declines rather than
inventing, which is the entire promise of a grounded research tool.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Doc:
    filename: str
    text: str


@dataclass(frozen=True)
class Question:
    q: str
    # Filename the answer must come from. None when unanswerable.
    source: str | None
    # Substrings that must appear in a correct answer (any one is enough).
    expect_any: list[str] = field(default_factory=list)
    answerable: bool = True
    # Why this case exists — surfaced in failure output.
    probes: str = ""


DOCS = [
    Doc("ops-handbook.txt", """OPERATIONS HANDBOOK — REVISION 12

Incident response. Sev-1 incidents page the on-call engineer within 60 seconds.
The escalation window before a secondary engineer is paged is 8 minutes.
Post-incident reviews are due within 5 business days of resolution.

Deployment. Releases ship on Tuesdays and Thursdays only. A release requires two
approvals and a green staging run. Automated rollbacks complete in under 4 minutes.

Data retention. Customer telemetry is retained for 90 days. Audit logs are kept
for 7 years in cold storage. Deletion requests are honoured within 30 days.
"""),

    Doc("atlas-benchmark.txt", """PROJECT ATLAS — RETRIEVAL BENCHMARK, FEBRUARY 2026

Atlas is our internal retrieval stack. On the 1,200-question internal evaluation
set, Atlas reduced the ungrounded-answer rate from 21.7 percent to 4.2 percent.
Median end-to-end latency was 340 milliseconds and the p99 was 1.9 seconds.
The Atlas index contains 3.1 million passages drawn from 14,000 documents.
Reranking contributed 61 percent of the total quality improvement.
The benchmark was conducted by the Retrieval team on dedicated hardware.
"""),

    Doc("vendor-terms.txt", """VENDOR AGREEMENT SUMMARY — NORTHWIND ANALYTICS

The contract term is 36 months commencing 1 April 2026. Annual fees are
340,000 US dollars, invoiced quarterly in advance. Either party may terminate
for convenience with 90 days written notice. The uptime commitment is 99.95
percent measured monthly, with service credits of 10 percent of monthly fees
per full hour of downtime beyond the commitment.
"""),
]


QUESTIONS = [
    # --- direct lookups: the wording closely matches the source
    Question("What is the escalation window before a secondary engineer is paged?",
             "ops-handbook.txt", ["8 minutes", "8-minute", "eight minutes"],
             probes="direct phrasing, should be a strong match"),
    Question("How long are audit logs retained?",
             "ops-handbook.txt", ["7 years", "seven years"],
             probes="direct lookup inside a longer document"),
    Question("What was the median end-to-end latency in the Atlas benchmark?",
             "atlas-benchmark.txt", ["340", "340 milliseconds", "340ms"],
             probes="numeric fact retrieval"),
    Question("What are the annual fees in the Northwind agreement?",
             "vendor-terms.txt", ["340,000", "340000", "$340,000"],
             probes="numeric fact; note 340 also appears in atlas — tests disambiguation"),

    # --- paraphrased: the answer is present but the wording differs
    Question("How quickly can we undo a bad release?",
             "ops-handbook.txt", ["4 minutes", "four minutes", "under 4"],
             probes="paraphrase — 'undo' never appears in the document"),
    Question("Which days of the week do we ship?",
             "ops-handbook.txt", ["Tuesday", "Thursday"],
             probes="paraphrase; this exact case regressed at threshold 0.65"),
    Question("How much did Atlas cut hallucinations by?",
             "atlas-benchmark.txt", ["4.2", "21.7"],
             probes="paraphrase — document says 'ungrounded-answer rate'"),
    Question("Can we get out of the Northwind contract early?",
             "vendor-terms.txt", ["90 days", "convenience", "terminate"],
             probes="intent-level paraphrase of a termination clause"),

    # --- specific detail buried among similar numbers
    Question("How many passages are in the Atlas index?",
             "atlas-benchmark.txt", ["3.1 million", "3,100,000", "3.1m"],
             probes="must not confuse with the 14,000 documents figure"),
    Question("What is the uptime commitment?",
             "vendor-terms.txt", ["99.95"],
             probes="precise figure among several percentages"),

    # --- unanswerable: the corpus genuinely does not contain this.
    #     These are the anti-hallucination cases.
    Question("What is the company's parental leave policy?",
             None, answerable=False,
             probes="plausible corporate topic, absent from the corpus"),
    Question("Who is the CEO of Northwind Analytics?",
             None, answerable=False,
             probes="about a document's subject, but the fact is not in it"),
    Question("What was Atlas's accuracy on the MMLU benchmark?",
             None, answerable=False,
             probes="adjacent to real content — the tempting hallucination"),
    Question("How many employees does the Retrieval team have?",
             None, answerable=False,
             probes="the team is named in the corpus, its size is not"),
]

ANSWERABLE = [q for q in QUESTIONS if q.answerable]
UNANSWERABLE = [q for q in QUESTIONS if not q.answerable]
