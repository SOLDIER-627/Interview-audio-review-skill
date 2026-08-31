#!/usr/bin/env python3
"""长录音分片转写、重复幻觉检测、局部重试和绝对时间轴合并。"""

from __future__ import annotations

import argparse
import atexit
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HUB_MODEL = "mlx-community/whisper-large-v3-turbo"


def find_local_model() -> Path:
    """允许 Skill 被外层项目目录包装后继续找到共享本地模型。"""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "models" / "whisper-large-v3-turbo"
        if (candidate / "weights.safetensors").is_file():
            return candidate
    return Path(__file__).resolve().parents[2] / "models" / "whisper-large-v3-turbo"


LOCAL_MODEL = find_local_model()
DEFAULT_MODEL = str(LOCAL_MODEL) if (LOCAL_MODEL / "weights.safetensors").is_file() else HUB_MODEL
RUN_PREFIX = "interview-audio-review-"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="分片转写长面试录音并标记可疑 Whisper 幻觉。")
    result.add_argument("input", help="输入音频或视频文件")
    result.add_argument("--output", help="合并后的临时 JSON；默认写入本次临时目录")
    result.add_argument("--run-dir", help="本次临时目录；默认在系统临时目录安全创建")
    result.add_argument("--model", default=DEFAULT_MODEL, help="本地模型目录或 Hugging Face 仓库")
    result.add_argument("--language", default="zh", help="主要语言；auto 表示自动检测")
    result.add_argument("--initial-prompt", help="姓名、公司名和技术术语提示")
    result.add_argument("--chunk-seconds", type=float, default=600.0, help="首轮分片秒数，默认 600")
    result.add_argument("--overlap-seconds", type=float, default=10.0, help="首轮重叠秒数，默认 10")
    result.add_argument("--retry-seconds", type=float, default=300.0, help="可疑分片重试长度，默认 300")
    result.add_argument("--force", action="store_true", help="允许覆盖临时输出 JSON")
    return result


def require_environment() -> None:
    missing = []
    if platform.machine() != "arm64":
        missing.append("原生 arm64 Python")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        missing.append("ffmpeg/ffprobe")
    if importlib.util.find_spec("mlx_whisper") is None:
        missing.append("mlx-whisper")
    if missing:
        raise SystemExit("缺少运行条件：" + "、".join(missing))


def probe_duration(source: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(completed.stdout.strip())


def ranges(duration: float, length: float, overlap: float) -> list[tuple[float, float]]:
    if length <= 0 or overlap < 0 or overlap >= length:
        raise ValueError("分片长度必须大于 0，重叠必须不小于 0 且小于分片长度")
    result: list[tuple[float, float]] = []
    start = 0.0
    step = length - overlap
    while start < duration:
        end = min(duration, start + length)
        result.append((start, end))
        if end >= duration:
            break
        start += step
    return result


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


def mark_suspicious(segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    marked: list[dict[str, Any]] = []
    score = 0.0
    previous = ""
    run = 0
    for segment in segments:
        current = compact(str(segment.get("text") or ""))
        run = run + 1 if current and current == previous else 1
        previous = current
        duration = max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0))
        flags: list[str] = []
        if current and run >= 4:
            flags.append("consecutive_repetition")
        if duration >= 15 and len(current) <= 12:
            flags.append("short_text_over_long_duration")
        if repeated_inside(current):
            flags.append("internal_repetition")
        copy = dict(segment)
        if flags:
            copy["quality_flags"] = flags
            score += max(duration, 1.0)
        marked.append(copy)
    return marked, score


def extract(source: Path, destination: Path, start: float, end: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{end - start:.3f}",
            "-i",
            str(source),
            "-c",
            "copy",
            "-y",
            str(destination),
        ],
        check=True,
    )


