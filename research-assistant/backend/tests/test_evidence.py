"""Evidence selection and independent corroboration.

These cover the two structural defects the fact-checker rework fixed: evidence
chosen by position rather than relevance, and verification against only the
documents the draft was written from.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.evidence import select_evidence, chunk_document, tokenize


def _filler(n: int) -> str:
    return f"General background discussion number {n}. " * 40


class TestChunking:
    def test_windows_overlap_so_boundaries_are_not_lost(self):
        text = "A" * 500 + "THE DECIDING SENTENCE" + "B" * 500
        chunks = chunk_document(text, size=300, overlap=100)
        assert any("THE DECIDING SENTENCE" in c for c in chunks), \
            "a sentence on a boundary must survive whole in some window"

    def test_empty_text_yields_nothing(self):
        assert chunk_document("") == []
        assert chunk_document(None) == []

    def test_stopwords_are_dropped_but_domain_terms_survive(self):
        terms = tokenize("The Raft consensus algorithm is in the system")
        assert "raft" in terms and "consensus" in terms
        assert "the" not in terms and "is" not in terms


class TestSelectEvidence:
    def test_finds_a_fact_buried_mid_document_in_a_large_corpus(self):
        """The case the old code could not reach: 40 sources, the answer in the
        middle of #27. Positional truncation saw the top of the first six."""
        docs = [{"title": f"S{i}", "url": f"https://ex.com/{i}", "text": _filler(i)} for i in range(40)]
        docs[27]["text"] = (
            _filler(99)
            + " Raft elects a leader using randomized election timeouts between 150 and 300 milliseconds. "
            + _filler(98)
        )

        picked = select_evidence(
            "Raft uses randomized election timeouts of 150 to 300 milliseconds", docs, top_k=4
        )

        assert picked, "expected at least one passage"
        assert any("150 and 300 milliseconds" in p["text"] for p in picked)
        assert picked[0]["url"] == "https://ex.com/27"

    def test_prefers_distinct_sources_over_windows_of_one_page(self):
        """Agreement across sources is the signal; four windows of the same
        page is one source wearing four hats."""
        repeated = "Mamba uses selective state spaces. " * 200
        docs = [
            {"title": "Long", "url": "https://a.com", "text": repeated},
            {"title": "Other", "url": "https://b.com", "text": "Mamba uses selective state spaces in its design."},
        ]
        picked = select_evidence("Mamba selective state spaces", docs, top_k=4)
        assert len({p["url"] for p in picked}) == len(picked), "one passage per source"

    def test_irrelevant_chunks_are_excluded_not_used_as_padding(self):
        docs = [{"title": f"S{i}", "url": f"https://ex.com/{i}", "text": _filler(i)} for i in range(10)]
        picked = select_evidence("quantum chromodynamics lattice gauge theory", docs, top_k=4)
        assert picked == [], "zero-overlap chunks must not pad the evidence block"

    def test_provenance_is_carried_through(self):
        docs = [{"title": "Paper", "url": "upload://mine.pdf",
                 "text": "Selective state spaces reduce inference cost.", "origin": "corpus"}]
        picked = select_evidence("selective state spaces inference cost", docs, top_k=2)
        assert picked[0]["origin"] == "corpus"
        assert picked[0]["title"] == "Paper"

    def test_empty_inputs_are_safe(self):
        assert select_evidence("anything", []) == []
        assert select_evidence("", [{"title": "T", "url": "u", "text": "text"}]) == []


class TestEvidenceBlock:
    def test_sources_the_draft_already_used_are_not_counted_as_independent(self):
        """A 'corroborating' hit on a page the analyst already read corroborates
        nothing — it is the same evidence arriving twice."""
        from agents.factcheck_agent import _evidence_block

        prior = [{"title": "Known", "url": "https://known.com",
                  "text": "Transformers have quadratic attention complexity."}]
        corroborating = [{"title": "Known", "url": "https://known.com",
                          "text": "Transformers have quadratic attention complexity.",
                          "origin": "independent"}]

        block = _evidence_block("Transformers have quadratic attention complexity",
                                prior, corroborating)
        assert block["has_independent"] is False

    def test_a_genuinely_new_source_counts_as_independent(self):
        from agents.factcheck_agent import _evidence_block

        prior = [{"title": "Known", "url": "https://known.com",
                  "text": "Transformers have quadratic attention complexity."}]
        corroborating = [{"title": "Fresh", "url": "https://fresh.org",
                          "text": "Attention in Transformers scales quadratically with sequence length.",
                          "origin": "independent"}]

        block = _evidence_block("Transformers have quadratic attention complexity",
                                prior, corroborating)
        assert block["has_independent"] is True
        assert "[INDEPENDENT]" in block["text"]
        assert "[PRIOR]" in block["text"]

    def test_block_says_so_when_nothing_was_retrieved(self):
        from agents.factcheck_agent import _evidence_block
        block = _evidence_block("unrelated claim about lattice gauge theory", [], [])
        assert "No evidence retrieved" in block["text"]
        assert block["has_independent"] is False


