#!/usr/bin/env python3
"""Structured validation for final transcript and interview-review artifacts."""

from __future__ import annotations

import re
from pathlib import Path


TIMESTAMP_RANGE = r"\[\d{2}:\d{2}:\d{2}[–-]\d{2}:\d{2}:\d{2}\]"
QUESTION_HEADING = re.compile(rf"^##\s+Q\d+(?:\.\d+)*\..+{TIMESTAMP_RANGE}\s*$", re.MULTILINE)
TRANSCRIPT_LINE = re.compile(rf"^{TIMESTAMP_RANGE}(?:\s+\*\*[^*]+\*\*)?\s+.+$", re.MULTILINE)
SECTION_HEADING = re.compile(r"^\*\*(面试官问题|我的回答|改进建议|推荐回答)\*\*\s*$", re.MULTILINE)


def _nonempty_after(block: str, marker: str, next_markers: list[str]) -> bool:
    start = block.find(marker)
    if start < 0:
        return False
    start += len(marker)
    ends = [block.find(item, start) for item in next_markers]
    valid_ends = [position for position in ends if position >= 0]
    end = min(valid_ends) if valid_ends else len(block)
    return bool(block[start:end].strip())


def validate_review_text(text: str) -> list[str]:
    problems: list[str] = []
    if len(text.strip()) < 1000:
        problems.append("正文少于 1000 个字符")
    for heading in ("处理与证据说明", "总体结论", "面试问答"):
        if not re.search(rf"^#+\s+{re.escape(heading)}\s*$", text, re.MULTILINE):
            problems.append(f"缺少章节：{heading}")
    matches = list(QUESTION_HEADING.finditer(text))
    if not matches:
        problems.append("没有带时间戳的正式问题")
        return problems
    expected = ["面试官问题", "我的回答", "改进建议", "推荐回答"]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start():end]
        title = match.group(0).strip()
        headings = SECTION_HEADING.findall(block)
        if headings[:4] != expected:
            problems.append(f"{title} 的四个必需小节缺失或顺序错误")
            continue
        markers = [f"**{item}**" for item in expected]
        for marker_index, marker in enumerate(markers):
            if not _nonempty_after(block, marker, markers[marker_index + 1:]):
                problems.append(f"{title} 的 {marker.strip('*')} 为空")
        recommendation_start = block.find("**推荐回答**")
        if recommendation_start >= 0:
            recommendation = block[recommendation_start + len("**推荐回答**"):]
            if not re.search(r"^\s*(?:1\.|[-*])\s+\S", recommendation, re.MULTILINE):
                problems.append(f"{title} 的推荐回答未分点")
    return list(dict.fromkeys(problems))


def validate_transcript_text(text: str) -> list[str]:
    problems: list[str] = []
    if len(text.strip()) < 200:
        problems.append("转写正文少于 200 个字符")
    if not re.search(r"^#\s+.+转写稿\s*$", text, re.MULTILINE):
        problems.append("缺少转写稿标题")
    if not re.search(r"^##\s+转写说明\s*$", text, re.MULTILINE):
        problems.append("缺少章节：转写说明")
    if not re.search(r"^##\s+转写正文\s*$", text, re.MULTILINE):
        problems.append("缺少章节：转写正文")
    if len(TRANSCRIPT_LINE.findall(text)) < 1:
        problems.append("没有带时间戳的转写内容")
    return problems


def validate_artifact(path: Path, mode: str) -> list[str]:
    if not path.is_file() or path.suffix.lower() != ".md":
        return ["最终 Markdown 文件不存在"]
    expected_pattern = rf"\.{re.escape(mode)}(?:-[^.]+)?\.md$"
    if not re.search(expected_pattern, path.name):
        return [f"文件名不符合 {mode} 模式约定"]
    text = path.read_text(encoding="utf-8")
    if mode == "review":
        return validate_review_text(text)
    if mode == "transcript":
        return validate_transcript_text(text)
    return [f"未知输出模式：{mode}"]