def transcribe_piece(
    mlx_whisper: Any,
    source: Path,
    run_dir: Path,
    start: float,
    end: float,
    index: str,
    model: str,
    language: str,
    prompt: str | None,
) -> dict[str, Any]:
    audio_path = run_dir / f"chunk-{index}-{int(start):06d}-{int(end):06d}{source.suffix}"
    extract(source, audio_path, start, end)
    started = time.perf_counter()
    raw = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=None if language.lower() == "auto" else language,
        task="transcribe",
        word_timestamps=False,
        initial_prompt=prompt,
        verbose=False,
    )
    elapsed = time.perf_counter() - started
    normalized = []
    for position, segment in enumerate(raw.get("segments") or []):
        normalized.append(
            {
                "id": position,
                "start": float(segment.get("start") or 0.0) + start,
                "end": float(segment.get("end") or 0.0) + start,
                "speaker": None,
                "text": str(segment.get("text") or "").strip(),
                "avg_logprob": float(segment["avg_logprob"]) if segment.get("avg_logprob") is not None else None,
                "no_speech_prob": float(segment["no_speech_prob"]) if segment.get("no_speech_prob") is not None else None,
                "source_chunk": audio_path.name,
            }
        )
    marked, score = mark_suspicious(normalized)
    chunk_json = run_dir / f"chunk-{index}.json"
    chunk_json.write_text(
        json.dumps(
            {
                "start": start,
                "end": end,
                "elapsed_seconds": elapsed,
                "suspicion_score": score,
                "segments": marked,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "start": start,
        "end": end,
        "elapsed_seconds": elapsed,
        "suspicion_score": score,
        "segments": marked,
        "chunk_json": chunk_json.name,
    }


def merge_chunks(chunks: list[dict[str, Any]], overlap: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        lower = chunk["start"] if index == 0 else chunk["start"] + overlap / 2
        upper = chunk["end"] if index == len(chunks) - 1 else chunks[index + 1]["start"] + overlap / 2
        for segment in chunk["segments"]:
            if lower <= float(segment["start"]) < upper:
                copy = dict(segment)
                copy["id"] = len(merged)
                merged.append(copy)
    return merged


def main() -> int:
    args = parser().parse_args()
    require_environment()
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"找不到输入文件：{source}")

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        if run_dir.exists() and any(run_dir.iterdir()):
            raise SystemExit("拒绝使用：指定的临时目录不是空目录")
        run_dir.mkdir(parents=True, exist_ok=True)
        if not run_dir.name.startswith(RUN_PREFIX):
            raise SystemExit(f"临时目录名称必须以 {RUN_PREFIX} 开头")
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=RUN_PREFIX)).resolve()
    output = Path(args.output).expanduser().resolve() if args.output else run_dir / "transcript.merged.json"
    if output.exists() and not args.force:
        raise SystemExit(f"临时输出已存在：{output}；如需覆盖请使用 --force")

    duration = probe_duration(source)
    marker = run_dir / ".interview-audio-review-run.json"
    marker.write_text(
        json.dumps(
            {
                "source": str(source),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "model": args.model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cleanup_state = {"completed": False}

    def cleanup_incomplete_run() -> None:
        if not cleanup_state["completed"] and run_dir.is_dir() and marker.is_file():
            shutil.rmtree(run_dir)

    atexit.register(cleanup_incomplete_run)

    import mlx_whisper

    all_started = time.perf_counter()
    initial: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(ranges(duration, args.chunk_seconds, args.overlap_seconds)):
        item = transcribe_piece(
            mlx_whisper, source, run_dir, start, end, f"p{index:03d}", args.model, args.language, args.initial_prompt
        )
        if item["suspicion_score"] >= 15:
            retry_parts: list[dict[str, Any]] = []
            local_duration = end - start
            retry_overlap = min(5.0, args.retry_seconds / 10)
            for retry_index, (local_start, local_end) in enumerate(
                ranges(local_duration, args.retry_seconds, retry_overlap)
            ):
                retry_parts.append(
                    transcribe_piece(
                        mlx_whisper,
                        source,
                        run_dir,
                        start + local_start,
                        start + local_end,
                        f"p{index:03d}r{retry_index:02d}",
                        args.model,
                        args.language,
                        args.initial_prompt,
                    )
                )
            retry_segments = merge_chunks(retry_parts, retry_overlap)
            retry_segments, retry_score = mark_suspicious(retry_segments)
            if retry_score < item["suspicion_score"]:
                warnings.append(
                    {
                        "start": start,
                        "end": end,
                        "action": "replaced_with_shorter_chunks",
                        "first_score": item["suspicion_score"],
                        "retry_score": retry_score,
                    }
                )
                item = {
                    "start": start,
                    "end": end,
                    "elapsed_seconds": sum(part["elapsed_seconds"] for part in retry_parts),
                    "suspicion_score": retry_score,
                    "segments": retry_segments,
                    "chunk_json": [part["chunk_json"] for part in retry_parts],
                }
            else:
                warnings.append(
                    {
                        "start": start,
                        "end": end,
                        "action": "kept_first_pass_but_marked_suspicious",
                        "first_score": item["suspicion_score"],
                        "retry_score": retry_score,
                    }
                )
        initial.append(item)

    segments = merge_chunks(initial, args.overlap_seconds)
    elapsed = time.perf_counter() - all_started
    payload = {
        "metadata": {
            "source": str(source),
            "backend": "mlx-whisper",
            "model": args.model,
            "language": args.language,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "realtime_factor": elapsed / duration if duration else None,
            "strategy": "overlapped_chunks_with_suspicion_retry",
            "chunk_seconds": args.chunk_seconds,
            "overlap_seconds": args.overlap_seconds,
            "speaker_labels": False,
            "warnings": warnings,
            "temporary_run_dir": str(run_dir),
        },
        "text": "".join(segment["text"] for segment in segments),
        "segments": segments,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RUN_DIR={run_dir}")
    print(f"OUTPUT={output}")
    print(f"音频时长：{duration / 60:.2f} 分钟")
    print(f"处理耗时：{elapsed / 60:.2f} 分钟")
    print(f"实时系数：{elapsed / duration:.3f}" if duration else "实时系数：未知")
    print(f"可疑分片：{len(warnings)}")
    cleanup_state["completed"] = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
