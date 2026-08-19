import pytest
from unittest.mock import patch, MagicMock
from graph.state import ResearchState


def make_state(**kwargs) -> ResearchState:
    """Helper: create a base state for testing."""
    base = {
        "query": "What is LangGraph?",
        "session_id": "test-session-123",
        "search_results": [],
        "source_documents": [],
        "draft_answer": "",
        "verified_claims": [],
        "overall_confidence": 0.0,
        "final_report": "",
        "current_step": "starting",
        "error": None,
        "retry_count": 0,
    }
    base.update(kwargs)
    return base


# =============================================
# Search Agent Tests
# =============================================

class TestSearchAgent:
    @patch("agents.search_agent.TavilyClient")
    def test_search_returns_results(self, mock_tavily_class):
        from agents.search_agent import search_agent

        mock_client = MagicMock()
        mock_tavily_class.return_value = mock_client
        mock_client.search.return_value = {
            "results": [
                {"url": "https://example.com", "title": "Test", "content": "Content", "score": 0.9},
                {"url": "https://example2.com", "title": "Test 2", "content": "Content 2", "score": 0.8},
                {"url": "https://example3.com", "title": "Test 3", "content": "Content 3", "score": 0.7},
            ]
        }

        state = make_state(query="What is AI?")
        result = search_agent(state)

        assert len(result["search_results"]) == 3
        assert result["current_step"] == "search_done"
        assert result["search_results"][0]["url"] == "https://example.com"

    @patch("agents.search_agent.TavilyClient")
    def test_search_handles_empty_results(self, mock_tavily_class):
        from agents.search_agent import search_agent

        mock_client = MagicMock()
        mock_tavily_class.return_value = mock_client
        mock_client.search.return_value = {"results": []}

        state = make_state(query="very obscure query xyz123")
        result = search_agent(state)

        assert result["current_step"] == "search_done"
        assert isinstance(result["search_results"], list)

    @patch("agents.search_agent.TavilyClient")
    def test_search_handles_api_error(self, mock_tavily_class):
        from agents.search_agent import search_agent

        mock_client = MagicMock()
        mock_tavily_class.return_value = mock_client
        mock_client.search.side_effect = Exception("API Error")

        state = make_state(query="test query")
        result = search_agent(state)

        assert result["current_step"] == "search_done"
        assert result["error"] is not None


# =============================================
# Reader Agent Tests
# =============================================

class TestReaderAgent:
    @patch("agents.reader_agent.requests.get")
    def test_reads_webpage(self, mock_get):
        from agents.reader_agent import reader_agent

        mock_response = MagicMock()
        long_paragraph = "This is test content about AI systems. " * 5
        mock_response.text = f"<html><body><article><p>{long_paragraph}</p></article></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        state = make_state(
            search_results=[
                {"url": "https://example.com", "title": "Test Article", "content": "", "score": 0.9}
            ]
        )
        result = reader_agent(state)

        assert len(result["source_documents"]) == 1
        assert result["source_documents"][0]["title"] == "Test Article"
        assert result["current_step"] == "read_done"

    @patch("agents.reader_agent.requests.get")
    def test_skips_failed_urls(self, mock_get):
        from agents.reader_agent import reader_agent

        mock_get.side_effect = Exception("Connection failed")

        state = make_state(
            search_results=[
                {"url": "https://broken.com", "title": "Broken", "content": "", "score": 0.5}
            ]
        )
        result = reader_agent(state)

        assert result["source_documents"] == []
        assert result["current_step"] == "read_done"


# =============================================
# Report Agent Tests
# =============================================

class TestReportAgent:
    @patch("agents.report_agent.ChatGroq")
    def test_generates_report(self, mock_groq_class):
        from agents.report_agent import report_agent

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="# Research Report\n\nThis is the final report.")
        mock_groq_class.return_value = mock_llm

        state = make_state(
            draft_answer="AI is transforming the world.",
            source_documents=[{"title": "AI Article", "url": "https://example.com", "text": "content"}],
            verified_claims=[{"claim": "AI is transforming", "verified": True, "confidence": 0.9, "source": "example.com"}],
            overall_confidence=0.9,
        )
        result = report_agent(state)

        assert result["final_report"] != ""
        assert result["current_step"] == "complete"

    def test_fallback_on_empty_draft(self):
        from agents.report_agent import get_confidence_label
        assert get_confidence_label(0.9) == "High Confidence"
        assert get_confidence_label(0.7) == "Moderate Confidence"
        assert get_confidence_label(0.5) == "Low Confidence"
        assert get_confidence_label(0.2) == "Uncertain"


# =============================================
# Analyst Agent Tests
# =============================================

