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


class ResearchPlan(BaseModel):
    sub_queries: List[str] = Field(
        description="3 to 5 targeted, distinct search queries that together comprehensively cover the research topic.",
        min_length=1,
        max_length=5
    )
    strategy: str = Field(
        description="Brief explanation of the research strategy and angles being explored."
    )


PLANNER_SYSTEM_PROMPT = """You are a Principal Research Scientist and Lead Investigator.
Your task is to analyze the user's research query and decompose it into 3-5 specific, distinct, and highly targeted search queries.

Guidelines:
- Each sub-query must explore a specific dimension (e.g. background/state-of-the-art, empirical benchmarks, technical tradeoffs, challenges/criticisms).
- Make queries keyword-rich and optimal for modern web search engines.
- Avoid vague or overlapping queries.
"""


def planner_agent(state: ResearchState) -> ResearchState:
    query = state["query"]
    logger.info(f"[PlannerAgent] Decomposing research query: {query}")

    llm = ChatGroq(
        model=settings.groq_model_fast,
        api_key=settings.groq_api_key,
        temperature=0.2,
    )

    sub_queries = []
    strategy = "Multi-angle search plan"

    # Attempt 1: Structured LLM output
    try:
        structured_llm = llm.with_structured_output(ResearchPlan)
        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=f"Decompose this research question into a comprehensive search plan: {query}"),
        ]
        plan = invoke_with_retry(structured_llm, messages)
        if isinstance(plan, dict):
            sub_queries = plan.get("sub_queries", [])
            strategy = plan.get("strategy", strategy)
        elif isinstance(plan, ResearchPlan):
            sub_queries = plan.sub_queries
            strategy = plan.strategy
    except Exception as e:
        logger.debug(f"[PlannerAgent] Structured output fallback: {e}")

    # Attempt 2: Direct JSON prompt parsing
    if not sub_queries:
        try:
            messages = [
                SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=f"""Decompose this research question into 3-5 distinct search queries: {query}
Return ONLY valid JSON format:
{{"sub_queries": ["query 1", "query 2", "query 3"], "strategy": "explanation"}}"""),
            ]
            resp = invoke_with_retry(llm, messages)
            cleaned = clean_llm_response(resp.content)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                sub_queries = data.get("sub_queries", [])
                strategy = data.get("strategy", strategy)
        except Exception as e2:
            logger.warning(f"[PlannerAgent] JSON planning fallback failed: {e2}")

    if not sub_queries:
        sub_queries = [query]
        strategy = "Direct query search"

    logger.info(f"[PlannerAgent] Generated {len(sub_queries)} sub-queries: {sub_queries}")

    return {
        **state,
        "sub_queries": sub_queries,
        "research_plan": [strategy],
        "current_step": "plan_done",
    }
