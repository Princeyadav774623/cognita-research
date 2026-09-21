import os

import pytest

from app.ingest.audio import SAMPLE_RATE, AudioError, extract, segment
from app.ingest.probe import probe


class TestExtract:
    def test_normalises_to_16k_mono_and_drops_video(self, tone_media, tmp_path):
        out = extract(tone_media, str(tmp_path / "a.wav"))
        info = probe(out)
        assert info.sample_rate == SAMPLE_RATE
        assert info.channels == 1
        assert not info.has_video


class TestSegment:
    def test_a_file_under_the_limit_is_not_split(self, tone_media, tmp_path):
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        parts = segment(audio, str(tmp_path / "p"), seconds=600,
                        max_bytes=100_000_000)
        assert len(parts) == 1
        assert parts[0].offset_ms == 0

    def test_offsets_are_contiguous_and_cover_the_media(self, tone_media, tmp_path):
        """The bug this exists for: if offsets drift, every citation in the
        product is wrong by minutes and nothing else in the system notices."""
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        parts = segment(audio, str(tmp_path / "p"), seconds=10,
                        max_bytes=10 * 32_000 + 1024)
        assert len(parts) == 3
        for a, b in zip(parts, parts[1:]):
            assert a.offset_ms + a.duration_ms == b.offset_ms
        assert parts[0].offset_ms == 0
        assert parts[-1].offset_ms + parts[-1].duration_ms == pytest.approx(
            probe(audio).duration_ms, abs=200)

    def test_no_sub_syllable_remnant_part_is_produced(self, tone_media, tmp_path):
        """ffmpeg's segment muxer leaves a fragment at the end and stamps it
        with the *source's* duration, so probing it reports the whole file.
        Cutting explicitly is what avoids both."""
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        parts = segment(audio, str(tmp_path / "p"), seconds=7,
                        max_bytes=7 * 32_000 + 1024)
        assert all(p.duration_ms >= 200 for p in parts)
        assert all(os.path.getsize(p.path) > 0 for p in parts)

    def test_a_cap_too_small_for_one_second_is_refused(self, tone_media, tmp_path):
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        with pytest.raises(AudioError, match="one second"):
            segment(audio, str(tmp_path / "p"), seconds=10, max_bytes=1_000)

    def test_step_shrinks_to_honour_the_cap(self, tone_media, tmp_path):
        """Asked for 10s parts under a cap that only fits 2s, it must produce
        2s parts rather than 10s parts that breach the cap."""
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        cap = 2 * 32_000 + 1024
        parts = segment(audio, str(tmp_path / "p"), seconds=10, max_bytes=cap)
        assert all(p.bytes <= cap for p in parts)
        assert all(p.duration_ms <= 2_100 for p in parts)

    def test_offsets_are_exact_not_approximate(self, tone_media, tmp_path):
        """Byte arithmetic over PCM frames, so these are equalities."""
        audio = extract(tone_media, str(tmp_path / "a.wav"))
        parts = segment(audio, str(tmp_path / "p"), seconds=10,
                        max_bytes=10 * 32_000 + 1024)
        assert [p.offset_ms for p in parts] == [0, 10_000, 20_000]
        assert all(p.duration_ms == 10_000 for p in parts)
