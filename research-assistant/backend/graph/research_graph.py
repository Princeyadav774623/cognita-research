from langgraph.graph import StateGraph, END
from graph.state import ResearchState
from agents.triage_agent import triage_agent
from agents.planner_agent import planner_agent
from agents.search_agent import search_agent
from agents.reader_agent import reader_agent_async
from agents.corpus_agent import corpus_agent
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

def route_after_triage(state: ResearchState) -> str:
    """A message that needs no research is already answered — go straight to
    the end rather than manufacturing a pipeline run for it."""
    if state.get("complexity") == "chat":
        logger.info("[Graph] Non-research message — answered directly, skipping the pipeline")
        return "done"
    return "planner"


def should_continue_after_search(state: ResearchState) -> str:
    """Route after search. A web dead end is no longer a dead end for the run:
    the answer may be in the user's own uploaded documents, so skip the reader
    and go straight to the corpus rather than bailing out to the report."""
    if not state.get("search_results"):
        logger.warning("[Graph] No web results — falling through to the user's corpus")
        return "corpus"
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
    graph.add_node("triage", triage_agent)
    graph.add_node("planner", planner_agent)
    graph.add_node("search", search_agent)
    graph.add_node("read", reader_agent_async)
    graph.add_node("corpus", corpus_agent)
    graph.add_node("analyze", analyst_agent)
    graph.add_node("factcheck", factcheck_agent)
    graph.add_node("gap_analysis", gap_analysis_agent)
    graph.add_node("report", report_agent)

    # Triage runs first and decides how much work the rest of the graph does.
    graph.set_entry_point("triage")

    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "planner": "planner",
            "done": END,
        }
    )

    # Planner -> Search
    graph.add_edge("planner", "search")

    # Conditional routing after search
    graph.add_conditional_edges(
        "search",
        should_continue_after_search,
        {
            "read": "read",
            "corpus": "corpus",
        }
    )

    # Extraction & Synthesis Pipeline. The corpus sits between reading the web
    # and synthesising, so the analyst sees web pages and the user's own
    # documents as one evidence set.
    graph.add_edge("read", "corpus")
    graph.add_edge("corpus", "analyze")
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


def create_initial_state(
    query: str, session_id: str, max_iterations: int = 2, user_id: str | None = None
) -> ResearchState:
    """Create a standardized initial research state."""
    return {
        "query": query,
        "session_id": session_id,
        "user_id": user_id,
        "complexity": None,
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


async def run_research(query: str, session_id: str, max_iterations: int = 2,
                       user_id: str | None = None):
    """Run the full research pipeline and return the final state."""
    initial_state = create_initial_state(query, session_id, max_iterations, user_id)
    logger.info(f"[Graph] Starting deep research for session {session_id}: {query}")
    final_state = await research_graph.ainvoke(initial_state)
    logger.info(f"[Graph] Deep research complete for session {session_id}")
    return final_state


# Streaming is opt-in per LLM call, not per node. Filtering by node leaked the
# triage classifier's JSON to the screen, because that node also runs an
# internal structured-output call. Only calls tagged USER_VISIBLE stream.
from agents.triage_agent import USER_VISIBLE_TAG

NODE_NAMES = {"triage", "planner", "search", "read", "corpus",
              "analyze", "factcheck", "gap_analysis", "report"}


async def stream_research(query: str, session_id: str, max_iterations: int = 2,
                          user_id: str | None = None):
    """Stream research progress, and stream the report itself as it is written.

    Node-completion events still arrive exactly as before, so the existing
    progress UI is unaffected. Interleaved with them are `token` events for the
    nodes in STREAMING_NODES, which is what turns a two-minute wait on a
    spinner into text appearing as the model produces it. Time-to-first-token
    matters far more to a reader than time-to-completion.
    """
    initial_state = create_initial_state(query, session_id, max_iterations, user_id)

    async for event in research_graph.astream_events(initial_state, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            if USER_VISIBLE_TAG not in (event.get("tags") or []):
                continue
            node = event.get("metadata", {}).get("langgraph_node")
            chunk = event["data"].get("chunk")
            text = getattr(chunk, "content", "") or ""
            if text:
                yield {"type": "token", "node": node, "text": text}
            continue

        if kind == "on_chain_end" and event.get("name") in NODE_NAMES:
            node_name = event["name"]
            state_update = event["data"].get("output")
            if not isinstance(state_update, dict):
                continue
            yield {
                "node": node_name,
                "step": state_update.get("current_step", node_name),
                "data": get_step_summary(node_name, state_update),
                "state": state_update,
            }


def _triage_message(state: dict) -> str:
    c = state.get("complexity")
    if c == "chat":
        return "Answered directly — no research needed"
    if c == "simple":
        return "Straightforward question — running a single focused pass"
    return "Complex question — running the full multi-pass pipeline"


def _corpus_message(state: dict) -> str:
    n = len([d for d in state.get("source_documents", []) if d.get("origin") == "corpus"])
    if n == 0:
        return "No matching documents in your knowledge base"
    return f"Found {n} relevant document{'' if n == 1 else 's'} in your knowledge base"


def get_step_summary(node: str, state: dict) -> dict:
    """Extract relevant data for each step to send to frontend."""
    summaries = {
        "triage": {
            "message": _triage_message(state),
            "complexity": state.get("complexity"),
        },
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
        "corpus": {
            "message": _corpus_message(state),
            "count": len([d for d in state.get("source_documents", [])
                          if d.get("origin") == "corpus"]),
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

