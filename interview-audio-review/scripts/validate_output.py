#!/usr/bin/env python3
"""Validate a final transcript or review without deleting evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from output_validation import validate_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化验证最终转写稿或复盘报告。")
    parser.add_argument("artifact", help="最终 Markdown 文件")
    parser.add_argument("--mode", choices=("transcript", "review"), required=True)
    args = parser.parse_args()
    path = Path(args.artifact).expanduser().resolve()
    problems = validate_artifact(path, args.mode)
    if problems:
        for problem in problems:
            print(f"错误：{problem}")
        return 1
    print(f"验证通过：{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
