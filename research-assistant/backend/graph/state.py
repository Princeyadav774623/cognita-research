from typing import TypedDict, List, Optional, Dict, Any


class SearchResult(TypedDict):
    url: str
    title: str
    content: str
    score: float


class SourceDocument(TypedDict):
    url: str
    title: str
    text: str
    # "web" for scraped pages, "corpus" for the user's own uploaded documents.
    # Readers that predate this field simply omit it; TypedDict is not
    # enforced at runtime, and every consumer uses .get("origin").
    origin: Optional[str]
    # True when direct extraction (PDF/HTML) failed or returned too little,
    # and the text is actually just the search engine's snippet instead of the
    # full page. A run can silently substitute two sentences for a paper and
    # report a normal-looking source count — this makes that visible rather
    # than invisible. Missing/None means "not tracked" (older callers), not
    # "confirmed full text".
    via_fallback: Optional[bool]


class SourceImage(TypedDict):
    """A picture published by one of the sources, not a generated one.

    Tavily returns these alongside results. Showing a real figure from a paper
    or a chart from a report is evidence; an invented illustration would be the
    opposite of what this product is for.
    """
    url: str
    description: str
    origin_url: str


class VerifiedClaim(TypedDict):
    claim: str
    verified: bool
    confidence: float
    source: str
    # True when the claim held up against a source the draft was NOT written
    # from. Verification against only the analyst's own sources is circular —
    # a faithful summary always agrees with the text it summarised — so this
    # is what separates "consistent with the draft" from "corroborated".
    # Missing/None means the run predates the distinction, not "not corroborated".
    independently_corroborated: Optional[bool]


# =============================================
# Main State — flows through the autonomous graph
# =============================================
class ResearchState(TypedDict):
    # Input
    query: str
    session_id: str
    # Owner of this run. Needed so the corpus agent can search *this* user's
    # uploaded documents — retrieval is tenant-scoped, and a graph with no
    # user_id simply skips the corpus rather than leaking across tenants.
    user_id: Optional[str]

    # Triage Agent output — "chat" | "simple" | "deep". Drives how many
    # search/reflection passes the run is allowed.
    complexity: Optional[str]

    # Planner Agent output
    sub_queries: List[str]
    research_plan: List[str]

    # Search Agent output
    search_results: List[SearchResult]
    images: List[SourceImage]

    # Reader Agent output
    source_documents: List[SourceDocument]

    # Analyst Agent output
    draft_answer: str

    # Fact-check Agent output
    verified_claims: List[VerifiedClaim]
    overall_confidence: float
    # Why the score is what it is, and what would raise it. A number the reader
    # cannot interrogate is decoration.
    confidence_factors: List[Dict[str, Any]]
    confidence_to_improve: List[str]

    # Reflection / Gap Analysis
    is_sufficient: bool
    missing_information: List[str]
    iteration: int
    max_iterations: int

    # Report Agent output
    final_report: str

    # Control & Observability
    current_step: str
    error: Optional[str]
    retry_count: int
    cost_tracking: Dict[str, Any]

