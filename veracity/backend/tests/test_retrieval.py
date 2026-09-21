"""Retrieval: chunking, the embedding prefix, and rank fusion."""
import pytest

from app.ingest.chunk import chunk_transcript
from app.ingest.transcribe import Segment, Word


def seg(start, end, text, conf=0.9, words=None):
    return Segment(start_ms=start, end_ms=end, text=text, confidence=conf,
                   words=words or [])


class TestChunking:
    def test_a_chunk_keeps_the_span_it_covers(self):
        """The whole point of retrieving a chunk is to send the reader to the
        moment it came from."""
        chunks = chunk_transcript(
            [seg(0, 1000, "one"), seg(1000, 2000, "two")],
            target_chars=100, overlap_chars=0)
        assert chunks[0].start_ms == 0 and chunks[0].end_ms == 2000

    def test_overlap_carries_timestamps_backwards_not_just_text(self):
        """A chunk built from an overlap legitimately starts earlier than its
        new content; copying the text without the timing would cite the wrong
        moment."""
        chunks = chunk_transcript(
            [seg(0, 1000, "aaaa"), seg(1000, 2000, "bbbb"),
             seg(2000, 3000, "cccc")],
            target_chars=8, overlap_chars=4)
        assert len(chunks) > 1
        assert chunks[1].start_ms < 2000

    def test_an_oversize_utterance_is_split_on_word_timings(self):
        """Splitting the text without the words would invent timestamps."""
        words = [Word(f"w{i}", i * 100, i * 100 + 90, 0.9, True) for i in range(40)]
        long = seg(0, 4000, " ".join(w.text for w in words), words=words)
        chunks = chunk_transcript([long], target_chars=40, overlap_chars=0)
        assert len(chunks) > 1
        assert chunks[0].start_ms == 0
        assert chunks[-1].end_ms <= 4000
        for c in chunks:
            assert c.end_ms >= c.start_ms

    def test_an_oversize_utterance_with_no_word_timings_is_kept_whole(self):
        """An honest big chunk beats a neat one with made-up timing."""
        long = seg(0, 4000, "x" * 500)
        chunks = chunk_transcript([long], target_chars=50, overlap_chars=0)
        assert len(chunks) == 1

    def test_timecodes_are_human_readable(self):
        chunks = chunk_transcript([seg(0, 1000, "a")], target_chars=100)
        assert chunks[0].timecode() == "0:00"
        hour = chunk_transcript([seg(3_723_000, 3_724_000, "a")],
                                target_chars=100)
        assert hour[0].timecode() == "1:02:03"

    def test_an_empty_transcript_yields_nothing(self):
        assert chunk_transcript([]) == []

    def test_confidence_is_weighted_by_duration_not_by_segment(self):
        """A two-word aside must not counterbalance a minute of difficult audio."""
        chunks = chunk_transcript(
            [seg(0, 60_000, "long difficult stretch", conf=0.5),
             seg(60_000, 60_500, "yeah", conf=1.0)],
            target_chars=1000, overlap_chars=0)
        assert chunks[0].confidence < 0.55


class TestEmbeddingPrefix:
    def test_the_instruction_prefix_is_applied_to_queries_only(self, monkeypatch):
        """bge is asymmetric. Getting this backwards degrades retrieval
        silently — results still come back and still look plausible."""
        from app.ingest import embed

        seen = []

        class FakeModel:
            def embed(self, texts):
                seen.extend(texts)
                return [type("V", (), {"tolist": lambda self: [0.0]})()
                        for _ in texts]

        monkeypatch.setattr(embed, "_load", lambda: FakeModel())
        embed.embed_passages(["a passage"])
        embed.embed_query("a question")

        assert seen[0] == "a passage", "a passage must not be prefixed"
        assert seen[1].startswith(embed.QUERY_PREFIX)
        assert seen[1].endswith("a question")

    def test_embedding_nothing_does_not_load_the_model(self, monkeypatch):
        from app.ingest import embed

        def explode():
            raise AssertionError("loaded the model for an empty list")

        monkeypatch.setattr(embed, "_load", explode)
        assert embed.embed_passages([]) == []


class TestRankFusion:
    """RRF fuses by position, because cosine distance and ts_rank are different
    scales with no meaningful conversion between them."""

    def _fuse(self, vector_ids, keyword_ids):
        from app.analysis.retrieve import RRF_K
        scores = {}
        for ranking in (vector_ids, keyword_ids):
            for rank, cid in enumerate(ranking, start=1):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        return [cid for cid, _ in
                sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]

    def test_agreement_between_both_retrievers_wins(self):
        fused = self._fuse(["a", "b", "c"], ["c", "d", "e"])
        assert fused[0] == "c", "a chunk both halves found should rank first"

    def test_a_chunk_only_one_retriever_found_still_appears(self):
        """The case hybrid search exists for: an exact token no embedding ranks
        well, or a paraphrase no keyword search matches."""
        fused = self._fuse(["a", "b"], ["z"])
        assert "z" in fused

    def test_a_high_rank_in_one_beats_a_low_rank_in_the_other(self):
        fused = self._fuse(["top"], ["x"] * 10 + ["bottom"])
        assert fused.index("top") < fused.index("bottom")
