"""The score has to be harder to fool than a mean."""
import pytest

from confidence import score_run

def claim(conf, verified=True, corroborated=False):
    return {"claim": "c", "verified": verified, "confidence": conf,
            "independently_corroborated": corroborated}

def docs(n, fallback=0):
    out = []
    for i in range(n):
        d = {"url": f"https://s{i}.com", "title": f"S{i}", "text": "t"}
        d["via_fallback"] = i < fallback
        out.append(d)
    return out


class TestAggregation:
    def test_one_unsupported_claim_is_not_averaged_away(self):
        """Four solid claims and one fabrication used to score the same as five
        middling ones. The fabrication is the thing that must not be buried."""
        good_only = score_run([claim(0.9) for _ in range(5)], docs(6))["score"]
        with_bad = score_run([claim(0.9) for _ in range(4)] + [claim(0.0, verified=False)], docs(6))["score"]
        assert with_bad < good_only - 0.1

    def test_no_claims_scores_zero_not_a_default(self):
        result = score_run([], docs(6))
        assert result["score"] == 0.0
        assert "No claims verified" in result["factors"][0]["label"]

    def test_independent_corroboration_raises_the_score(self):
        plain = score_run([claim(0.8) for _ in range(4)], docs(6))["score"]
        corrob = score_run([claim(0.8, corroborated=True) for _ in range(4)], docs(6))["score"]
        assert corrob > plain


class TestCaps:
    def test_thin_evidence_caps_the_score(self):
        """Perfect claims over two sources is not a confident answer."""
        result = score_run([claim(1.0) for _ in range(5)], docs(2))
        assert result["score"] <= 0.60
        assert any("Only 2 source" in f["label"] for f in result["factors"])

    def test_moderate_breadth_caps_below_high(self):
        result = score_run([claim(1.0, corroborated=True) for _ in range(5)], docs(4))
        assert result["score"] <= 0.80

    def test_mostly_snippets_caps_the_score(self):
        """A source that could only be read as a two-sentence snippet is not
        the paper it stands in for."""
        result = score_run([claim(1.0, corroborated=True) for _ in range(5)], docs(8, fallback=6))
        assert result["score"] <= 0.70
        assert any("snippet" in f["label"] for f in result["factors"])

    def test_full_text_across_many_sources_is_not_capped(self):
        result = score_run([claim(0.95, corroborated=True) for _ in range(5)], docs(8))
        assert result["score"] > 0.80

    def test_score_stays_in_range(self):
        assert 0.0 <= score_run([claim(1.0, corroborated=True) for _ in range(9)], docs(30))["score"] <= 1.0


class TestExplanation:
    def test_says_what_would_raise_it(self):
        result = score_run([claim(0.5, verified=False)], docs(2))
        assert result["to_improve"], "a score with no route to improving it is just decoration"

    def test_a_strong_run_has_nothing_to_flag(self):
        result = score_run([claim(0.95, corroborated=True) for _ in range(5)], docs(10))
        assert result["to_improve"] == []


class TestDeterministicReportSections:
    """Sources and the confidence block are facts the run already holds. Asking
    the model to reproduce them was a second, less accurate copy — and a place
    it could invent a reference."""

    def test_sources_list_matches_what_was_read(self):
        from agents.report_agent import _sources_section

        out = _sources_section([
            {"title": "IEA Report", "url": "https://iea.org/r"},
            {"title": "Paywalled", "url": "https://x.com/p", "via_fallback": True},
            {"title": "thesis.pdf", "url": "upload://thesis.pdf", "origin": "corpus"},
        ])

        assert "[IEA Report](https://iea.org/r)" in out
        # A snippet is not the page it stands for, and the list says so.
        assert "search snippet only" in out
        # An uploaded document has no browsable URL, so it is named not linked.
        assert "your uploaded document" in out
        assert "[thesis.pdf](upload://" not in out

    def test_no_sources_is_stated_plainly(self):
        from agents.report_agent import _sources_section
        assert "No sources" in _sources_section([])

    def test_confidence_section_reports_corroboration_and_limits(self):
        from agents.report_agent import _confidence_section

        out = _confidence_section({
            "overall_confidence": 0.62,
            "verified_claims": [
                {"claim": "a", "verified": True, "confidence": 0.9, "independently_corroborated": True},
                {"claim": "b", "verified": False, "confidence": 0.1},
            ],
            "confidence_factors": [{"label": "3 sources", "detail": "Capped on thin evidence."}],
            "confidence_to_improve": ["Allow another pass to gather more sources."],
        })

        assert "62%" in out
        assert "1 of 2 key claims" in out
        assert "1 held up against a source the answer was not written from" in out
        assert "3 sources" in out
        assert "What would raise this score" in out

    def test_confidence_section_survives_an_empty_run(self):
        from agents.report_agent import _confidence_section
        out = _confidence_section({"overall_confidence": 0.0})
        assert "0%" in out
