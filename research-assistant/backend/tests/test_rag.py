import pytest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock


def _fake_tenant_session(mock_db):
    """Build a stand-in for db.tenant_session()/get_tenant_session() that
    always yields the given mock, regardless of user_id."""
    @contextmanager
    def _cm(user_id):
        yield mock_db
    return _cm


# =============================================
# Chunking
# =============================================

class TestChunkText:
    def test_empty_text_returns_no_chunks(self):
        from rag.ingest import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_returns_single_chunk(self):
        from rag.ingest import chunk_text
        chunks = chunk_text("short text", chunk_size=1000, overlap=150)
        assert chunks == ["short text"]

    def test_long_text_splits_with_overlap(self):
        from rag.ingest import chunk_text
        text = "a" * 2500
        chunks = chunk_text(text, chunk_size=1000, overlap=150)
        assert len(chunks) == 3
        # consecutive chunks should share overlapping content
        assert chunks[0][-150:] == chunks[1][:150]

    def test_chunks_never_exceed_chunk_size(self):
        from rag.ingest import chunk_text
        text = "word " * 1000
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert all(len(c) <= 500 for c in chunks)


# =============================================
# Text extraction
# =============================================

class TestExtractText:
    def test_rejects_unsupported_extension(self):
        from rag.ingest import extract_text, IngestError
        with pytest.raises(IngestError, match="Unsupported file type"):
            extract_text("malware.exe", b"data")

    def test_rejects_oversized_file(self):
        from rag.ingest import extract_text, IngestError, MAX_FILE_SIZE_BYTES
        oversized = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        with pytest.raises(IngestError, match="too large"):
            extract_text("big.txt", oversized)

    def test_extracts_plain_text(self):
        from rag.ingest import extract_text
        text = extract_text("notes.txt", b"Hello world, this is a test file.")
        assert "Hello world" in text

    def test_rejects_empty_text_file(self):
        from rag.ingest import extract_text, IngestError
        with pytest.raises(IngestError, match="empty"):
            extract_text("empty.txt", b"   ")

    def test_decodes_non_utf8_text_gracefully(self):
        from rag.ingest import extract_text
        content = "café".encode("latin-1")
        text = extract_text("notes.txt", content)
        assert text.strip()

    def test_extracts_markdown_as_text(self):
        from rag.ingest import extract_text
        text = extract_text("readme.md", b"# Title\n\nSome content here.")
        assert "Title" in text

    def test_rejects_spoofed_file_magic_bytes(self):
        from rag.ingest import extract_text, IngestError
        # Claiming to be PDF but actually plain garbage
        with pytest.raises(IngestError, match="PDF"):
            extract_text("malicious.pdf", b"this is not a pdf file")

    def test_image_ocr_missing_dependency_raises_ingest_error(self):
        from rag.ingest import extract_text, IngestError
        png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"fake-image-bytes"
        with patch.dict("sys.modules", {"pytesseract": None, "PIL": None}):
            with pytest.raises(IngestError):
                extract_text("scan.png", png_header)


# =============================================
# Retrieval (mocked embeddings + DB)
# =============================================

class TestRetrieval:
    @patch("rag.retrieval.embed_texts")
    @patch("rag.retrieval.get_tenant_session")
    def test_ingest_document_marks_ready_on_success(self, mock_get_session, mock_embed):
        from rag.retrieval import ingest_document

        mock_db = MagicMock()
        mock_get_session.side_effect = _fake_tenant_session(mock_db)
        mock_embed.return_value = [[0.1] * 384]

        result = ingest_document("user-1", "notes.txt", b"Some real content for the document.")

        assert result["status"] == "ready"
        assert result["chunk_count"] == 1
        mock_db.commit.assert_called()

    @patch("rag.retrieval.embed_texts")
    @patch("rag.retrieval.get_tenant_session")
    def test_ingest_document_marks_error_on_unsupported_type(self, mock_get_session, mock_embed):
        from rag.retrieval import ingest_document

        mock_db = MagicMock()
        mock_get_session.side_effect = _fake_tenant_session(mock_db)

        result = ingest_document("user-1", "virus.exe", b"whatever")

        assert result["status"] == "error"
        assert "Unsupported file type" in result["error"]
        mock_embed.assert_not_called()

    @patch("rag.retrieval.embed_query")
    @patch("rag.retrieval.get_tenant_session")
    def test_retrieve_relevant_chunks_returns_empty_when_no_documents(self, mock_get_session, mock_embed_query):
        from rag.retrieval import retrieve_relevant_chunks

        mock_db = MagicMock()
        mock_get_session.side_effect = _fake_tenant_session(mock_db)
        mock_embed_query.return_value = [0.1] * 384

        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        results = retrieve_relevant_chunks("user-1", "any question")
        assert results == []


