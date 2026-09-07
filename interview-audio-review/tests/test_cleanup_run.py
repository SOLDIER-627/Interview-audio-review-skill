from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "cleanup_run.py"
MARKER = ".interview-audio-review-run.json"


class CleanupRunTests(unittest.TestCase):
    def make_run_dir(self, mode: str) -> Path:
        run_dir = Path(tempfile.mkdtemp(prefix="interview-audio-review-test-"))
        marker = {
            "source": "/tmp/example.m4a",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": "test-model",
            "mode": mode,
        }
        (run_dir / MARKER).write_text(json.dumps(marker), encoding="utf-8")
        return run_dir

    def test_sample_cleanup_deletes_only_sample_run(self) -> None:
        run_dir = self.make_run_dir("sample")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--sample"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(run_dir.exists())

    def test_sample_cleanup_rejects_full_run(self) -> None:
        run_dir = self.make_run_dir("full")
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--sample"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--sample", result.stderr + result.stdout)
            self.assertTrue(run_dir.exists())
        finally:
            if run_dir.exists():
                shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
