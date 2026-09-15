import re

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry, clean_llm_response, normalize_url
import logging

logger = logging.getLogger(__name__)

from agents.triage_agent import USER_VISIBLE_TAG  # single definition of the tag
settings = get_settings()


# =============================================
# REPORT AGENT
# Generates the final polished report
# with citations, confidence score, and summary
# =============================================

REPORT_PROMPT = """You are writing a research report for an intelligent reader
who is new to this topic. Write the way a good teacher explains something to a
colleague: plainly, in full sentences, with the reasoning visible.

Structure — write exactly these two sections and nothing after them:
1. ## Summary — 2-3 sentences answering the question directly. Someone who
   reads only this should come away with the actual answer, not a description
   of what the report will cover.
2. ## Detailed Findings — the substance, with citations.

Do NOT write a Sources list or a Confidence Assessment. Both are appended
afterwards from the run's own records, so anything you write there would be a
second, less accurate copy.

How to write the findings:

- Explain, don't label. A term or component needs a sentence saying what it is
  and why it matters, not a two-word gloss. "Edge — routing logic" tells a
  newcomer nothing; "An edge decides which step runs next, by looking at the
  current state — this is what lets the graph loop or branch instead of running
  straight through" tells them something.
- Prefer prose to fragments. Tables are for comparing several things across the
  same few dimensions. If a table's cells are turning into single words or
  sentence fragments, the material wanted paragraphs instead.
- Define a term the first time you use it, in the same sentence.
- Say why something matters, not only that it exists. A fact with no
  consequence attached is hard to remember and easy to skip.
- Use concrete numbers, dates and names from the sources wherever they exist.
- No filler openers ("In today's rapidly evolving landscape"), no restating the
  question back, no promising what the next section will do.
- Contractions and plain words are fine. "Uses" beats "utilises". Keep sentences
  short enough to read once.

Formatting:

- Markdown. GitHub-flavoured tables are supported and render properly.
- Cite inline as [Source Title](URL) at the specific claim it supports, not in
  a clump at the end of a paragraph.

Visuals — use them when the material calls for one, never as decoration:

- ALWAYS include a chart when the sources give you three or more comparable
  numbers (costs, percentages, counts, growth over time). A reader compares
  quantities far faster in a chart than in a sentence, and numbers buried in
  prose are the most commonly skipped part of a report. Use a `chart` fence
  carrying JSON:

  ```chart
  {"type": "bar", "title": "Levelised cost by source", "unit": "$",
   "data": [{"label": "Solar", "value": 40}, {"label": "Wind", "value": 50},
            {"label": "Gas", "value": 70}]}
  ```

  type is "bar" to compare things, "line" for change over time, "pie" for
  shares of one whole. Use only real figures from the sources — never estimate
  a value to fill a gap, and never invent a data point to round out a chart. If
  you only have two numbers, write them in a sentence instead.

- Include a diagram when the answer involves a flow, a cycle, a decision or a
  hierarchy. Use a `mermaid` fence:

  ```mermaid
  flowchart LR
    A[Question] --> B[Plan]
    B --> C[Search]
    C --> D{Enough evidence?}
    D -- no --> C
    D -- yes --> E[Report]
  ```

  Roughly 4-8 nodes, short labels, one diagram is plenty.

- A purely factual question with no quantities and no process needs neither. An
  unnecessary chart implies a precision the answer does not have.
"""


# Markdown inline links: [label](url). Bare URLs are ignored — an unlinked URL
# in prose isn't presented to the reader as a citation.
_MARKDOWN_LINK = re.compile(r"\[([^\]]{1,300})\]\((https?://[^\s)]+)\)")


def audit_citations(report: str, source_documents: list) -> dict:
    """Check that every URL the report cites is one this run actually read.

    The product's whole promise is that claims trace back to sources, and
    nothing verified that the trace resolved. A model asked to "cite sources"
    will occasionally cite a plausible URL it was never given — which reads
    exactly like a real citation to someone skimming the report.

    Nothing is rewritten: silently deleting a citation would hide the problem
    rather than surface it. The counts go in the report footer and the
    offending URLs go to the log.
    """
    known = {normalize_url(d.get("url", "")) for d in source_documents if d.get("url")}
    cited = [(label, url) for label, url in _MARKDOWN_LINK.findall(report)]

    resolved, unresolved = [], []
    for label, url in cited:
        (resolved if normalize_url(url) in known else unresolved).append((label, url))

    if unresolved:
        logger.warning(
            "[ReportAgent] %d of %d citations do not resolve to a source read in this run: %s",
            len(unresolved), len(cited),
            ", ".join(url for _, url in unresolved[:5]),
        )

    return {
        "total": len(cited),
        "resolved": len(resolved),
        "unresolved": [url for _, url in unresolved],
    }


def _sources_section(documents: list) -> str:
    """The sources list, built from what was actually read.

    Corpus documents are the user's own uploads and have no clickable URL, so
    they are named rather than linked.
    """
    if not documents:
        return "_No sources were retrieved for this question._"

    lines = []
    for i, doc in enumerate(documents, 1):
        title = doc.get("title") or "Untitled source"
        url = doc.get("url", "")
        if doc.get("origin") == "corpus" or url.startswith("upload://"):
            entry = f"{i}. {title} — your uploaded document"
        else:
            entry = f"{i}. [{title}]({url})"
        if doc.get("via_fallback"):
            entry += " _(search snippet only — full text could not be extracted)_"
        lines.append(entry)
    return "\n".join(lines)