# =============================================
# Chat agent
# =============================================

class TestChatAgent:
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    @patch("rag.chat_agent.get_tenant_session")
    def test_chat_with_no_documents_short_circuits(self, mock_get_session, mock_retrieve):
        from rag.chat_agent import chat

        mock_db = MagicMock()
        mock_get_session.side_effect = _fake_tenant_session(mock_db)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        def fake_add(obj):
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = "conv-1"

        mock_db.add.side_effect = fake_add
        mock_db.refresh.side_effect = lambda obj: None
        mock_retrieve.return_value = []

        result = chat("user-1", None, "What does the policy say?")

        assert "upload one first" in result["answer"]
        assert result["sources"] == []


# =============================================
# Upload endpoint guards
# =============================================

class TestUploadEndpoint:
    """The upload route must reject bad input before it reaches ingestion.

    Size in particular is enforced by reading the body in bounded chunks and
    bailing mid-stream, so an oversized upload is never buffered in full.
    """

    @staticmethod
    def _client():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.rag_routes import router
        from auth import get_current_user_id
        from rate_limit import limiter

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(router)
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        return TestClient(app)

    def test_rejects_unsupported_extension_before_ingesting(self):
        with patch("api.rag_routes.create_document_record") as mock_ingest:
            res = self._client().post(
                "/api/rag/upload", files={"file": ("virus.exe", b"MZ\x00", "application/octet-stream")}
            )
            assert res.status_code == 400
            assert "Unsupported file type" in res.json()["detail"]
            mock_ingest.assert_not_called()

    def test_rejects_oversized_file_without_ingesting(self):
        from rag.ingest import MAX_FILE_SIZE_BYTES

        oversized = b"x" * (MAX_FILE_SIZE_BYTES + 1024)
        with patch("api.rag_routes.create_document_record") as mock_ingest:
            res = self._client().post(
                "/api/rag/upload", files={"file": ("big.txt", oversized, "text/plain")}
            )
            assert res.status_code == 400
            assert "too large" in res.json()["detail"].lower()
            mock_ingest.assert_not_called()

    def test_rejects_empty_file(self):
        with patch("api.rag_routes.create_document_record") as mock_ingest:
            res = self._client().post(
                "/api/rag/upload", files={"file": ("empty.txt", b"", "text/plain")}
            )
            assert res.status_code == 400
            mock_ingest.assert_not_called()

    def test_accepts_file_at_the_size_limit(self):
        from rag.ingest import MAX_FILE_SIZE_BYTES

        at_limit = b"x" * MAX_FILE_SIZE_BYTES
        with patch("api.rag_routes.create_document_record") as mock_create, \
             patch("api.rag_routes.process_document") as mock_process:
            mock_create.return_value = {"status": "processing", "id": "doc-1", "filename": "ok.txt"}
            res = self._client().post(
                "/api/rag/upload", files={"file": ("ok.txt", at_limit, "text/plain")}
            )
            assert res.status_code == 200
            # The full body reaches the background worker intact, not truncated
            # by the chunked read that enforces the size limit.
            assert len(mock_process.call_args[0][3]) == MAX_FILE_SIZE_BYTES

    def test_returns_immediately_and_indexes_in_the_background(self):
        """Parsing no longer happens inside the request: a long PDF used to hold
        the connection open and could outlive a proxy timeout. The response now
        carries a processing record and the client polls for the outcome."""
        with patch("api.rag_routes.create_document_record") as mock_create, \
             patch("api.rag_routes.process_document") as mock_process:
            mock_create.return_value = {"status": "processing", "id": "doc-9", "filename": "scan.pdf"}
            res = self._client().post(
                "/api/rag/upload", files={"file": ("scan.pdf", b"%PDF-1.4 junk", "application/pdf")}
            )

        assert res.status_code == 200
        assert res.json()["status"] == "processing"
        # Extraction ran after the response was sent, not before it.
        mock_process.assert_called_once()
        assert mock_process.call_args[0][1] == "doc-9"

    def test_extraction_failure_lands_on_the_record_not_the_response(self):
        """With ingestion moved off the request there is no caller left to raise
        to; the document's status is how the user finds out."""
        from rag.retrieval import process_document

        doc = MagicMock(status="processing", error=None)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = doc

        with patch("rag.retrieval.get_tenant_session", side_effect=_fake_tenant_session(mock_db)):
            process_document("user-1", "doc-9", "scan.pdf", b"%PDF-1.4 junk")

        assert doc.status == "error"
        assert doc.error


