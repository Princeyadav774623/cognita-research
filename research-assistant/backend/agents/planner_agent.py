from pydantic import BaseModel, Field
from typing import List
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState
from utils import invoke_with_retry
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

    try:
        # Use structured output for deterministic Pydantic validation
        structured_llm = llm.with_structured_output(ResearchPlan)
        messages = [
            SystemMessage(content=PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=f"Decompose this research question into a comprehensive search plan: {query}"),
        ]
        plan = invoke_with_retry(structured_llm, messages)
        
        # plan can be ResearchPlan instance or dict depending on parsing
        if isinstance(plan, dict):
            sub_queries = plan.get("sub_queries", [query])
            strategy = plan.get("strategy", "Direct search plan")
        elif isinstance(plan, ResearchPlan):
            sub_queries = plan.sub_queries
            strategy = plan.strategy
        else:
            sub_queries = [query]
            strategy = "Direct search plan"

        logger.info(f"[PlannerAgent] Generated {len(sub_queries)} sub-queries: {sub_queries}")

        return {
            **state,
            "sub_queries": sub_queries,
            "research_plan": [strategy],
            "current_step": "plan_done",
        }
    except Exception as e:
        logger.warning(f"[PlannerAgent] Structured planning failed, falling back to direct query: {e}")
        return {
            **state,
            "sub_queries": [query],
            "research_plan": ["Fallback direct search plan"],
            "current_step": "plan_done",
        }
