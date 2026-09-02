#!/usr/bin/env python3
"""Render normalized transcript JSON into a readable Markdown evidence draft."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from transcription_utils import format_timestamp


def speaker_label(segment: dict[str, object]) -> str:
    speaker = str(segment.get("speaker") or "说话人未区分")
    confidence = segment.get("speaker_confidence")
    if confidence is None:
        return speaker
    return f"{speaker}，角色置信度 {confidence}"


def render(payload: dict[str, object], title: str) -> str:
    metadata = dict(payload.get("metadata") or {})
    source = Path(str(metadata.get("source") or "未知来源")).name
    duration = float(metadata.get("duration_seconds") or 0.0)
    backend = str(metadata.get("backend") or "未知")
    lines = [
        f"# {title}转写稿",
        "",
        "## 转写说明",
        "",
        f"- 源文件：`{source}`",
        f"- 时长：约 {duration / 60:.2f} 分钟",
        f"- 转写后端：{backend}",
        f"- 处理日期：{date.today().isoformat()}",
        "- 角色标签只在证据充分时使用；不确定内容保留明确标记。",
        "",
        "## 转写正文",
        "",
    ]
    for segment in payload.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = format_timestamp(float(segment.get("start") or 0.0))
        end = format_timestamp(float(segment.get("end") or segment.get("start") or 0.0))
        flags = set(segment.get("quality_flags") or [])
        if "unreliable_transcription" in flags and "[" not in text:
            text = f"[转写不可靠] {text}"
        lines.append(f"[{start}–{end}] **{speaker_label(segment)}** {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="将标准化 JSON 渲染为可纠错的 Markdown 转写稿。")
    parser.add_argument("input", help="标准化转写 JSON")
    parser.add_argument("--output", required=True, help="输出 Markdown")
    parser.add_argument("--title", help="标题；默认使用源文件名")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"找不到输入：{input_path}")
    if output_path.exists() and not args.force:
        raise SystemExit(f"输出已存在：{output_path}；如需覆盖请使用 --force")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    source = Path(str((payload.get("metadata") or {}).get("source") or input_path.stem))
    title = args.title or source.stem
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render(payload, title), encoding="utf-8")
    print(f"输出：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