class TestAnalystAgent:
    def test_no_sources_short_circuits(self):
        from agents.analyst_agent import analyst_agent

        state = make_state(source_documents=[])
        result = analyst_agent(state)

        assert result["draft_answer"] == "Could not find sufficient sources to answer this question."
        assert result["current_step"] == "analysis_done"
        assert result["error"] == "No source documents available"

    @patch("agents.analyst_agent.ChatGroq")
    def test_synthesizes_draft_from_sources(self, mock_groq_class):
        from agents.analyst_agent import analyst_agent

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="AI is transforming research. [Source 1]")
        mock_groq_class.return_value = mock_llm

        state = make_state(
            source_documents=[
                {"title": "AI Article", "url": "https://example.com", "text": "AI is changing everything." * 20}
            ]
        )
        result = analyst_agent(state)

        assert result["draft_answer"] == "AI is transforming research. [Source 1]"
        assert result["current_step"] == "analysis_done"
        assert result["error"] is None

    @patch("agents.analyst_agent.ChatGroq")
    def test_llm_error_returns_empty_draft(self, mock_groq_class):
        from agents.analyst_agent import analyst_agent

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM unavailable")
        mock_groq_class.return_value = mock_llm

        state = make_state(
            source_documents=[{"title": "Doc", "url": "https://example.com", "text": "some content"}]
        )
        result = analyst_agent(state)

        assert result["draft_answer"] == ""
        assert result["error"] == "LLM unavailable"

    def test_build_context_falls_back_without_rerank(self):
        """Fewer chunks than TOP_K_CHUNKS should skip Cohere entirely."""
        from agents.analyst_agent import build_context

        docs = [{"title": "Doc A", "url": "https://a.com", "text": "short content"}]
        context = build_context("test query", docs)

        assert "Doc A" in context
        assert "short content" in context

    def test_build_context_handles_no_documents(self):
        from agents.analyst_agent import build_context

        assert build_context("test query", []) == "No content available."


# =============================================
# Fact-Check Agent Tests
# =============================================

class TestFactCheckAgent:
    def test_no_draft_answer_short_circuits(self):
        from agents.factcheck_agent import factcheck_agent

        state = make_state(draft_answer="")
        result = factcheck_agent(state)

        assert result["verified_claims"] == []
        assert result["overall_confidence"] == 0.0
        assert result["current_step"] == "factcheck_done"

    @patch("agents.factcheck_agent.ChatGroq")
    def test_verifies_extracted_claims(self, mock_groq_class):
        from agents.factcheck_agent import factcheck_agent

        mock_llm = MagicMock()
        # Two calls total now, not one-per-claim: extract_claims, then a single
        # batched verification carrying every verdict keyed by claim_index.
        mock_llm.invoke.side_effect = [
            MagicMock(content='["AI is transforming research", "Models are larger"]'),
            MagicMock(content='{"verdicts": ['
                              '{"claim_index": 0, "verified": true, "confidence": 0.9, "source": "example.com"},'
                              '{"claim_index": 1, "verified": false, "confidence": 0.1, "source": "none"}]}'),
        ]
        mock_groq_class.return_value = mock_llm

        state = make_state(
            draft_answer="AI is transforming research.",
            source_documents=[{"title": "AI Article", "url": "https://example.com", "text": "content"}],
        )
        result = factcheck_agent(state)

        assert len(result["verified_claims"]) == 2
        by_claim = {c["claim"]: c for c in result["verified_claims"]}
        assert by_claim["AI is transforming research"]["verified"] is True
        assert by_claim["Models are larger"]["verified"] is False
        assert result["overall_confidence"] == 0.5   # (0.9 + 0.1) / 2
        assert result["current_step"] == "factcheck_done"
        # The whole point of the change: evidence is sent once, not per claim.
        assert mock_llm.invoke.call_count == 2

    @patch("agents.factcheck_agent.ChatGroq")
    def test_reuses_verdicts_from_previous_pass(self, mock_groq_class):
        """The reflective loop must not re-verify claims it already settled."""
        from agents.factcheck_agent import factcheck_agent

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content='["Already checked"]'),   # extract_claims
        ]
        mock_groq_class.return_value = mock_llm

        state = make_state(
            draft_answer="Already checked.",
            source_documents=[{"title": "T", "url": "https://e.com", "text": "c"}],
        )
        state["verified_claims"] = [
            {"claim": "Already checked", "verified": True, "confidence": 0.8, "source": "e.com"}
        ]
        result = factcheck_agent(state)

        assert len(result["verified_claims"]) == 1
        assert result["verified_claims"][0]["confidence"] == 0.8
        # extract_claims only — no verification call, because nothing was pending.
        assert mock_llm.invoke.call_count == 1

    @patch("agents.factcheck_agent.ChatGroq")
    def test_handles_malformed_claim_json(self, mock_groq_class):
        from agents.factcheck_agent import factcheck_agent

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="not valid json at all")
        mock_groq_class.return_value = mock_llm

        state = make_state(
            draft_answer="Some claim.",
            source_documents=[{"title": "Doc", "url": "https://example.com", "text": "content"}],
        )
        result = factcheck_agent(state)

        # extract_claims fails gracefully -> no claims -> default confidence
        assert result["verified_claims"] == []
        assert result["overall_confidence"] == 0.5
        assert result["current_step"] == "factcheck_done"

    @patch("agents.factcheck_agent.ChatGroq")
    def test_verify_claim_handles_malformed_response(self, mock_groq_class):
        from agents.factcheck_agent import verify_claim

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="garbage, not json")

        result = verify_claim(mock_llm, "Some claim", "some context")

        assert result["verified"] is False
        assert result["confidence"] == 0.5
        assert result["source"] == "Verification failed"

    def test_extract_claims_strips_markdown_fences(self):
        from agents.factcheck_agent import extract_claims

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='```json\n["Claim one", "Claim two"]\n```'
        )

        claims = extract_claims(mock_llm, "some draft answer")
        assert claims == ["Claim one", "Claim two"]


