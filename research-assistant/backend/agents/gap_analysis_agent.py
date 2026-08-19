from pydantic import BaseModel, Field
from typing import List
import json
import re
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry, clean_llm_response
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


class GapAnalysisResult(BaseModel):
    is_sufficient: bool = Field(
        description="True if the findings are sufficient and verified enough to write the final report, False if critical information or key angles are missing."
    )
    followup_sub_queries: List[str] = Field(
        description="1 to 3 targeted follow-up queries to fill the missing gaps if is_sufficient is False.",
        default_factory=list
    )
    missing_aspects: List[str] = Field(
        description="Specific aspects or claims that lacked evidence.",
        default_factory=list
    )
    reflection_notes: str = Field(
        description="Brief explanation of findings sufficiency."
    )


GAP_SYSTEM_PROMPT = """You are a Research Director evaluating whether the collected evidence and fact-check results are sufficient to produce an authoritative, comprehensive report.

Criteria to pass (is_sufficient = True):
1. The research draft covers the core aspects of the query.
2. Fact-check confidence is >= 0.70.
3. No glaring unverified claims or obvious missing perspectives.

If any core aspect is unaddressed or confidence is low, set is_sufficient = False and generate 1-3 targeted follow-up search queries.
"""


def gap_analysis_agent(state: ResearchState) -> ResearchState:
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 2)
    overall_confidence = state.get("overall_confidence", 0.0)

    logger.info(f"[GapAnalysisAgent] Evaluating research depth (Iteration {iteration}/{max_iterations}, Confidence: {overall_confidence:.0%})")

    # If maximum iterations reached, force sufficiency to prevent infinite loops
    if iteration >= max_iterations:
        logger.info("[GapAnalysisAgent] Max iterations reached, proceeding to report generation.")
        return {
            **state,
            "is_sufficient": True,
            "current_step": "gap_analysis_done",
        }

    # If confidence is exceptionally high and sources exist, short-circuit
    if overall_confidence >= 0.85 and len(state.get("source_documents", [])) >= 3:
        logger.info("[GapAnalysisAgent] High confidence and strong source coverage achieved.")
        return {
            **state,
            "is_sufficient": True,
            "missing_information": [],
            "current_step": "gap_analysis_done",
        }

    llm = ChatGroq(
        model=settings.groq_model_fast,
        api_key=settings.groq_api_key,
        temperature=0.1,
    )

    unverified = [c["claim"] for c in state.get("verified_claims", []) if not c.get("verified")]

    is_sufficient = True
    followups = []
    missing = []

    # Attempt 1: Structured LLM Output
    try:
        structured_llm = llm.with_structured_output(GapAnalysisResult)
        messages = [
            SystemMessage(content=GAP_SYSTEM_PROMPT),
            HumanMessage(content=f"""
Research Query: {state['query']}
Current Iteration: {iteration}
Overall Confidence: {overall_confidence:.0%}

Draft Answer:
{state.get('draft_answer', '')[:1500]}

Unverified / Low-confidence claims:
{unverified}

Number of sources analyzed: {len(state.get('source_documents', []))}

Assess whether we have enough evidence or need another targeted search loop.
"""),
        ]
        result = invoke_with_retry(structured_llm, messages)
        if isinstance(result, GapAnalysisResult):
            is_sufficient = result.is_sufficient
            followups = result.followup_sub_queries or []
            missing = result.missing_aspects or []
        elif isinstance(result, dict):
            is_sufficient = bool(result.get("is_sufficient", True))
            followups = result.get("followup_sub_queries", [])
            missing = result.get("missing_aspects", [])
    except Exception as e:
        logger.debug(f"[GapAnalysisAgent] Structured output fallback: {e}")
        # Attempt 2: Direct JSON prompt parsing
        try:
            json_prompt = f"""Evaluate research sufficiency for: {state['query']}
Current iteration: {iteration}
Overall confidence: {overall_confidence:.0%}
Draft: {state.get('draft_answer', '')[:1000]}
Unverified: {unverified}
Sources: {len(state.get('source_documents', []))}

Respond ONLY with a valid JSON object:
{{
  "is_sufficient": true,
  "followup_sub_queries": ["query1"],
  "missing_aspects": ["aspect1"],
  "reflection_notes": "notes"
}}"""
            resp = invoke_with_retry(llm, [SystemMessage(content=GAP_SYSTEM_PROMPT), HumanMessage(content=json_prompt)])
            cleaned = clean_llm_response(resp.content)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                is_sufficient = bool(data.get("is_sufficient", True))
                followups = data.get("followup_sub_queries", [])
                missing = data.get("missing_aspects", [])
        except Exception as e2:
            logger.warning(f"[GapAnalysisAgent] Gap analysis fallback error: {e2}")
            is_sufficient = True

    logger.info(f"[GapAnalysisAgent] Sufficient: {is_sufficient}, Follow-up queries: {followups}")

    return {
        **state,
        "is_sufficient": is_sufficient,
        "sub_queries": followups if (not is_sufficient and followups) else state.get("sub_queries", []),
        "missing_information": missing,
        "iteration": iteration + 1,
        "current_step": "gap_analysis_done",
    }
