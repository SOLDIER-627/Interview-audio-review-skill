#!/usr/bin/env python3
"""VAD-aware, resumable local transcription for long Apple-silicon recordings."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transcription_utils import (
    DEFAULT_MODEL,
    MARKER,
    RUN_PREFIX,
    apple_preflight,
    detect_silences,
    intersect_intervals,
    invert_intervals,
    mark_suspicious,
    merge_intervals,
    postprocess_segments,
    probe_media,
    quality_score,
    select_representative_window,
    suspicious_ranges,
)


CHECKPOINT = "checkpoint.json"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="带 VAD、局部复核和断点续转的长面试录音转写。")
    result.add_argument("input", help="输入音频或视频文件")
    result.add_argument("--output", help="合并后的临时 JSON；默认写入本次临时目录")
    run_group = result.add_mutually_exclusive_group()
    run_group.add_argument("--run-dir", help="新的临时目录；必须为空且名称符合安全规则")
    run_group.add_argument("--resume", help="继续先前中断的本次临时目录")
    result.add_argument("--model", default=DEFAULT_MODEL, help="本地模型目录或 Hugging Face 仓库")
    result.add_argument("--language", default="zh", help="主要语言；auto 表示自动检测")
    result.add_argument("--initial-prompt", help="姓名、公司名和技术术语提示")
    result.add_argument("--chunk-seconds", type=float, default=600.0, help="父分片秒数，默认 600")
    result.add_argument("--overlap-seconds", type=float, default=10.0, help="父分片重叠秒数，默认 10")
    result.add_argument("--retry-padding-seconds", type=float, default=8.0, help="异常窗口前后扩展秒数")
    result.add_argument("--retry-max-seconds", type=float, default=120.0, help="单个局部复核窗口最大秒数")
    result.add_argument("--no-vad", action="store_true", help="关闭 Apple 路线的 FFmpeg 静音过滤")
    result.add_argument("--vad-noise-db", type=float, default=-35.0, help="静音阈值，默认 -35 dB")
    result.add_argument("--vad-min-silence-seconds", type=float, default=1.5, help="静音最短时长")
    result.add_argument("--vad-padding-seconds", type=float, default=0.25, help="语音窗口边缘保留时长")
    result.add_argument("--vad-merge-gap-seconds", type=float, default=3.0, help="合并相邻语音窗口的最大间隔")
    result.add_argument("--preflight-sample", action="store_true", help="只转写自动选择的代表性片段")
    result.add_argument("--sample-seconds", type=float, default=300.0, help="代表性片段长度，默认 300 秒")
    result.add_argument("--sample-start", type=float, help="手工指定代表性片段开始秒数")
    result.add_argument("--force", action="store_true", help="允许覆盖最终临时输出 JSON")
    return result


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


def split_window(
    start: float,
    end: float,
    maximum: float,
    segments: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float]]:
    if maximum <= 0 or end - start <= maximum:
        return [(start, end)]
    result = []
    cursor = start
    boundaries = sorted(
        {
            float(segment.get("end") or 0)
            for segment in (segments or [])
            if start < float(segment.get("end") or 0) < end
        }
    )
    while cursor < end:
        target = min(end, cursor + maximum)
        available = [value for value in boundaries if cursor < value <= target]
        if not boundaries:
            right = target
        elif available:
            right = max(available)
        else:
            later = [value for value in boundaries if value > target]
            right = min(later) if later else end
        if right <= cursor:
            right = target
        result.append((cursor, right))
        cursor = right
    return result


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


def transcribe_window(
    mlx_whisper: Any,
    source: Path,
    run_dir: Path,
    start: float,
    end: float,
    index: str,
    model: str,
    language: str,
    prompt: str | None,
    silence_intervals: list[tuple[float, float]],
) -> dict[str, Any]:
    audio_path = run_dir / f"window-{index}-{int(start):06d}-{int(end):06d}{source.suffix}"
    extract(source, audio_path, start, end)
    started = time.perf_counter()
    raw = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model,
        language=None if language.lower() == "auto" else language,
        task="transcribe",
        word_timestamps=False,
        initial_prompt=prompt,
        verbose=None,
    )
    elapsed = time.perf_counter() - started
    normalized = []
    for position, segment in enumerate(raw.get("segments") or []):
        segment_start = min(end, max(start, float(segment.get("start") or 0.0) + start))
        segment_end = min(end, max(segment_start, float(segment.get("end") or 0.0) + start))
        normalized.append(
            {
                "id": position,
                "start": segment_start,
                "end": segment_end,
                "speaker": None,
                "speaker_confidence": None,
                "text": str(segment.get("text") or "").strip(),
                "avg_logprob": float(segment["avg_logprob"]) if segment.get("avg_logprob") is not None else None,
                "no_speech_prob": float(segment["no_speech_prob"])
                if segment.get("no_speech_prob") is not None
                else None,
                "source_chunk": audio_path.name,
            }
        )
    marked, score = mark_suspicious(normalized, silence_intervals)
    window_json = run_dir / f"window-{index}.json"
    window_json.write_text(
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
        "window_json": window_json.name,
    }


def replace_range(
    segments: list[dict[str, Any]], replacement: list[dict[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    kept = [
        segment
        for segment in segments
        if float(segment.get("end") or 0) <= start or float(segment.get("start") or 0) >= end
    ]
    kept.extend(replacement)
    return sorted(kept, key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0)))


def mark_unreliable(segments: list[dict[str, Any]], start: float, end: float) -> None:
    for segment in segments:
        if float(segment.get("end") or 0) <= start or float(segment.get("start") or 0) >= end:
            continue
        flags = list(segment.get("quality_flags") or [])
        if "unreliable_transcription" not in flags:
            flags.append("unreliable_transcription")
        segment["quality_flags"] = flags


def transcribe_parent(
    mlx_whisper: Any,
    source: Path,
    run_dir: Path,
    start: float,
    end: float,
    index: int,
    speech_intervals: list[tuple[float, float]],
    silence_intervals: list[tuple[float, float]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    windows = intersect_intervals(speech_intervals, start, end) if not args.no_vad else [(start, end)]
    initial_segments: list[dict[str, Any]] = []
    elapsed = 0.0
    window_files: list[str] = []
    for window_index, (left, right) in enumerate(windows):
        item = transcribe_window(
            mlx_whisper,
            source,
            run_dir,
            left,
            right,
            f"p{index:03d}w{window_index:03d}",
            args.model,
            args.language,
            args.initial_prompt,
            silence_intervals,
        )
        elapsed += item["elapsed_seconds"]
        initial_segments.extend(item["segments"])
        window_files.append(item["window_json"])

    initial_segments, _ = mark_suspicious(initial_segments, silence_intervals)
    warnings: list[dict[str, Any]] = []
    retry_counter = 0
    bad_ranges = suspicious_ranges(
        initial_segments,
        start,
        end,
        padding=args.retry_padding_seconds,
    )
    for bad_start, bad_end in bad_ranges:
        overlapping = [
            segment
            for segment in initial_segments
            if float(segment.get("end") or 0) > bad_start and float(segment.get("start") or 0) < bad_end
        ]
        if overlapping:
            bad_start = max(start, min(bad_start, min(float(item["start"]) for item in overlapping)))
            bad_end = min(end, max(bad_end, max(float(item["end"]) for item in overlapping)))
        for retry_start, retry_end in split_window(
            bad_start, bad_end, args.retry_max_seconds, overlapping
        ):
            original = [
                segment
                for segment in initial_segments
                if float(segment.get("end") or 0) > retry_start
                and float(segment.get("start") or 0) < retry_end
            ]
            first_score = quality_score(original, silence_intervals)
            retry = transcribe_window(
                mlx_whisper,
                source,
                run_dir,
                retry_start,
                retry_end,
                f"p{index:03d}r{retry_counter:03d}",
                args.model,
                args.language,
                args.initial_prompt,
                silence_intervals,
            )
            retry_counter += 1
            elapsed += retry["elapsed_seconds"]
            retry_score = quality_score(retry["segments"], silence_intervals)
            use_retry = retry_score + 0.5 < first_score
            chosen = retry["segments"] if use_retry else original
            if use_retry:
                initial_segments = replace_range(initial_segments, chosen, retry_start, retry_end)
            unresolved = min(first_score, retry_score) >= max(3.0, (retry_end - retry_start) * 0.08)
            if unresolved:
                mark_unreliable(initial_segments, retry_start, retry_end)
            warnings.append(
                {
                    "start": retry_start,
                    "end": retry_end,
                    "action": "replaced_with_local_retry" if use_retry else "kept_first_pass",
                    "first_score": first_score,
                    "retry_score": retry_score,
                    "unresolved": unresolved,
                }
            )

    processed, dropped = postprocess_segments(initial_segments)
    parent = {
        "start": start,
        "end": end,
        "elapsed_seconds": elapsed,
        "suspicion_score": quality_score(processed, silence_intervals),
        "segments": processed,
        "warnings": warnings,
        "dropped_segments": dropped,
        "window_json": window_files,
    }
    parent_path = run_dir / f"parent-p{index:03d}.json"
    parent_path.write_text(json.dumps(parent, ensure_ascii=False, indent=2), encoding="utf-8")
    return parent


def merge_parents(parents: list[dict[str, Any]], overlap: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    for index, parent in enumerate(parents):
        lower = parent["start"] if index == 0 else parent["start"] + overlap / 2
        upper = parent["end"] if index == len(parents) - 1 else parents[index + 1]["start"] + overlap / 2
        for segment in parent["segments"]:
            midpoint = (float(segment["start"]) + float(segment["end"])) / 2
            if lower <= midpoint < upper:
                merged.append(dict(segment))
    return postprocess_segments(merged)


def runtime_parameters(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "model": args.model,
        "language": args.language,
        "initial_prompt": args.initial_prompt,
        "chunk_seconds": args.chunk_seconds,
        "overlap_seconds": args.overlap_seconds,
        "retry_padding_seconds": args.retry_padding_seconds,
        "retry_max_seconds": args.retry_max_seconds,
        "vad": not args.no_vad,
        "vad_noise_db": args.vad_noise_db,
        "vad_min_silence_seconds": args.vad_min_silence_seconds,
        "vad_padding_seconds": args.vad_padding_seconds,
        "vad_merge_gap_seconds": args.vad_merge_gap_seconds,
        "output": str(Path(args.output).expanduser().resolve()) if args.output else None,
    }


def create_run_dir(source: Path, args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if args.resume:
        run_dir = Path(args.resume).expanduser().resolve()
        marker_path = run_dir / MARKER
        if not run_dir.is_dir() or not marker_path.is_file():
            raise SystemExit("无法续跑：临时目录不存在或缺少安全标记")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("mode") != "full":
            raise SystemExit("无法续跑：代表性样本运行不能作为完整转写检查点")
        if marker.get("source") != str(source):
            raise SystemExit("无法续跑：源文件路径与检查点不一致")
        stat = source.stat()
        if marker.get("source_size") != stat.st_size or marker.get("source_mtime_ns") != stat.st_mtime_ns:
            raise SystemExit("无法续跑：源文件在上次运行后发生变化")
        if marker.get("parameters") != runtime_parameters(args):
            raise SystemExit("无法续跑：模型、分片、VAD 或提示词参数发生变化")
        return run_dir, marker

    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        if run_dir.exists() and any(run_dir.iterdir()):
            raise SystemExit("拒绝使用：指定的临时目录不是空目录")
        run_dir.mkdir(parents=True, exist_ok=True)
        if not run_dir.name.startswith(RUN_PREFIX):
            raise SystemExit(f"临时目录名称必须以 {RUN_PREFIX} 开头")
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=RUN_PREFIX)).resolve()
    stat = source.stat()
    marker = {
        "source": str(source),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "mode": "sample" if args.preflight_sample else "full",
        "parameters": runtime_parameters(args),
    }
    (run_dir / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir, marker


def write_checkpoint(run_dir: Path, completed: list[int], total: int) -> None:
    (run_dir / CHECKPOINT).write_text(
        json.dumps(
            {
                "completed_parent_indices": completed,
                "total_parent_count": total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_speech_map(source: Path, duration: float, args: argparse.Namespace) -> tuple[list, list]:
    if args.no_vad:
        return [], [(0.0, duration)]
    silences = detect_silences(source, duration, args.vad_noise_db, args.vad_min_silence_seconds)
    speech = invert_intervals(silences, duration, args.vad_padding_seconds)
    speech = merge_intervals(speech, gap=args.vad_merge_gap_seconds)
    return silences, speech


def run_sample(
    mlx_whisper: Any,
    source: Path,
    run_dir: Path,
    media: dict[str, Any],
    silences: list[tuple[float, float]],
    speech: list[tuple[float, float]],
    args: argparse.Namespace,
) -> int:
    start, end = select_representative_window(
        media["duration_seconds"], speech, args.sample_seconds, args.sample_start
    )
    parent = transcribe_parent(mlx_whisper, source, run_dir, start, end, 0, speech, silences, args)
    payload = {
        "metadata": {
            "source": str(source),
            "backend": "mlx-whisper",
            "model": args.model,
            "language": args.language,
            "duration_seconds": end - start,
            "sample_start": start,
            "sample_end": end,
            "speaker_labels": False,
            "warnings": parent["warnings"],
            "temporary_run_dir": str(run_dir),
        },
        "text": "\n".join(segment["text"] for segment in parent["segments"]),
        "segments": parent["segments"],
    }
    output = run_dir / "preflight-sample.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output}", flush=True)
    print(f"代表性范围：{start:.2f}–{end:.2f} 秒", flush=True)
    print(f"可疑局部窗口：{len(parent['warnings'])}", flush=True)
    return 0


def main() -> int:
    args = parser().parse_args()
    if min(args.chunk_seconds, args.sample_seconds, args.retry_max_seconds, args.vad_min_silence_seconds) <= 0:
        raise SystemExit("分片、样本、复核和 VAD 时长参数必须大于 0")
    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"找不到输入文件：{source}")
    report = apple_preflight(args.model, require_metal=True)
    if report["errors"]:
        raise SystemExit("运行前检查失败：" + "；".join(report["errors"]))
    media = probe_media(source)
    run_dir, _ = create_run_dir(source, args)
    print(f"RUN_DIR={run_dir}", flush=True)
    if args.preflight_sample:
        print("这是代表性样本运行；核对后使用 cleanup_run.py --sample 清理本次目录。", flush=True)
    else:
        print("如运行中断，可使用同样参数加 --resume 继续。", flush=True)

    silences, speech = load_speech_map(source, media["duration_seconds"], args)
    (run_dir / "vad-map.json").write_text(
        json.dumps(
            {
                "enabled": not args.no_vad,
                "noise_db": args.vad_noise_db,
                "min_silence_seconds": args.vad_min_silence_seconds,
                "silence_intervals": silences,
                "speech_intervals": speech,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    import mlx_whisper

    if args.preflight_sample:
        return run_sample(mlx_whisper, source, run_dir, media, silences, speech, args)

    output = Path(args.output).expanduser().resolve() if args.output else run_dir / "transcript.merged.json"
    if output.exists() and not args.force and not args.resume:
        raise SystemExit(f"临时输出已存在：{output}；如需覆盖请使用 --force")
    parent_ranges = ranges(media["duration_seconds"], args.chunk_seconds, args.overlap_seconds)
    parents: list[dict[str, Any]] = []
    completed: list[int] = []
    all_started = time.perf_counter()
    for index, (start, end) in enumerate(parent_ranges):
        parent_path = run_dir / f"parent-p{index:03d}.json"
        if args.resume and parent_path.is_file():
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            print(f"已恢复父分片 {index + 1}/{len(parent_ranges)}", flush=True)
        else:
            parent = transcribe_parent(mlx_whisper, source, run_dir, start, end, index, speech, silences, args)
            print(
                f"已完成父分片 {index + 1}/{len(parent_ranges)}；局部复核 {len(parent['warnings'])} 个",
                flush=True,
            )
        parents.append(parent)
        completed.append(index)
        write_checkpoint(run_dir, completed, len(parent_ranges))

    segments, dropped = merge_parents(parents, args.overlap_seconds)
    warnings = [warning for parent in parents for warning in parent.get("warnings", [])]
    wall_elapsed = time.perf_counter() - all_started
    processing_elapsed = sum(float(parent.get("elapsed_seconds") or 0.0) for parent in parents)
    payload = {
        "metadata": {
            "source": str(source),
            "backend": "mlx-whisper",
            "model": args.model,
            "language": args.language,
            "duration_seconds": media["duration_seconds"],
            "elapsed_seconds": processing_elapsed,
            "current_run_wall_seconds": wall_elapsed,
            "realtime_factor": processing_elapsed / media["duration_seconds"] if media["duration_seconds"] else None,
            "strategy": "vad_parent_chunks_with_targeted_retry_and_resume",
            "chunk_seconds": args.chunk_seconds,
            "overlap_seconds": args.overlap_seconds,
            "vad_filter": not args.no_vad,
            "vad_noise_db": args.vad_noise_db,
            "vad_min_silence_seconds": args.vad_min_silence_seconds,
            "speaker_labels": False,
            "warnings": warnings,
            "dropped_segments": dropped,
            "media": media,
            "temporary_run_dir": str(run_dir),
        },
        "text": "\n".join(segment["text"] for segment in segments),
        "segments": segments,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OUTPUT={output}", flush=True)
    print(f"音频时长：{media['duration_seconds'] / 60:.2f} 分钟", flush=True)
    print(
        f"累计转写耗时：{processing_elapsed / 60:.2f} 分钟；本次运行：{wall_elapsed / 60:.2f} 分钟",
        flush=True,
    )
    print(
        f"局部复核：{len(warnings)}；仍不可靠：{sum(bool(item['unresolved']) for item in warnings)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