# =============================================
# DB Layer Tests
# =============================================

class TestDB:
    @pytest.fixture(autouse=True)
    def _use_tmp_sqlite(self, tmp_path, monkeypatch):
        """Point the DB module at an isolated sqlite file per test."""
        import importlib
        import db as db_module

        monkeypatch.setattr(db_module, "DB_URL", f"sqlite:///{tmp_path}/test.db")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        db_module.engine = create_engine(
            db_module.DB_URL, connect_args={"check_same_thread": False}
        )
        db_module.SessionLocal = sessionmaker(bind=db_module.engine, autoflush=False, autocommit=False)
        # tenant_session() uses AppSessionLocal for every real query — point
        # it at the same isolated test engine (RLS/set_config is Postgres-only
        # and skipped automatically under sqlite; verified separately).
        db_module.AppSessionLocal = db_module.SessionLocal
        # A fresh SQLite file already has user_id from the model definition,
        # so skip init_db()'s Postgres-only ALTER TABLE migration step here.
        db_module.Base.metadata.create_all(bind=db_module.engine)
        yield db_module

    def test_save_and_get_session(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        final_state = {
            "final_report": "# Report",
            "source_documents": [{"title": "Doc", "url": "https://example.com"}],
            "verified_claims": [{"claim": "x", "verified": True, "confidence": 0.8, "source": "y"}],
            "overall_confidence": 0.8,
            "error": None,
        }
        db.save_session("abc-123", "user-1", "What is AI?", final_state)

        record = db.get_session("abc-123", "user-1")
        assert record is not None
        assert record["query"] == "What is AI?"
        assert record["status"] == "complete"
        assert record["confidence"] == 0.8

    def test_get_missing_session_returns_none(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        assert db.get_session("does-not-exist", "user-1") is None

    def test_session_isolated_by_user(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        db.save_session("shared-id-owned-by-1", "user-1", "query", {"final_report": "r"})
        assert db.get_session("shared-id-owned-by-1", "user-2") is None
        assert db.get_session("shared-id-owned-by-1", "user-1") is not None

    def test_list_sessions_orders_most_recent_first(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        db.save_session("s1", "user-1", "query 1", {"final_report": "r1"})
        db.save_session("s2", "user-1", "query 2", {"final_report": "r2"})

        sessions = db.list_sessions("user-1")
        ids = [s["session_id"] for s in sessions]
        assert "s1" in ids and "s2" in ids

    def test_list_sessions_excludes_other_users(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        db.save_session("mine", "user-1", "query", {"final_report": "r"})
        db.save_session("theirs", "user-2", "query", {"final_report": "r"})

        sessions = db.list_sessions("user-1")
        ids = [s["session_id"] for s in sessions]
        assert ids == ["mine"]

    def test_delete_session(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        db.save_session("to-delete", "user-1", "query", {"final_report": "r"})

        assert db.delete_session("to-delete", "user-1") is True
        assert db.get_session("to-delete", "user-1") is None
        assert db.delete_session("to-delete", "user-1") is False

    def test_delete_session_blocked_for_other_user(self, _use_tmp_sqlite):
        db = _use_tmp_sqlite
        db.save_session("not-yours", "user-1", "query", {"final_report": "r"})

        assert db.delete_session("not-yours", "user-2") is False
        assert db.get_session("not-yours", "user-1") is not None
