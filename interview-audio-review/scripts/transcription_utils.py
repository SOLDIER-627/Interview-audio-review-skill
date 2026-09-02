#!/usr/bin/env python3
"""Shared media inspection, VAD, quality detection, and transcript helpers."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


HUB_MODEL = "mlx-community/whisper-large-v3-turbo"
RUN_PREFIX = "interview-audio-review-"
MARKER = ".interview-audio-review-run.json"


def find_local_model(anchor: Path | None = None) -> Path:
    start = (anchor or Path(__file__)).resolve()
    for parent in start.parents:
        candidate = parent / "models" / "whisper-large-v3-turbo"
        if (candidate / "weights.safetensors").is_file():
            return candidate
    return start.parents[2] / "models" / "whisper-large-v3-turbo"


LOCAL_MODEL = find_local_model()
DEFAULT_MODEL = str(LOCAL_MODEL) if (LOCAL_MODEL / "weights.safetensors").is_file() else HUB_MODEL


def probe_media(source: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name,bit_rate",
            "-show_entries",
            "stream=index,codec_name,codec_type,channels,sample_rate",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    audio_streams = [item for item in payload.get("streams", []) if item.get("codec_type") == "audio"]
    if not audio_streams:
        raise RuntimeError("输入文件中没有可用音频流")
    media_format = payload.get("format") or {}
    duration = float(media_format.get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError("无法读取有效音频时长")
    return {
        "duration_seconds": duration,
        "format_name": media_format.get("format_name"),
        "bit_rate": int(media_format["bit_rate"]) if media_format.get("bit_rate") else None,
        "audio_streams": audio_streams,
    }


def physical_memory_bytes() -> int | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
        if page_size > 0 and page_count > 0:
            return page_size * page_count
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return None


def validate_local_model(model: str) -> list[str]:
    path = Path(model).expanduser()
    if not path.exists():
        return []
    problems: list[str] = []
    weights = path / "weights.safetensors"
    if not weights.is_file() or weights.stat().st_size < 1_000_000:
        problems.append(f"本地模型权重缺失或不完整：{weights}")
    return problems


def apple_preflight(model: str = DEFAULT_MODEL, require_metal: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    machine = platform.machine()
    if machine != "arm64":
        errors.append("MLX 路线要求原生 arm64 Python")
    if sys.version_info[:2] not in {(3, 11), (3, 12)}:
        warnings.append(f"当前 Python {platform.python_version()}；推荐使用 3.11 或 3.12")
    for command in ("ffmpeg", "ffprobe"):
        if shutil.which(command) is None:
            errors.append(f"缺少 {command}")
    if importlib.util.find_spec("mlx_whisper") is None:
        errors.append("缺少 mlx-whisper")
    errors.extend(validate_local_model(model))

    metal_ok: bool | None = None
    if require_metal and not errors:
        try:
            import mlx.core as mx
            import mlx_whisper  # noqa: F401 - importing verifies the complete runtime

            probe = mx.array([1.0, 2.0]) * 2
            mx.eval(probe)
            metal_ok = True
        except Exception as error:  # MLX raises backend-specific exception types.
            metal_ok = False
            errors.append(f"Metal/MLX 初始化失败：{error}")

    disk_free = shutil.disk_usage(tempfile.gettempdir()).free
    if disk_free < 2 * 1024**3:
        warnings.append("系统临时目录可用空间少于 2 GiB")
    return {
        "platform": platform.platform(),
        "machine": machine,
        "python": platform.python_version(),
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "mlx_whisper": importlib.util.find_spec("mlx_whisper") is not None,
        "metal_ok": metal_ok,
        "model": model,
        "memory_bytes": physical_memory_bytes(),
        "temp_disk_free_bytes": disk_free,
        "errors": errors,
        "warnings": warnings,
    }


def merge_intervals(intervals: Iterable[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    ordered = sorted((max(0.0, float(start)), max(0.0, float(end))) for start, end in intervals if end > start)
    merged: list[tuple[float, float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def parse_silencedetect(output: str, duration: float) -> list[tuple[float, float]]:
    events: list[tuple[int, str, float]] = []
    for position, match in enumerate(re.finditer(r"silence_(start|end):\s*([0-9.]+)", output)):
        events.append((position, match.group(1), float(match.group(2))))
    intervals: list[tuple[float, float]] = []
    current_start: float | None = None
    for _, kind, value in events:
        if kind == "start":
            current_start = value if current_start is None else min(current_start, value)
        elif current_start is not None:
            intervals.append((current_start, min(duration, value)))
            current_start = None
    if current_start is not None and current_start < duration:
        intervals.append((current_start, duration))
    return merge_intervals(intervals)


def detect_silences(
    source: Path,
    duration: float,
    noise_db: float = -35.0,
    min_silence_seconds: float = 1.5,
) -> list[tuple[float, float]]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_silence_seconds}",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_silencedetect(completed.stderr, duration)


def invert_intervals(
    silent_intervals: Iterable[tuple[float, float]],
    duration: float,
    padding: float = 0.25,
    minimum: float = 0.35,
) -> list[tuple[float, float]]:
    silences = merge_intervals(silent_intervals)
    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in silences:
        if start > cursor:
            speech.append((max(0.0, cursor - padding), min(duration, start + padding)))
        cursor = max(cursor, end)
    if cursor < duration:
        speech.append((max(0.0, cursor - padding), duration))
    return merge_intervals((item for item in speech if item[1] - item[0] >= minimum), gap=padding)


def interval_coverage(intervals: Iterable[tuple[float, float]], start: float, end: float) -> float:
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in intervals)


def intersect_intervals(
    intervals: Iterable[tuple[float, float]], start: float, end: float, minimum: float = 0.2
) -> list[tuple[float, float]]:
    result = []
    for left, right in intervals:
        clipped = (max(start, left), min(end, right))
        if clipped[1] - clipped[0] >= minimum:
            result.append(clipped)
    return merge_intervals(result)


def select_representative_window(
    duration: float,
    speech_intervals: list[tuple[float, float]],
    sample_seconds: float = 300.0,
    requested_start: float | None = None,
) -> tuple[float, float]:
    length = min(max(1.0, sample_seconds), duration)
    if requested_start is not None:
        start = min(max(0.0, requested_start), max(0.0, duration - length))
        return start, min(duration, start + length)
    if duration <= length:
        return 0.0, duration
    margin = min(120.0, duration * 0.05)
    if duration - length >= margin * 2:
        search_start = margin
        search_end = duration - length - margin
    else:
        search_start = 0.0
        search_end = duration - length
    candidates = {search_start, search_end}
    step = max(15.0, min(60.0, length / 5))
    position = search_start
    while position <= search_end:
        candidates.add(position)
        position += step
    for start, end in speech_intervals:
        candidates.add(min(max(search_start, start), search_end))
        candidates.add(min(max(search_start, end - length), search_end))
    center = duration / 2
    return max(
        ((start, start + length) for start in candidates),
        key=lambda item: (interval_coverage(speech_intervals, *item), -abs((sum(item) / 2) - center)),
    )


def compact(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()


def repeated_inside(text: str) -> bool:
    value = compact(text)
    if len(value) < 8:
        return False
    for width in range(1, min(12, len(value) // 3) + 1):
        unit = value[:width]
        repeated = unit * (len(value) // width)
        if value.startswith(repeated) and len(repeated) / len(value) >= 0.8:
            return True
    return False


def contains_unexpected_script(text: str) -> bool:
    unexpected = 0
    letters = 0
    for character in text:
        if not character.isalpha():
            continue
        letters += 1
        name = unicodedata.name(character, "")
        if any(script in name for script in ("CYRILLIC", "ARABIC", "HEBREW", "THAI", "HANGUL")):
            unexpected += 1
    return letters >= 5 and unexpected >= 3 and unexpected / letters >= 0.25


def common_hallucination(text: str) -> bool:
    normalized = compact(text)
    patterns = (
        "感谢观看",
        "谢谢观看",
        "字幕志愿者",
        "中文字幕",
        "请点赞订阅",
        "请不吝点赞",
    )
    return any(pattern in normalized for pattern in patterns)


def mark_suspicious(
    segments: list[dict[str, Any]],
    silence_intervals: list[tuple[float, float]] | None = None,
) -> tuple[list[dict[str, Any]], float]:
    marked: list[dict[str, Any]] = []
    score = 0.0
    previous = ""
    run = 0
    silences = silence_intervals or []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        current = compact(text)
        run = run + 1 if current and current == previous else 1
        previous = current
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        duration = max(0.0, end - start)
        flags = list(segment.get("quality_flags") or [])
        if current and run >= 4:
            flags.append("consecutive_repetition")
        if duration >= 15 and len(current) <= 12:
            flags.append("short_text_over_long_duration")
        if repeated_inside(text):
            flags.append("internal_repetition")
        if common_hallucination(text):
            flags.append("common_hallucination")
        if contains_unexpected_script(text):
            flags.append("unexpected_script")
        if duration >= 10 and not current:
            flags.append("empty_over_long_duration")
        avg_logprob = segment.get("avg_logprob")
        if avg_logprob is not None and float(avg_logprob) < -2.5 and duration >= 2:
            flags.append("low_logprob")
        if silences and duration > 0:
            ratio = interval_coverage(silences, start, end) / duration
            if ratio >= 0.7 and current:
                flags.append("speech_inside_detected_silence")
        copy = dict(segment)
        unique_flags = list(dict.fromkeys(flags))
        if unique_flags:
            copy["quality_flags"] = unique_flags
            weight = 0.5 if unique_flags == ["low_logprob"] else 1.0
            score += max(duration, 1.0) * weight
        marked.append(copy)
    return marked, score


def suspicious_ranges(
    segments: list[dict[str, Any]],
    start: float,
    end: float,
    padding: float = 8.0,
    merge_gap: float = 10.0,
) -> list[tuple[float, float]]:
    ranges = []
    for segment in segments:
        flags = set(segment.get("quality_flags") or [])
        if not flags or flags == {"low_logprob"}:
            continue
        left = max(start, float(segment.get("start") or start) - padding)
        right = min(end, float(segment.get("end") or left) + padding)
        if right > left:
            ranges.append((left, right))
    return merge_intervals(ranges, gap=merge_gap)


def text_join(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left[-1].isascii() and right[0].isascii() and left[-1].isalnum() and right[0].isalnum():
        return f"{left} {right}"
    return left + right


def postprocess_segments(
    segments: list[dict[str, Any]],
    merge_gap: float = 0.25,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filtered: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for segment in sorted(segments, key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0))):
        text = str(segment.get("text") or "").strip()
        flags = set(segment.get("quality_flags") or [])
        if not text:
            dropped.append({"start": segment.get("start"), "end": segment.get("end"), "reason": "empty"})
            continue
        if "speech_inside_detected_silence" in flags and (
            "common_hallucination" in flags or "unexpected_script" in flags
        ):
            dropped.append(
                {"start": segment.get("start"), "end": segment.get("end"), "reason": "silence_hallucination"}
            )
            continue
        copy = dict(segment)
        copy["text"] = text
        if filtered:
            previous = filtered[-1]
            previous_text = str(previous.get("text") or "")
            overlap = min(float(previous.get("end") or 0), float(copy.get("end") or 0)) - max(
                float(previous.get("start") or 0), float(copy.get("start") or 0)
            )
            similarity = SequenceMatcher(None, compact(previous_text), compact(text)).ratio()
            if compact(previous_text) == compact(text) or (overlap > 0 and similarity >= 0.92):
                previous_logprob = previous.get("avg_logprob")
                current_logprob = copy.get("avg_logprob")
                if current_logprob is not None and (previous_logprob is None or current_logprob > previous_logprob):
                    dropped.append(
                        {"start": previous.get("start"), "end": previous.get("end"), "reason": "overlap_duplicate"}
                    )
                    filtered[-1] = copy
                else:
                    dropped.append(
                        {"start": copy.get("start"), "end": copy.get("end"), "reason": "overlap_duplicate"}
                    )
                continue
            gap = float(copy.get("start") or 0) - float(previous.get("end") or 0)
            combined_duration = float(copy.get("end") or 0) - float(previous.get("start") or 0)
            same_quality = set(previous.get("quality_flags") or []) == set(copy.get("quality_flags") or [])
            terminal = previous_text.endswith(("。", "！", "？", "!", "?"))
            if 0 <= gap <= merge_gap and combined_duration <= 15 and same_quality and not terminal:
                previous["end"] = copy.get("end")
                previous["text"] = text_join(previous_text, text)
                chunks = list(previous.get("source_chunks") or [previous.get("source_chunk")])
                chunks.extend(copy.get("source_chunks") or [copy.get("source_chunk")])
                previous["source_chunks"] = [item for item in dict.fromkeys(chunks) if item]
                continue
        filtered.append(copy)
    for index, segment in enumerate(filtered):
        segment["id"] = index
    return filtered, dropped


def quality_score(segments: list[dict[str, Any]], silence_intervals: list[tuple[float, float]] | None = None) -> float:
    _, score = mark_suspicious(segments, silence_intervals)
    return score


def format_timestamp(seconds: float) -> str:
    value = max(0, int(math.floor(seconds)))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
