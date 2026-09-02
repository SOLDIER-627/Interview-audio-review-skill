from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from transcription_utils import (  # noqa: E402
    contains_unexpected_script,
    invert_intervals,
    mark_suspicious,
    parse_silencedetect,
    postprocess_segments,
    select_representative_window,
    suspicious_ranges,
)


class TranscriptionUtilsTests(unittest.TestCase):
    def test_parse_silence_with_open_interval(self) -> None:
        log = "silence_start: 10.0\nsilence_end: 20.0 | silence_duration: 10\nsilence_start: 90.0"
        self.assertEqual(parse_silencedetect(log, 100.0), [(10.0, 20.0), (90.0, 100.0)])

    def test_invert_silence_preserves_absolute_timeline(self) -> None:
        speech = invert_intervals([(10.0, 20.0), (90.0, 100.0)], 100.0, padding=0.25)
        self.assertEqual(speech, [(0.0, 10.25), (19.75, 90.25)])

    def test_representative_window_prefers_speech_dense_region(self) -> None:
        start, end = select_representative_window(1000.0, [(500.0, 850.0)], sample_seconds=300.0)
        self.assertGreaterEqual(start, 500.0)
        self.assertLessEqual(end, 850.0)

    def test_quality_flags_hallucination_and_unexpected_script(self) -> None:
        segments = [
            {"start": 0.0, "end": 30.0, "text": "感谢观看"},
            {"start": 31.0, "end": 40.0, "text": "привет мир test"},
        ]
        marked, score = mark_suspicious(segments, [(0.0, 30.0)])
        self.assertIn("common_hallucination", marked[0]["quality_flags"])
        self.assertIn("speech_inside_detected_silence", marked[0]["quality_flags"])
        self.assertTrue(contains_unexpected_script(segments[1]["text"]))
        self.assertGreater(score, 0)

    def test_suspicious_ranges_are_local(self) -> None:
        segments = [
            {"start": 100.0, "end": 110.0, "text": "异常", "quality_flags": ["common_hallucination"]}
        ]
        self.assertEqual(suspicious_ranges(segments, 0.0, 600.0, padding=8.0), [(92.0, 118.0)])

    def test_postprocess_drops_only_clear_silence_hallucination(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "感谢观看",
                "quality_flags": ["common_hallucination", "speech_inside_detected_silence"],
            },
            {"start": 31.0, "end": 32.0, "text": "真实回答"},
        ]
        cleaned, dropped = postprocess_segments(segments)
        self.assertEqual([item["text"] for item in cleaned], ["真实回答"])
        self.assertEqual(dropped[0]["reason"], "silence_hallucination")

    def test_postprocess_removes_overlap_duplicate(self) -> None:
        segments = [
            {"start": 1.0, "end": 3.0, "text": "同一句话", "avg_logprob": -0.5},
            {"start": 2.0, "end": 4.0, "text": "同一句话", "avg_logprob": -0.2},
        ]
        cleaned, dropped = postprocess_segments(segments)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["start"], 2.0)
        self.assertEqual(dropped[0]["reason"], "overlap_duplicate")


if __name__ == "__main__":
    unittest.main()
