from tavily import TavilyClient
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from graph.state import ResearchState, SearchResult
from utils import invoke_with_retry, normalize_url, clean_llm_response
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================
# SEARCH AGENT (Multi-Query Decomposed Search)
# =============================================

def search_agent(state: ResearchState) -> ResearchState:
    queries_to_search = state.get("sub_queries") or [state["query"]]
    logger.info(f"[SearchAgent] Executing search across {len(queries_to_search)} queries (Iteration {state.get('iteration', 1)})")

    tavily = TavilyClient(api_key=settings.tavily_api_key)

    seen_urls = {normalize_url(r["url"]) for r in state.get("search_results", [])}
    all_results: list[SearchResult] = list(state.get("search_results", []))

    last_error = None
    # Triage decides how wide to cast the net: a definitional question does not
    # need the same breadth as a comparative analysis, and every extra source
    # is more text for the reader, analyst and fact-checker to chew through.
    per_query = 3 if state.get("complexity") == "simple" else 5
    try:
        for q in queries_to_search:
            try:
                response = tavily.search(
                    query=q,
                    search_depth="advanced",
                    max_results=per_query,
                    include_answer=False,
                    include_raw_content=False,
                )
                for r in response.get("results", []):
                    raw_url = r.get("url", "")
                    clean_url = normalize_url(raw_url)
                    if clean_url and clean_url not in seen_urls:
                        seen_urls.add(clean_url)
                        all_results.append({
                            "url": clean_url,
                            "title": r.get("title", "Untitled"),
                            "content": r.get("content", ""),
                            "score": float(r.get("score", 0.0)),
                        })
            except Exception as query_err:
                last_error = query_err
                logger.warning(f"[SearchAgent] Search error for query '{q}': {query_err}")

        # Fallback if too few results
        if len(all_results) < 3 and state.get("retry_count", 0) < 1:
            logger.warning("[SearchAgent] Too few results, rephrasing primary query...")
            rephrased = rephrase_query(state["query"])
            try:
                response2 = tavily.search(
                    query=rephrased,
                    search_depth="advanced",
                    max_results=6,
                )
                for r in response2.get("results", []):
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            "url": url,
                            "title": r.get("title", "Untitled"),
                            "content": r.get("content", ""),
                            "score": float(r.get("score", 0.0)),
                        })
            except Exception as e:
                last_error = e
                logger.warning(f"[SearchAgent] Rephrased search failed: {e}")

            return {
                **state,
                "search_results": all_results,
                "current_step": "search_done",
                "retry_count": state.get("retry_count", 0) + 1,
                "error": str(last_error) if not all_results and last_error else state.get("error"),
            }

        logger.info(f"[SearchAgent] Total unique search results collected: {len(all_results)}")
        return {
            **state,
            "search_results": all_results,
            "current_step": "search_done",
            "error": str(last_error) if not all_results and last_error else state.get("error"),
        }

    except Exception as e:
        logger.error(f"[SearchAgent] Fatal Search Error: {e}")
        return {
            **state,
            "search_results": all_results,
            "current_step": "search_done",
            "error": str(e),
        }


def rephrase_query(query: str) -> str:
    """Use Groq to rephrase query for better search engine results."""
    try:
        llm = ChatGroq(
            model=settings.groq_model_fast,
            api_key=settings.groq_api_key,
            temperature=0.3,
        )
        messages = [
            SystemMessage(content="Rephrase the user query to get better search engine results. Return only the rephrased query, nothing else."),
            HumanMessage(content=query),
        ]
        result = invoke_with_retry(llm, messages)
        return clean_llm_response(result.content)
    except Exception as e:
        logger.warning(f"[SearchAgent] Query rephrasing fallback: {e}")
        return query