# =============================================
# Agentic retrieval loop
# =============================================

class TestAgenticRetrieval:
    """The loop must be able to reconsider: resolve follow-up phrasing, judge
    whether what it found actually answers the question, and rewrite its own
    query once before giving up."""

    @staticmethod
    def _chunk(sim, content="text", idx=0):
        return {"content": content, "filename": "d.txt", "chunk_index": idx, "similarity": sim}

    @patch("rag.chat_agent._fast_llm")
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    def test_strong_match_short_circuits_without_grading(self, mock_retrieve, mock_llm):
        from rag.chat_agent import agentic_retrieve, STRONG_MATCH_SIMILARITY

        mock_retrieve.return_value = [self._chunk(STRONG_MATCH_SIMILARITY + 0.05)]
        chunks, _, trace = agentic_retrieve("u", "q", [], top_k=4, similarity_threshold=0.55)

        assert len(chunks) == 1
        assert trace[-1]["verdict"].startswith("strong match")
        # A confident cosine hit must not cost an LLM call.
        mock_llm.return_value.with_structured_output.assert_not_called()
        assert mock_retrieve.call_count == 1

    @patch("rag.chat_agent._grade_retrieval")
    @patch("rag.chat_agent._one_line")
    @patch("rag.chat_agent._fast_llm")
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    def test_rewrites_and_retries_when_first_attempt_is_insufficient(
        self, mock_retrieve, _mock_llm, mock_one_line, mock_grade
    ):
        from rag.chat_agent import agentic_retrieve

        mock_retrieve.side_effect = [[self._chunk(0.60)], [self._chunk(0.62)]]
        mock_grade.side_effect = [(False, "missing the specifics"), (True, "")]
        mock_one_line.return_value = "a better query"

        chunks, _, trace = agentic_retrieve("u", "q", [], top_k=4, similarity_threshold=0.55)

        assert mock_retrieve.call_count == 2
        assert any(t["step"] == "rewrite" and t["query"] == "a better query" for t in trace)
        assert len(chunks) == 1

    @patch("rag.chat_agent._grade_retrieval")
    @patch("rag.chat_agent._one_line")
    @patch("rag.chat_agent._fast_llm")
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    def test_reports_best_effort_rather_than_giving_up_when_chunks_exist(
        self, mock_retrieve, _mock_llm, mock_one_line, mock_grade
    ):
        """Telemetry must not claim it gave up while an answer is produced from
        the chunks it did find — the trace has to match what actually happened."""
        from rag.chat_agent import agentic_retrieve

        mock_retrieve.side_effect = [[self._chunk(0.60)], [self._chunk(0.61)]]
        mock_grade.return_value = (False, "still thin")
        mock_one_line.return_value = "another phrasing"

        chunks, _, trace = agentic_retrieve("u", "q", [], top_k=4, similarity_threshold=0.55)

        assert chunks, "best-effort chunks should still be returned"
        assert trace[-1]["step"] == "best_effort"
        assert not any(t["step"] == "give_up" for t in trace)

    @patch("rag.chat_agent._grade_retrieval")
    @patch("rag.chat_agent._one_line")
    @patch("rag.chat_agent._fast_llm")
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    def test_gives_up_only_when_nothing_was_found(
        self, mock_retrieve, _mock_llm, mock_one_line, mock_grade
    ):
        from rag.chat_agent import agentic_retrieve

        mock_retrieve.return_value = []
        mock_grade.return_value = (False, "nothing retrieved")
        mock_one_line.return_value = "reworded"

        chunks, _, trace = agentic_retrieve("u", "q", [], top_k=4, similarity_threshold=0.55)

        assert chunks == []
        assert trace[-1]["step"] == "give_up"

    @patch("rag.chat_agent._grade_retrieval")
    @patch("rag.chat_agent._one_line")
    @patch("rag.chat_agent._fast_llm")
    @patch("rag.chat_agent.retrieve_relevant_chunks")
    def test_contextualises_follow_up_against_history(
        self, mock_retrieve, _mock_llm, mock_one_line, mock_grade
    ):
        """A pronoun-laden follow-up has to become a standalone query before it
        is embedded, or the vector search is looking for 'it'."""
        from rag.chat_agent import agentic_retrieve

        mock_retrieve.return_value = [self._chunk(0.62)]
        mock_grade.return_value = (True, "")
        mock_one_line.return_value = "How long does a rollback take?"

        history = [MagicMock(role="user", content="What days do releases ship?"),
                   MagicMock(role="assistant", content="Tuesdays and Thursdays.")]
        _, _, trace = agentic_retrieve("u", "how long to undo one?", history, 4, 0.55)

        assert trace[0]["step"] == "contextualize"
        assert trace[0]["query"] == "How long does a rollback take?"
        # the rewritten query, not the pronoun version, is what gets embedded
        assert mock_retrieve.call_args[0][1] == "How long does a rollback take?"


