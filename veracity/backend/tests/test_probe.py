import pytest

from app.ingest.probe import ProbeError, probe


class TestProbe:
    def test_reads_duration_and_streams(self, tone_media):
        info = probe(tone_media)
        assert info.duration_ms == pytest.approx(30_000, abs=200)
        assert info.has_audio and info.has_video
        assert info.audio_codec == "aac"

    def test_a_file_with_no_audio_is_refused(self, silent_media):
        # Accepting it would mean a job that runs the whole pipeline and
        # produces an empty transcript, with the failure surfacing minutes later.
        with pytest.raises(ProbeError, match="no audio track"):
            probe(silent_media)

    def test_a_non_media_file_is_refused(self, tmp_path):
        p = tmp_path / "notes.md"
        p.write_text("# not media")
        with pytest.raises(ProbeError):
            probe(str(p))

    def test_missing_file_is_refused(self):
        with pytest.raises(ProbeError):
            probe("/nonexistent/nope.mp4")

    def test_duration_survives_a_container_that_omits_it(self, tone_media, tmp_path):
        """FLAC written by a cut has no duration header at all.

        probe() decodes to find out rather than giving up, because this is the
        normal shape of everything the segmenter produces.
        """
        import subprocess
        out = tmp_path / "headerless.flac"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-i", tone_media, "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "flac",
            "-map_metadata", "-1", "-f", "flac", str(out),
        ], capture_output=True, check=True)
        assert probe(str(out)).duration_ms == pytest.approx(30_000, abs=300)
