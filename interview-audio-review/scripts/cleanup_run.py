#!/usr/bin/env python3
"""在验证最终 review 后，安全删除一次面试复盘的临时目录。"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path


RUN_PREFIX = "interview-audio-review-"
MARKER = ".interview-audio-review-run.json"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="安全清理面试复盘的本次临时产物。")
    result.add_argument("--run-dir", required=True, help="由本 Skill 转写脚本创建的临时目录")
    group = result.add_mutually_exclusive_group(required=True)
    group.add_argument("--review", help="已完成并需要保留的最终 review.md")
    group.add_argument("--failed", action="store_true", help="本次运行失败且没有最终报告")
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


def validate_review(review: Path, run_dir: Path) -> None:
    if not review.is_file() or review.suffix.lower() != ".md":
        raise SystemExit("拒绝清理：最终 review.md 不存在")
    if review == run_dir or run_dir in review.parents:
        raise SystemExit("拒绝清理：最终 review 不能放在将被删除的临时目录中")
    text = review.read_text(encoding="utf-8")
    required = ["总体结论", "面试问答", "推荐回答", "处理与证据说明"]
    missing = [heading for heading in required if heading not in text]
    problems = []
    if len(text) < 1000:
        problems.append("正文少于 1000 个字符")
    if missing:
        problems.append("缺少章节：" + "、".join(missing))
    if problems:
        raise SystemExit("拒绝清理：最终 review 内容不完整；" + "；".join(problems))


def main() -> int:
    args = parser().parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    validate_run_dir(run_dir)
    if args.review:
        validate_review(Path(args.review).expanduser().resolve(), run_dir)
    shutil.rmtree(run_dir)
    print(f"已清理本次临时目录：{run_dir}")
    print("原始录音、本地模型和最终 review.md 未被删除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