class TestCorroborationFlag:
    @pytest.mark.asyncio
    @patch("agents.factcheck_agent.ChatGroq")
    async def test_flag_set_only_when_verified_and_independently_evidenced(self, mock_groq):
        from agents.factcheck_agent import factcheck_agent

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MagicMock(content='["Solar is cheapest", "Wind is cheapest"]'),
            MagicMock(content='{"verdicts": ['
                              '{"claim_index": 0, "verified": true, "confidence": 0.9, "source": "iea.org"},'
                              '{"claim_index": 1, "verified": false, "confidence": 0.1, "source": "none"}]}'),
        ]
        mock_groq.return_value = mock_llm

        state = make_fc_state(
            draft_answer="Solar is cheapest. Wind is cheapest.",
            source_documents=[{"title": "Draft source", "url": "https://used.com",
                               "text": "Solar is the cheapest source of electricity. Wind is cheapest too."}],
        )

        async def fake_corroboration(claims):
            # Only the first claim finds a new source.
            return {claims[0]: [{"title": "IEA", "url": "https://iea.org",
                                 "text": "Solar is the cheapest electricity source on record.",
                                 "origin": "independent"}],
                    claims[1]: []}

        with patch("agents.factcheck_agent._gather_corroboration", side_effect=fake_corroboration):
            result = await factcheck_agent(state)

        by_claim = {c["claim"]: c for c in result["verified_claims"]}
        assert by_claim["Solar is cheapest"]["independently_corroborated"] is True
        # Unverified claims never count as corroborated, whatever was retrieved.
        assert by_claim["Wind is cheapest"]["independently_corroborated"] is False

    @pytest.mark.asyncio
    @patch("agents.factcheck_agent.settings")
    async def test_no_tavily_key_degrades_instead_of_failing(self, mock_settings):
        from agents.factcheck_agent import _gather_corroboration
        mock_settings.tavily_api_key = ""
        assert await _gather_corroboration(["a claim"]) == {}

    @pytest.mark.asyncio
    @patch("agents.factcheck_agent._search_one_claim", side_effect=RuntimeError("tavily down"))
    async def test_search_failure_is_tolerated(self, _boom):
        """A claim with no corroborating search still gets judged on prior
        evidence — it just doesn't earn the independent-agreement confidence."""
        from agents.factcheck_agent import _gather_corroboration
        out = await _gather_corroboration(["a claim"])
        assert out == {}


def make_fc_state(**kwargs):
    from graph.research_graph import create_initial_state
    base = create_initial_state("test query", "sess-1")
    base.update(kwargs)
    return base


class TestCitationAudit:
    """A report whose citations don't resolve is worse than one with none,
    because it looks checked."""

    def test_counts_citations_that_match_sources_read(self):
        from agents.report_agent import audit_citations

        report = "Solar is cheapest ([IEA](https://iea.org/report)) and growing."
        docs = [{"title": "IEA", "url": "https://iea.org/report", "text": "..."}]

        audit = audit_citations(report, docs)
        assert audit == {"total": 1, "resolved": 1, "unresolved": []}

    def test_flags_a_url_the_run_never_read(self):
        from agents.report_agent import audit_citations

        report = "As shown in [Nature](https://nature.com/fabricated-paper), this holds."
        docs = [{"title": "IEA", "url": "https://iea.org/report", "text": "..."}]

        audit = audit_citations(report, docs)
        assert audit["resolved"] == 0
        assert audit["unresolved"] == ["https://nature.com/fabricated-paper"]

    def test_tracking_params_do_not_cause_false_mismatches(self):
        """The reader normalises URLs on the way in, so the audit has to
        normalise too or every utm-tagged source reads as fabricated."""
        from agents.report_agent import audit_citations

        report = "See [Report](https://iea.org/report?utm_source=newsletter)."
        docs = [{"title": "IEA", "url": "https://iea.org/report", "text": "..."}]

        assert audit_citations(report, docs)["resolved"] == 1

    def test_report_without_citations_is_not_an_error(self):
        from agents.report_agent import audit_citations
        audit = audit_citations("A plain summary with no links.", [])
        assert audit == {"total": 0, "resolved": 0, "unresolved": []}

    def test_bare_urls_are_not_treated_as_citations(self):
        from agents.report_agent import audit_citations
        audit = audit_citations("Visit https://example.com for details.", [])
        assert audit["total"] == 0
