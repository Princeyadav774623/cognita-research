from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================
# REPORT AGENT
# Generates the final polished report
# with citations, confidence score, and summary
# =============================================

REPORT_PROMPT = """You are a professional research report writer.
Generate a clean, well-structured research report using the provided answer and verification results.

The report must include:
1. ## Summary (2-3 sentence overview)
2. ## Detailed Findings (the main content, with citations)
3. ## Sources (list all sources used)
4. ## Confidence Assessment (based on fact-check results)

Format everything in clean Markdown.
Use citations like [Source Title](URL) inline when referencing specific facts.
"""


def report_agent(state: ResearchState) -> ResearchState:
    logger.info("[ReportAgent] Generating final report")

    llm = ChatGroq(
        model=settings.groq_model_fast,    # Fast model is enough for formatting
        api_key=settings.groq_api_key,
        temperature=0.3,
        max_tokens=2048,
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

Available Sources:
{sources_text}

Please generate the final polished report.
"""),
    ]

    try:
        response = invoke_with_retry(llm, messages)
        report = response.content.strip()

        # Add metadata footer
        report += f"\n\n---\n*Confidence Score: {confidence:.0%} ({confidence_label}) | Sources analyzed: {len(state.get('source_documents', []))}*"

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
    if score >= 0.8:
        return "High Confidence"
    elif score >= 0.6:
        return "Moderate Confidence"
    elif score >= 0.4:
        return "Low Confidence"
    else:
        return "Uncertain"
