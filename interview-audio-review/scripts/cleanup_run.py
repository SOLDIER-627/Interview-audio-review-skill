#!/usr/bin/env python3
"""在验证最终 review 后，安全删除一次面试复盘的临时目录。"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from output_validation import validate_artifact


RUN_PREFIX = "interview-audio-review-"
MARKER = ".interview-audio-review-run.json"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="安全清理面试复盘的本次临时产物。")
    result.add_argument("--run-dir", required=True, help="由本 Skill 转写脚本创建的临时目录")
    group = result.add_mutually_exclusive_group(required=True)
    group.add_argument("--artifact", help="已完成并需要保留的最终 Markdown 产物")
    group.add_argument("--review", help="已完成并需要保留的最终 review.md")
    group.add_argument("--transcript", help="已完成并需要保留的最终 transcript.md")
    group.add_argument("--failed", action="store_true", help="本次运行失败且没有最终报告")
    result.add_argument("--mode", choices=("transcript", "review"), help="与 --artifact 配合使用")
    return result


def validate_run_dir(run_dir: Path) -> dict[str, object]:
    if not run_dir.is_dir() or not run_dir.name.startswith(RUN_PREFIX):
        raise SystemExit("拒绝清理：目录不存在或名称不符合本 Skill 的临时目录规则")
    allowed_roots = {Path(tempfile.gettempdir()).resolve(), Path("/private/tmp").resolve()}
    if not any(root == run_dir.parent or root in run_dir.parents for root in allowed_roots):
        raise SystemExit("拒绝清理：本次运行目录不在系统临时目录内")
    marker = run_dir / MARKER
    if not marker.is_file():
        raise SystemExit("拒绝清理：缺少本次运行标记文件")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"拒绝清理：运行标记损坏：{error}") from error
    required = {"source", "created_at", "model"}
    if not required.issubset(payload):
        raise SystemExit("拒绝清理：运行标记缺少必要字段")
    return payload


def validate_final_artifact(artifact: Path, run_dir: Path, mode: str) -> None:
    if artifact == run_dir or run_dir in artifact.parents:
        raise SystemExit("拒绝清理：最终产物不能放在将被删除的临时目录中")
    problems = validate_artifact(artifact, mode)
    if problems:
        raise SystemExit(f"拒绝清理：最终 {mode} 内容不完整；" + "；".join(problems))


def main() -> int:
    args = parser().parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    validate_run_dir(run_dir)
    if args.artifact:
        if not args.mode:
            raise SystemExit("使用 --artifact 时必须同时指定 --mode transcript|review")
        validate_final_artifact(Path(args.artifact).expanduser().resolve(), run_dir, args.mode)
    elif args.mode:
        raise SystemExit("--mode 只能与 --artifact 配合使用")
    elif args.review:
        validate_final_artifact(Path(args.review).expanduser().resolve(), run_dir, "review")
    elif args.transcript:
        validate_final_artifact(Path(args.transcript).expanduser().resolve(), run_dir, "transcript")
    shutil.rmtree(run_dir)
    print(f"已清理本次临时目录：{run_dir}")
    print("原始录音、本地模型和最终 Markdown 产物未被删除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
