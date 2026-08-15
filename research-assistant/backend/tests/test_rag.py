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
