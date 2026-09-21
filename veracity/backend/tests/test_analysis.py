"""Claim extraction, verification and the mode ladder.

The model is stubbed throughout. What is under test is our handling of what it
returns — the gate that stops a misheard sentence being fact-checked, the
placement of a claim on the timeline, the refusal to treat an outage as a
finding — not whether the model is any good.
"""
import pytest


class Seg:
    """A stored transcript segment, which is what extraction reads."""

    def __init__(self, ordinal, start_ms, end_ms, text, confidence=0.9):
        self.ordinal = ordinal
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.text = text
        self.confidence = confidence


SEGMENTS = [
    Seg(0, 0, 3000, "The reef stretches for over 2,300 kilometres."),
    Seg(1, 3000, 6000, "It supports more than 1,500 species of fish."),
    Seg(2, 6000, 9000, "Some say it has already died.", confidence=0.40),
]


def stub_json(monkeypatch, payload, target="app.analysis.claims.complete_json"):
    monkeypatch.setattr(target, lambda *a, **k: payload)


class TestClaimExtraction:
    def test_a_claim_is_placed_on_the_segment_it_came_from(self, monkeypatch):
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "It supports more than 1,500 species of fish.",
             "proposition": "The reef supports more than 1,500 species of fish.",
             "start_ms": 3000, "kind": "statistic"},
        ]})
        out = claims.extract(SEGMENTS)
        assert len(out) == 1
        assert out[0].start_ms == 3000 and out[0].end_ms == 6000

    def test_a_nearby_timestamp_snaps_to_the_right_segment(self, monkeypatch):
        """The model echoes back a timestamp we gave it, but rounds or picks the
        next line often enough to matter."""
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "x", "proposition": "y", "start_ms": 3200},
        ]})
        assert claims.extract(SEGMENTS)[0].start_ms == 3000

    def test_a_claim_that_cannot_be_placed_is_dropped(self, monkeypatch):
        """A claim with no timestamp cannot be cited, and an uncitable verdict
        is not useful to anybody."""
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "invented", "proposition": "invented",
             "start_ms": 999_999},
        ]})
        assert claims.extract(SEGMENTS) == []

    def test_a_low_confidence_segment_is_never_fact_checked(self, monkeypatch):
        """Verifying a misheard sentence reports high confidence in something
        that was never said — worse than no verdict at all."""
        from app.analysis import claims
        from app.db.models import ClaimVerdict
        stub_json(monkeypatch, {"claims": [
            {"spoken": "Some say it has already died.",
             "proposition": "The reef has already died.", "start_ms": 6000},
        ]})
        out = claims.extract(SEGMENTS)
        assert out[0].verdict == ClaimVerdict.unclear_audio
        assert out[0].is_checkable is False

    def test_a_confident_segment_is_checkable(self, monkeypatch):
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "a", "proposition": "b", "start_ms": 0},
        ]})
        assert claims.extract(SEGMENTS)[0].is_checkable is True

    def test_an_empty_transcript_extracts_nothing(self):
        from app.analysis import claims
        assert claims.extract([]) == []

    def test_a_claim_with_no_proposition_is_skipped(self, monkeypatch):
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "something", "proposition": "", "start_ms": 0},
        ]})
        assert claims.extract(SEGMENTS) == []

    def test_extraction_is_capped(self, monkeypatch):
        from app.analysis import claims
        stub_json(monkeypatch, {"claims": [
            {"spoken": "a", "proposition": f"claim {i}", "start_ms": 0}
            for i in range(100)
        ]})
        assert len(claims.extract(SEGMENTS, max_claims=5)) == 5


