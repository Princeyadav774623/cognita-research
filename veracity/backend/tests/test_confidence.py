"""Scoring, which is pure logic and therefore worth testing exhaustively.

The properties here are the ones that make the number mean something. A score
that can be talked up by adding more mediocre claims, or that ignores a
contradiction because four other claims were fine, is decoration.
"""
from app.analysis.confidence import score_analysis
from app.db.models import ClaimVerdict


def r(verdict, confidence=0.9):
    return {"verdict": verdict, "verdict_confidence": confidence}


class TestScoring:
    def test_all_supported_scores_high(self):
        s = score_analysis([r(ClaimVerdict.supported) for _ in range(6)],
                           asr_confidence=0.9)
        assert s.value > 0.85

    def test_one_contradiction_cannot_be_averaged_away(self):
        """Five good claims and one false one is not a 5/6 result. The false
        one is the most important thing on the page."""
        good = score_analysis([r(ClaimVerdict.supported) for _ in range(6)],
                              asr_confidence=0.9).value
        mixed = score_analysis(
            [r(ClaimVerdict.supported) for _ in range(5)]
            + [r(ClaimVerdict.contradicted, 0.95)],
            asr_confidence=0.9).value
        assert mixed <= 0.70, "a contradiction must cap the score"
        assert mixed < good - 0.2

    def test_poor_audio_caps_regardless_of_verdicts(self):
        """No number of supported claims makes a transcript the model could
        barely hear into a reliable one."""
        s = score_analysis([r(ClaimVerdict.supported) for _ in range(10)],
                           asr_confidence=0.55)
        assert s.value <= 0.50
        assert any("transcription" in f for f in s.factors)

    def test_mostly_unclear_audio_caps(self):
        results = ([r(ClaimVerdict.unclear_audio, None) for _ in range(4)]
                   + [r(ClaimVerdict.supported) for _ in range(2)])
        s = score_analysis(results, asr_confidence=0.9)
        assert s.value <= 0.60
        assert any("unclear" in f for f in s.factors)

    def test_too_few_claims_caps(self):
        s = score_analysis([r(ClaimVerdict.supported)], asr_confidence=0.95)
        assert s.value <= 0.75
        assert any("thin basis" in f for f in s.factors)

    def test_nothing_checkable_scores_zero_not_a_default(self):
        """An invented middling number reads as a measurement when nothing was
        measured."""
        s = score_analysis([r(ClaimVerdict.unclear_audio, None)],
                           asr_confidence=0.4)
        assert s.value == 0.0
        assert s.counts["unclear_audio"] == 1

    def test_an_empty_analysis_scores_zero(self):
        assert score_analysis([], asr_confidence=0.9).value == 0.0

    def test_unsupported_sits_between_supported_and_contradicted(self):
        sup = score_analysis([r(ClaimVerdict.supported) for _ in range(6)],
                             asr_confidence=0.9).value
        uns = score_analysis([r(ClaimVerdict.unsupported, 0.0) for _ in range(6)],
                             asr_confidence=0.9).value
        con = score_analysis([r(ClaimVerdict.contradicted, 0.9) for _ in range(6)],
                             asr_confidence=0.9).value
        assert con < uns < sup

    def test_every_cap_applied_is_explained(self):
        """A score a reader cannot interrogate is decoration."""
        s = score_analysis(
            [r(ClaimVerdict.contradicted, 0.9), r(ClaimVerdict.supported)],
            asr_confidence=0.5)
        assert len(s.factors) >= 2
        assert all(f.strip().endswith(".") for f in s.factors)
