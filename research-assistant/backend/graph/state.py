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


class VerifiedClaim(TypedDict):
    claim: str
    verified: bool
    confidence: float
    source: str


# =============================================
# Main State — flows through the autonomous graph
# =============================================
class ResearchState(TypedDict):
    # Input
    query: str
    session_id: str

    # Planner Agent output
    sub_queries: List[str]
    research_plan: List[str]

    # Search Agent output
    search_results: List[SearchResult]

    # Reader Agent output
    source_documents: List[SourceDocument]

    # Analyst Agent output
    draft_answer: str

    # Fact-check Agent output
    verified_claims: List[VerifiedClaim]
    overall_confidence: float

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