class TestVerification:
    def _claim(self, checkable=True):
        from app.analysis.claims import ExtractedClaim
        from app.db.models import ClaimVerdict
        return ExtractedClaim(
            spoken_text="it is 2,300 km", proposition="The reef is 2,300 km long.",
            start_ms=0, end_ms=3000, kind="statistic", asr_confidence=0.9,
            verdict=(ClaimVerdict.unsupported if checkable
                     else ClaimVerdict.unclear_audio),
        )

    def test_a_supported_verdict_is_carried_through(self, monkeypatch):
        from app.analysis import verify
        from app.analysis.search import Evidence
        from app.db.models import ClaimVerdict
        monkeypatch.setattr(verify, "search", lambda *a, **k: [
            Evidence("Reef facts", "https://example.org/reef", "It is 2,300 km long.")])
        monkeypatch.setattr(verify, "complete_json", lambda *a, **k: {
            "verdict": "supported", "confidence": 0.95, "reasoning": "matches",
            "quote": "It is 2,300 km long.", "source_url": "https://example.org/reef"})
        out = verify.verify_claims([self._claim()])[0]
        assert out["verdict"] == ClaimVerdict.supported
        assert out["independently_corroborated"] is True
        assert out["evidence"][0]["url"] == "https://example.org/reef"

    def test_a_verdict_with_no_quote_is_capped(self, monkeypatch):
        """A verdict with nothing quotable behind it is an opinion about the
        claim, not a finding about the evidence."""
        from app.analysis import verify
        from app.analysis.search import Evidence
        monkeypatch.setattr(verify, "search", lambda *a, **k: [
            Evidence("t", "https://e.org", "vaguely on topic")])
        monkeypatch.setattr(verify, "complete_json", lambda *a, **k: {
            "verdict": "supported", "confidence": 0.99, "quote": "", "reasoning": ""})
        assert verify.verify_claims([self._claim()])[0]["verdict_confidence"] <= 0.5

    def test_no_sources_found_is_unsupported_not_contradicted(self, monkeypatch):
        from app.analysis import verify
        from app.db.models import ClaimVerdict
        monkeypatch.setattr(verify, "search", lambda *a, **k: [])
        out = verify.verify_claims([self._claim()])[0]
        assert out["verdict"] == ClaimVerdict.unsupported
        assert out["independently_corroborated"] is False

    def test_an_unclear_claim_is_skipped_without_searching(self, monkeypatch):
        from app.analysis import verify
        from app.db.models import ClaimVerdict
        searched = []
        monkeypatch.setattr(verify, "search",
                            lambda *a, **k: searched.append(1) or [])
        out = verify.verify_claims([self._claim(checkable=False)])[0]
        assert out["verdict"] == ClaimVerdict.unclear_audio
        assert searched == [], "an unclear claim must not cost a search"

    def test_a_nonsense_verdict_string_degrades_to_unsupported(self, monkeypatch):
        from app.analysis import verify
        from app.analysis.search import Evidence
        from app.db.models import ClaimVerdict
        monkeypatch.setattr(verify, "search", lambda *a, **k: [
            Evidence("t", "https://e.org", "text")])
        monkeypatch.setattr(verify, "complete_json", lambda *a, **k: {
            "verdict": "mostly true-ish", "confidence": 0.8, "quote": "q"})
        assert verify.verify_claims([self._claim()])[0]["verdict"] == \
            ClaimVerdict.unsupported

    def test_a_failed_check_is_not_reported_as_a_finding(self, monkeypatch):
        """`unsupported` is a statement about the evidence. An outage is a
        statement about us, and collapsing the two reports a finding where there
        was only a failure."""
        from app.analysis import verify
        from app.db.models import ClaimVerdict

        def explode(*_a, **_k):
            raise RuntimeError("rate limit reached")

        monkeypatch.setattr(verify, "search", explode)
        out = verify.verify_claims([self._claim()])[0]
        assert out["verdict"] == ClaimVerdict.check_failed
        assert out["verdict_confidence"] is None
        assert "rate limiting" in out["reasoning"]

    def test_a_missing_search_backend_is_raised_not_swallowed(self, monkeypatch):
        """Silently returning "unsupported" for every claim would look like a
        result rather than a misconfiguration."""
        from app.analysis import verify
        from app.analysis.search import SearchUnavailable

        def unavailable(*_a, **_k):
            raise SearchUnavailable("no key")

        monkeypatch.setattr(verify, "search", unavailable)
        with pytest.raises(SearchUnavailable):
            verify.verify_claims([self._claim()])


class TestModeLadder:
    def _stub(self, monkeypatch, claim_count=2):
        from app.analysis import claims as claims_mod
        from app.analysis import pipeline, summarise as summarise_mod
        from app.analysis.claims import ExtractedClaim
        from app.db.models import ClaimVerdict

        monkeypatch.setattr(summarise_mod, "complete_json", lambda *a, **k: {
            "summary": "a summary", "key_points": [], "topics": []})
        made = [ExtractedClaim(spoken_text="s", proposition=f"p{i}",
                               start_ms=i * 1000, end_ms=i * 1000 + 500,
                               kind="other", asr_confidence=0.9,
                               verdict=ClaimVerdict.unsupported)
                for i in range(claim_count)]
        monkeypatch.setattr(claims_mod, "extract", lambda *a, **k: made)
        return pipeline

    def test_summary_does_not_extract_claims(self, monkeypatch):
        from app.db.models import AnalysisMode
        pipeline = self._stub(monkeypatch)
        out = pipeline.run(SEGMENTS, AnalysisMode.summary, asr_confidence=0.9)
        assert out["claims"] == []
        assert out["overall_confidence"] is None

    def test_deep_surfaces_claims_but_does_not_verify_them(self, monkeypatch):
        """Saying "we found these assertions" is useful on its own, and honest
        about the fact that nothing has checked them."""
        from app.db.models import AnalysisMode
        pipeline = self._stub(monkeypatch)
        out = pipeline.run(SEGMENTS, AnalysisMode.deep, asr_confidence=0.9)
        assert len(out["claims"]) == 2
        assert all(c["verdict_confidence"] is None for c in out["claims"])
        assert out["overall_confidence"] is None

    def test_report_verifies_and_scores(self, monkeypatch):
        from app.analysis import pipeline as pipeline_mod
        from app.db.models import AnalysisMode, ClaimVerdict
        pipeline = self._stub(monkeypatch)
        monkeypatch.setattr(pipeline_mod, "search_available", lambda: True)
        monkeypatch.setattr("app.analysis.verify.verify_claims", lambda c, **k: [
            {"verdict": ClaimVerdict.supported, "verdict_confidence": 0.9,
             "reasoning": "r", "evidence": [], "independently_corroborated": True}
            for _ in c])
        monkeypatch.setattr("app.analysis.perspectives.for_claims",
                            lambda *a, **k: [])
        out = pipeline.run(SEGMENTS, AnalysisMode.report, asr_confidence=0.9)
        assert out["overall_confidence"] is not None
        assert all(c["independently_corroborated"] for c in out["claims"])

    def test_report_without_a_search_backend_refuses_rather_than_pretending(
            self, monkeypatch):
        from app.analysis import pipeline as pipeline_mod
        from app.analysis.search import SearchUnavailable
        from app.db.models import AnalysisMode
        pipeline = self._stub(monkeypatch)
        monkeypatch.setattr(pipeline_mod, "search_available", lambda: False)
        with pytest.raises(SearchUnavailable):
            pipeline.run(SEGMENTS, AnalysisMode.report, asr_confidence=0.9)

    def test_an_empty_transcript_is_refused(self, monkeypatch):
        from app.db.models import AnalysisMode
        pipeline = self._stub(monkeypatch)
        with pytest.raises(ValueError, match="no transcript"):
            pipeline.run([], AnalysisMode.summary, asr_confidence=0.9)
