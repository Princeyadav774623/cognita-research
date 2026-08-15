from langgraph.graph import StateGraph, END
from graph.state import ResearchState
from agents.planner_agent import planner_agent
from agents.search_agent import search_agent
from agents.reader_agent import reader_agent_async
from agents.analyst_agent import analyst_agent
from agents.factcheck_agent import factcheck_agent
from agents.gap_analysis_agent import gap_analysis_agent
from agents.report_agent import report_agent
import logging

logger = logging.getLogger(__name__)


# =============================================
# AUTONOMOUS LANGGRAPH ORCHESTRATION
# Plan-and-Solve with Reflective Deep Research Loop
# =============================================

def should_continue_after_search(state: ResearchState) -> str:
    """Route after search: if no results found, route directly to report."""
    if not state.get("search_results"):
        logger.warning("[Graph] No search results — routing to report with error")
        return "report"
    return "read"


def should_loop_or_report(state: ResearchState) -> str:
    """Reflective loop: if evidence is insufficient and iterations remain, loop back to search."""
    is_sufficient = state.get("is_sufficient", True)
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 2)

    if not is_sufficient and iteration <= max_iterations:
        logger.info(f"[Graph] Reflective search loop triggered (Iteration {iteration}/{max_iterations})")
        return "search"

    logger.info("[Graph] Research verified and complete, routing to final report")
    return "report"


def build_research_graph():
    """Build and compile the multi-agent deep research graph."""
    graph = StateGraph(ResearchState)

    # Add all agent nodes (using high-speed async parallel reader)
    graph.add_node("planner", planner_agent)
    graph.add_node("search", search_agent)
    graph.add_node("read", reader_agent_async)
    graph.add_node("analyze", analyst_agent)
    graph.add_node("factcheck", factcheck_agent)
    graph.add_node("gap_analysis", gap_analysis_agent)
    graph.add_node("report", report_agent)

    # Set entry point
    graph.set_entry_point("planner")

    # Planner -> Search
    graph.add_edge("planner", "search")

    # Conditional routing after search
    graph.add_conditional_edges(
        "search",
        should_continue_after_search,
        {
            "read": "read",
            "report": "report",
        }
    )

    # Extraction & Synthesis Pipeline
    graph.add_edge("read", "analyze")
    graph.add_edge("analyze", "factcheck")
    graph.add_edge("factcheck", "gap_analysis")

    # Autonomous Gap-Analysis / Reflection Loop
    graph.add_conditional_edges(
        "gap_analysis",
        should_loop_or_report,
        {
            "search": "search",
            "report": "report",
        }
    )

    # Final Report -> END
    graph.add_edge("report", END)

    # Compile the graph
    compiled = graph.compile()
    logger.info("[Graph] Autonomous Deep Research graph compiled successfully")
    return compiled


# Singleton — build once, reuse
research_graph = build_research_graph()


def create_initial_state(query: str, session_id: str, max_iterations: int = 2) -> ResearchState:
    """Create a standardized initial research state."""
    return {
        "query": query,
        "session_id": session_id,
        "sub_queries": [query],
        "research_plan": [],
        "search_results": [],
        "source_documents": [],
        "draft_answer": "",
        "verified_claims": [],
        "overall_confidence": 0.0,
        "is_sufficient": False,
        "missing_information": [],
        "iteration": 1,
        "max_iterations": max_iterations,
        "final_report": "",
        "current_step": "starting",
        "error": None,
        "retry_count": 0,
        "cost_tracking": {"total_tokens": 0, "estimated_cost_usd": 0.0},
    }


async def run_research(query: str, session_id: str, max_iterations: int = 2):
    """Run the full research pipeline and return the final state."""
    initial_state = create_initial_state(query, session_id, max_iterations)
    logger.info(f"[Graph] Starting deep research for session {session_id}: {query}")
    final_state = await research_graph.ainvoke(initial_state)
    logger.info(f"[Graph] Deep research complete for session {session_id}")
    return final_state


async def stream_research(query: str, session_id: str, max_iterations: int = 2):
    """
    Stream research progress step by step.
    Yields state updates as each agent node completes.
    Used for WebSocket and SSE streaming.
    """
    initial_state = create_initial_state(query, session_id, max_iterations)

    async for event in research_graph.astream(initial_state):
        for node_name, state_update in event.items():
            yield {
                "node": node_name,
                "step": state_update.get("current_step", node_name),
                "data": get_step_summary(node_name, state_update),
                "state": state_update,
            }


def get_step_summary(node: str, state: dict) -> dict:
    """Extract relevant data for each step to send to frontend."""
    summaries = {
        "planner": {
            "message": f"Planned {len(state.get('sub_queries', []))} research angles",
            "sub_queries": state.get("sub_queries", []),
            "strategy": state.get("research_plan", [""])[0] if state.get("research_plan") else "",
        },
        "search": {
            "message": f"Found {len(state.get('search_results', []))} sources (Pass {state.get('iteration', 1)})",
            "count": len(state.get("search_results", [])),
        },
        "read": {
            "message": f"Read and verified {len(state.get('source_documents', []))} documents",
            "count": len(state.get("source_documents", [])),
        },
        "analyze": {
            "message": "Synthesized cross-source findings",
            "preview": state.get("draft_answer", "")[:200] + "...",
        },
        "factcheck": {
            "message": f"Fact verification confidence: {state.get('overall_confidence', 0):.0%}",
            "confidence": state.get("overall_confidence", 0),
            "claims": len(state.get("verified_claims", [])),
        },
        "gap_analysis": {
            "message": "Evaluated research depth & gaps",
            "is_sufficient": state.get("is_sufficient", True),
            "iteration": state.get("iteration", 1),
        },
        "report": {
            "message": "Final report generated with verified citations",
            "report": state.get("final_report", ""),
        },
    }
    return summaries.get(node, {"message": f"Step {node} complete"})