def _confidence_section(state: ResearchState) -> str:
    """What the score is, how it was reached, and what would raise it."""
    confidence = state.get("overall_confidence", 0.0)
    label = get_confidence_label(confidence)
    claims = state.get("verified_claims", [])
    corroborated = sum(1 for c in claims if c.get("independently_corroborated"))

    parts = [f"**{confidence:.0%} — {label}**", ""]

    if claims:
        supported = sum(1 for c in claims if c.get("verified"))
        parts.append(
            f"{supported} of {len(claims)} key claims were supported by the sources, "
            f"and {corroborated} held up against a source the answer was not written from."
        )
        parts.append("")

    for factor in state.get("confidence_factors") or []:
        parts.append(f"- **{factor['label']}** — {factor['detail']}")

    limits = state.get("confidence_to_improve") or []
    if limits:
        parts += ["", "**What would raise this score**", ""]
        parts += [f"- {note}" for note in limits]

    return "\n".join(parts)


def report_agent(state: ResearchState) -> ResearchState:
    logger.info("[ReportAgent] Generating final report")

    # The report is what the user actually reads, so it gets the stronger
    # model. It used to use the fast one, on the reasoning that this node only
    # formats — but the prompt asks it to write the whole findings section, so
    # the weaker model was rewriting, and flattening, the 120B model's draft.
    #
    # The extra tokens are paid for by no longer asking it to reproduce the
    # sources list and confidence block, which are appended deterministically
    # below from data we already hold exactly.
    llm = ChatGroq(
        model=settings.groq_model_smart,
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=3072,
    )

    # Build verified claims summary
    claims_text = format_claims(state.get("verified_claims", []))
    confidence = state.get("overall_confidence", 0.5)
    confidence_label = get_confidence_label(confidence)

    # Build sources list
    sources_text = format_sources(state.get("source_documents", []))

    messages = [
        SystemMessage(content=REPORT_PROMPT),
        HumanMessage(content=f"""
Research Question: {state["query"]}

Draft Answer:
{state.get("draft_answer", "No answer generated")}

Fact-Check Results (Overall Confidence: {confidence:.0%} — {confidence_label}):
{claims_text}

Available Sources (cite these inline; the full list is appended automatically):
{sources_text}

Write the Summary and Detailed Findings.
"""),
    ]

    try:
        # Tagged so the graph streams these tokens to the client — the report
        # is the deliverable, and watching it appear beats watching a spinner.
        response = invoke_with_retry(llm.with_config({"tags": [USER_VISIBLE_TAG]}), messages)
        report = clean_llm_response(response.content)

        # Add metadata footer. The fallback count matters: a source that
        # couldn't be scraped (403, paywall, JS-rendered page) silently
        # degrades to the search engine's two-sentence snippet, and without
        # this line that read as a normal source no different from a fully
        # read paper — a real quality regression the report never disclosed.
        source_documents = state.get("source_documents", [])
        tracked = [d for d in source_documents if d.get("via_fallback") is not None]
        fallback_note = ""
        if tracked:
            full_text_count = sum(1 for d in tracked if not d.get("via_fallback"))
            fallback_note = f" | Full text extracted: {full_text_count}/{len(tracked)} web sources"

        # Audit before appending: the generated sources list resolves by
        # construction, so including it would inflate the score this check
        # exists to report honestly.
        citations = audit_citations(report, source_documents)

        # Sources and the confidence breakdown are facts, not prose. Building
        # them here instead of asking the model to reproduce them removes a
        # place it could invent a reference, and guarantees the list matches
        # what the run actually read.
        report += "\n\n## Sources\n\n" + _sources_section(source_documents)
        report += "\n\n## Confidence assessment\n\n" + _confidence_section(state)
        citation_note = ""
        if citations["total"]:
            citation_note = f" | Citations resolved: {citations['resolved']}/{citations['total']}"
            if citations["unresolved"]:
                citation_note += " (unresolved links are not from sources read in this run)"

        # Independent corroboration. Verification against only the analyst's own
        # sources is circular, so the two numbers are reported separately.
        claims = state.get("verified_claims", [])
        corroborated = sum(1 for c in claims if c.get("independently_corroborated"))
        corroboration_note = ""
        if claims:
            corroboration_note = f" | Independently corroborated: {corroborated}/{len(claims)} claims"

        report += (
            f"\n\n---\n*Confidence Score: {confidence:.0%} ({confidence_label}) "
            f"| Sources analyzed: {len(source_documents)}{fallback_note}"
            f"{citation_note}{corroboration_note}*"
        )

        logger.info("[ReportAgent] Final report generated successfully")

        return {
            **state,
            "final_report": report,
            "current_step": "complete",
        }

    except Exception as e:
        logger.error(f"[ReportAgent] Error: {e}")
        # Fallback — return the draft answer as the report
        return {
            **state,
            "final_report": state.get("draft_answer", "Report generation failed."),
            "current_step": "complete",
            "error": str(e),
        }


def format_claims(claims: list) -> str:
    if not claims:
        return "No claims were verified."
    lines = []
    for c in claims:
        status = "✓ Verified" if c["verified"] else "✗ Unverified"
        lines.append(f"- {status} ({c['confidence']:.0%}): {c['claim']}")
    return "\n".join(lines)


def format_sources(documents: list) -> str:
    if not documents:
        return "No sources available."
    lines = []
    for doc in documents:
        lines.append(f"- [{doc['title']}]({doc['url']})")
    return "\n".join(lines)


def get_confidence_label(score: float) -> str:
    """Bands must match CONFIDENCE_BANDS in frontend/src/confidence.ts. They
    previously disagreed in three places, so a 0.55 score rendered as a
    moderate-coloured badge reading "Low Grounding"."""
    if score >= 0.8:
        return "High Confidence"
    elif score >= 0.6:
        return "Moderate Confidence"
    elif score >= 0.4:
        return "Low Confidence"
    else:
        return "Uncertain"