# =============================================
# Corpus agent — the user's documents as a research source
# =============================================

class TestCorpusAgent:
    """The research graph must be able to cite the user's own uploads, and must
    never reach into the corpus without a tenant to scope the search to."""

    @staticmethod
    def _state(**kw):
        base = {"query": "q", "session_id": "s", "user_id": "user-1",
                "sub_queries": ["q"], "source_documents": []}
        base.update(kw)
        return base

    @patch("agents.corpus_agent.retrieve_relevant_chunks")
    def test_skips_entirely_without_a_user_id(self, mock_retrieve):
        from agents.corpus_agent import corpus_agent
        result = corpus_agent(self._state(user_id=None))
        assert result["source_documents"] == []
        # Never query the corpus with no tenant — that is the isolation boundary.
        mock_retrieve.assert_not_called()

    @patch("agents.corpus_agent.retrieve_relevant_chunks")
    def test_adds_matching_documents_as_sources(self, mock_retrieve):
        from agents.corpus_agent import corpus_agent
        mock_retrieve.return_value = [
            {"content": "second passage", "filename": "notes.pdf", "chunk_index": 4, "similarity": 0.81},
            {"content": "first passage", "filename": "notes.pdf", "chunk_index": 1, "similarity": 0.72},
        ]
        result = corpus_agent(self._state())

        docs = result["source_documents"]
        assert len(docs) == 1, "passages from one file collapse into one document"
        assert docs[0]["origin"] == "corpus"
        assert docs[0]["url"] == "upload://notes.pdf"
        # Passages are stitched back into reading order, not retrieval order.
        assert docs[0]["text"].index("first passage") < docs[0]["text"].index("second passage")

    @patch("agents.corpus_agent.retrieve_relevant_chunks")
    def test_drops_weak_matches(self, mock_retrieve):
        from agents.corpus_agent import corpus_agent
        from agents.corpus_agent import MIN_SIMILARITY
        mock_retrieve.return_value = [
            {"content": "barely related", "filename": "x.txt", "chunk_index": 0,
             "similarity": MIN_SIMILARITY - 0.05},
        ]
        result = corpus_agent(self._state())
        assert result["source_documents"] == []

    @patch("agents.corpus_agent.retrieve_relevant_chunks")
    def test_preserves_web_documents_already_gathered(self, mock_retrieve):
        from agents.corpus_agent import corpus_agent
        mock_retrieve.return_value = [
            {"content": "mine", "filename": "d.txt", "chunk_index": 0, "similarity": 0.9},
        ]
        web = {"url": "https://a.com", "title": "A", "text": "web text", "origin": "web"}
        result = corpus_agent(self._state(source_documents=[web]))

        origins = [d.get("origin") for d in result["source_documents"]]
        assert origins == ["web", "corpus"], "corpus must append, not replace"

    @patch("agents.corpus_agent.retrieve_relevant_chunks")
    def test_survives_a_retrieval_failure(self, mock_retrieve):
        from agents.corpus_agent import corpus_agent
        mock_retrieve.side_effect = RuntimeError("pgvector unavailable")
        result = corpus_agent(self._state())
        # A corpus outage must not take the whole research run down with it.
        assert result["current_step"] == "corpus_done"
        assert result["source_documents"] == []


