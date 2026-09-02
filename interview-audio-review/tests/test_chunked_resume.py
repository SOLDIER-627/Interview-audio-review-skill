from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from transcribe_chunked import (  # noqa: E402
    create_run_dir,
    ranges,
    runtime_parameters,
    split_window,
    transcribe_parent,
)
from transcription_utils import MARKER  # noqa: E402


def arguments() -> argparse.Namespace:
    return argparse.Namespace(
        resume=None,
        run_dir=None,
        preflight_sample=False,
        model="local-model",
        language="zh",
        initial_prompt="Redis",
        chunk_seconds=600.0,
        overlap_seconds=10.0,
        retry_padding_seconds=8.0,
        retry_max_seconds=120.0,
        no_vad=False,
        vad_noise_db=-35.0,
        vad_min_silence_seconds=1.5,
        vad_padding_seconds=0.25,
        vad_merge_gap_seconds=3.0,
        output=None,
    )


class ChunkedResumeTests(unittest.TestCase):
    def test_ranges_and_targeted_split(self) -> None:
        self.assertEqual(ranges(1200.0, 600.0, 10.0), [(0.0, 600.0), (590.0, 1190.0), (1180.0, 1200.0)])
        self.assertEqual(split_window(10.0, 260.0, 120.0), [(10.0, 130.0), (130.0, 250.0), (250.0, 260.0)])
        segments = [{"end": 100.0}, {"end": 220.0}, {"end": 260.0}]
        self.assertEqual(
            split_window(10.0, 260.0, 120.0, segments),
            [(10.0, 100.0), (100.0, 220.0), (220.0, 260.0)],
        )

    def test_resume_validates_source_and_parameters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="resume-test-") as temporary:
            source = Path(temporary) / "audio.m4a"
            source.write_bytes(b"audio")
            run_dir = Path(temporary) / "interview-audio-review-run"
            args = arguments()
            args.run_dir = str(run_dir)
            created, marker = create_run_dir(source, args)
            self.assertEqual(created, run_dir.resolve())
            self.assertEqual(marker["parameters"], runtime_parameters(args))
            self.assertTrue((run_dir / MARKER).is_file())

            resumed_args = arguments()
            resumed_args.resume = str(run_dir)
            resumed, loaded = create_run_dir(source, resumed_args)
            self.assertEqual(resumed, run_dir.resolve())
            self.assertEqual(loaded["source"], str(source))

    def test_resume_rejects_parameter_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="resume-test-") as temporary:
            source = Path(temporary) / "audio.m4a"
            source.write_bytes(b"audio")
            run_dir = Path(temporary) / "interview-audio-review-run"
            args = arguments()
            args.run_dir = str(run_dir)
            create_run_dir(source, args)
            resumed_args = arguments()
            resumed_args.resume = str(run_dir)
            resumed_args.chunk_seconds = 300.0
            with self.assertRaises(SystemExit):
                create_run_dir(source, resumed_args)

    def test_parent_retries_only_local_suspicious_window(self) -> None:
        with tempfile.TemporaryDirectory(prefix="targeted-retry-") as temporary:
            source = Path(temporary) / "audio.m4a"
            source.write_bytes(b"audio")
            run_dir = Path(temporary)
            args = arguments()
            first_pass = {
                "elapsed_seconds": 1.0,
                "segments": [
                    {"start": 100.0, "end": 110.0, "text": "感谢观看"},
                    {"start": 300.0, "end": 305.0, "text": "真实回答"},
                ],
                "window_json": "window-first.json",
            }
            retry = {
                "elapsed_seconds": 0.2,
                "segments": [{"start": 100.0, "end": 110.0, "text": "纠正内容"}],
                "window_json": "window-retry.json",
            }
            with patch("transcribe_chunked.transcribe_window", side_effect=[first_pass, retry]) as mocked:
                parent = transcribe_parent(
                    object(), source, run_dir, 0.0, 600.0, 0, [(0.0, 600.0)], [], args
                )
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(mocked.call_args_list[1].args[3:5], (92.0, 118.0))
            self.assertEqual(parent["warnings"][0]["action"], "replaced_with_local_retry")
            self.assertEqual([item["text"] for item in parent["segments"]], ["纠正内容", "真实回答"])


if __name__ == "__main__":
    unittest.main()