class TestAnalystCorpusPriority:
    """A document the user uploaded must reach the analyst even when web search
    returned far more material than fits in the context window."""

    @staticmethod
    def _doc(title, origin, text):
        return {"title": title, "url": f"{origin}://{title}", "text": text, "origin": origin}

    def test_corpus_chunks_survive_a_flood_of_web_documents(self):
        from agents.analyst_agent import build_context, TOP_K_CHUNKS

        # Far more web material than can fit, with the corpus doc appended last
        # exactly as the graph appends it.
        web = [self._doc(f"page{i}", "web", "web filler " * 300) for i in range(40)]
        corpus = [self._doc("mine.txt", "corpus", "SENTINEL the private benchmark figure is 3.1 percent")]

        context = build_context("what was the benchmark figure?", web + corpus)

        assert "SENTINEL" in context, "the user's own document was crowded out of the context"

    def test_corpus_leads_the_context(self):
        from agents.analyst_agent import build_context

        web = [self._doc(f"page{i}", "web", "web filler " * 300) for i in range(20)]
        corpus = [self._doc("mine.txt", "corpus", "SENTINEL private content")]

        context = build_context("q", web + corpus)
        assert context.index("SENTINEL") < context.index("page0"), \
            "corpus material should be read before web material"

    def test_web_only_research_is_unaffected(self):
        from agents.analyst_agent import build_context, TOP_K_CHUNKS

        web = [self._doc(f"page{i}", "web", f"content{i} " * 200) for i in range(30)]
        context = build_context("q", web)
        assert context.count("--- Source") == TOP_K_CHUNKS


class TestEvalGrader:
    """The eval harness itself needs to be correct, or it manufactures failures
    and gets ignored."""

    def test_matches_through_typographic_whitespace(self):
        from evals.run import normalize
        # What the model actually emits: U+202F narrow no-break space.
        assert "8 minutes" in normalize("The window is **8 minutes** long.")

    def test_matches_through_non_breaking_hyphen(self):
        from evals.run import normalize
        assert "ops-handbook" in normalize("(source: ops‑handbook.txt)")

    def test_still_rejects_a_genuinely_wrong_answer(self):
        from evals.run import normalize
        assert "8 minutes" not in normalize("The window is 12 minutes long.")


class TestCredentialRedaction:
    """DATABASE_URL carries a live Postgres password. It must never reach a log
    line, where it outlives any rotation."""

    def test_password_is_stripped_from_logged_url(self):
        from db import _safe_url
        out = _safe_url("postgresql://postgres.abc:s3cr3t+p%40ss@db.example.com:6543/postgres")
        assert "s3cr3t" not in out
        assert "***" in out
        # host, port, user and database still identify the connection
        assert "db.example.com:6543" in out and "postgres.abc" in out

    def test_url_without_a_password_is_untouched(self):
        from db import _safe_url
        url = "postgresql://localhost:5432/postgres"
        assert _safe_url(url) == url

    def test_malformed_url_does_not_raise(self):
        from db import _safe_url
        assert _safe_url("not a url") == "not a url"


class TestStaleProcessingReaper:
    """Ingestion runs in the web process, so a restart between "row created"
    and "embedding finished" leaves a document processing forever. The UI polls
    while anything is processing, so that row spins indefinitely."""

    def _doc(self, minutes_old, status="processing"):
        from datetime import datetime, timedelta, timezone
        doc = MagicMock()
        doc.status = status
        doc.error = None
        doc.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
        return doc

    def test_marks_an_abandoned_document_as_failed(self):
        from rag.retrieval import reap_stale_processing

        stale = self._doc(30)
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [stale]

        with patch("rag.retrieval.get_tenant_session", side_effect=_fake_tenant_session(mock_db)):
            reaped = reap_stale_processing("user-1")

        assert reaped == 1
        assert stale.status == "error"
        # The message has to tell the user what to do, not just that it broke.
        assert "again" in stale.error.lower()
        mock_db.commit.assert_called_once()

    def test_leaves_a_recent_upload_alone(self):
        """A large PDF genuinely takes a while; reaping it mid-flight would be
        worse than the bug."""
        from rag.retrieval import reap_stale_processing

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with patch("rag.retrieval.get_tenant_session", side_effect=_fake_tenant_session(mock_db)):
            assert reap_stale_processing("user-1") == 0
        mock_db.commit.assert_not_called()

    def test_listing_documents_reaps_first(self):
        """No scheduler: a stuck row is noticed the next time anyone looks."""
        from rag.retrieval import list_documents

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch("rag.retrieval.reap_stale_processing") as reaper, \
             patch("rag.retrieval.get_tenant_session", side_effect=_fake_tenant_session(mock_db)):
            list_documents("user-1")

        reaper.assert_called_once_with("user-1")
