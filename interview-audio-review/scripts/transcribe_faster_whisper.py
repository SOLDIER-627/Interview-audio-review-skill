#!/usr/bin/env python3
"""使用 faster-whisper 在 Windows 或 Intel Mac 上生成标准化转写 JSON。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transcription_utils import mark_suspicious, postprocess_segments, probe_media


RUN_PREFIX = "interview-audio-review-"
MARKER = ".interview-audio-review-run.json"


def cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def check_environment() -> int:
    has_faster_whisper = importlib.util.find_spec("faster_whisper") is not None
    cuda_count = cuda_device_count() if has_faster_whisper else 0

    print(f"操作系统: {platform.system()} {platform.release()}")
    print(f"系统架构: {platform.machine()}")
    print(f"faster-whisper: {'已安装' if has_faster_whisper else '未安装'}")
    print(f"可见 CUDA 设备: {cuda_count}")
    if not has_faster_whisper:
        print(
            "请先运行：python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    return 0


def optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 faster-whisper 本地转写面试录音，并输出标准化 JSON。"
    )
    parser.add_argument("input", nargs="?", help="输入音频或视频文件")
    parser.add_argument(
        "--output",
        help="输出 JSON 文件；省略时在系统临时目录创建本次运行目录",
    )
    parser.add_argument(
        "--model",
        help="模型名称或本地目录；自动模式下 CUDA 默认 turbo，CPU 默认 small",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="主要语言代码；使用 auto 自动检测",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="运行设备；默认自动检测 CUDA，不可用时使用 CPU",
    )
    parser.add_argument(
        "--compute-type",
        help="计算精度；默认 CUDA 使用 float16，CPU 使用 int8",
    )
    parser.add_argument("--beam-size", type=int, default=5, help="搜索宽度；默认 5")
    parser.add_argument(
        "--vad-min-silence-ms",
        type=int,
        default=500,
        help="VAD 判定静音的最短毫秒数；默认 500",
    )
    parser.add_argument(
        "--word-timestamps",
        action="store_true",
        help="生成逐词时间戳；会增加耗时，默认关闭",
    )
    parser.add_argument(
        "--initial-prompt",
        help="可选的姓名、公司名和技术术语提示；不能用于补写未说内容",
    )
    parser.add_argument("--force", action="store_true", help="允许覆盖已有输出")
    parser.add_argument("--check", action="store_true", help="只检查本地依赖")
    return parser


def choose_runtime(args: argparse.Namespace) -> tuple[str, str, str]:
    device = args.device
    if device == "auto":
        device = "cuda" if cuda_device_count() > 0 else "cpu"
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")
    model_name = args.model or ("turbo" if device == "cuda" else "small")
    return device, compute_type, model_name


def load_model_with_fallback(
    args: argparse.Namespace,
) -> tuple[Any, str, str, str, bool]:
    from faster_whisper import WhisperModel

    device, compute_type, model_name = choose_runtime(args)
    used_fallback = False
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:
        if args.device != "auto" or device != "cuda":
            raise
        print(f"警告：CUDA 初始化失败，将回退到 CPU：{exc}", file=sys.stderr)
        device = "cpu"
        compute_type = "int8"
        model_name = args.model or "small"
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        used_fallback = True
    return model, device, compute_type, model_name, used_fallback


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        return check_environment()
    if not args.input:
        print("错误：必须提供输入文件。", file=sys.stderr)
        return 2
    if check_environment() != 0:
        return 1
    if args.beam_size < 1 or args.vad_min_silence_ms < 0:
        print("错误：beam-size 必须大于 0，VAD 静音时长不能为负数。", file=sys.stderr)
        return 2

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        print(f"错误：找不到输入文件：{input_path}", file=sys.stderr)
        return 2
    try:
        media = probe_media(input_path) if platform.system() == "Darwin" else None
    except Exception as error:
        print(f"错误：媒体检查失败：{error}", file=sys.stderr)
        return 2

    model, device, compute_type, model_name, used_fallback = load_model_with_fallback(args)
    run_dir: Path | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        if output_path.exists() and not args.force:
            print(
                f"错误：输出已存在：{output_path}；如需覆盖请使用 --force。",
                file=sys.stderr,
            )
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=RUN_PREFIX)).resolve()
        output_path = run_dir / "raw-transcript.json"
        marker = {
            "source": str(input_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "backend": "faster-whisper",
        }
        (run_dir / MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    language = None if args.language.lower() == "auto" else args.language

    started = time.perf_counter()
    segment_stream, info = model.transcribe(
        str(input_path),
        language=language,
        task="transcribe",
        beam_size=args.beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": args.vad_min_silence_ms},
        word_timestamps=args.word_timestamps,
        initial_prompt=args.initial_prompt,
    )

    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(segment_stream):
        text = str(segment.text or "").strip()
        normalized.append(
            {
                "id": getattr(segment, "id", index),
                "start": optional_float(segment.start),
                "end": optional_float(segment.end),
                "speaker": None,
                "speaker_confidence": None,
                "text": text,
                "avg_logprob": optional_float(getattr(segment, "avg_logprob", None)),
                "no_speech_prob": optional_float(getattr(segment, "no_speech_prob", None)),
            }
        )
    normalized, suspicion_score = mark_suspicious(normalized)
    normalized, dropped_segments = postprocess_segments(normalized)
    elapsed = time.perf_counter() - started
    duration = optional_float(getattr(info, "duration", None))
    if not duration:
        duration = max((item["end"] or 0.0 for item in normalized), default=0.0)
    realtime_factor = elapsed / duration if duration > 0 else None

    payload = {
        "metadata": {
            "source": str(input_path),
            "backend": "faster-whisper",
            "model": model_name,
            "language": getattr(info, "language", None) or language,
            "language_probability": optional_float(getattr(info, "language_probability", None)),
            "device": device,
            "compute_type": compute_type,
            "cuda_fallback_to_cpu": used_fallback,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "realtime_factor": realtime_factor,
            "beam_size": args.beam_size,
            "vad_filter": True,
            "vad_min_silence_ms": args.vad_min_silence_ms,
            "word_timestamps": args.word_timestamps,
            "initial_prompt_used": bool(args.initial_prompt),
            "speaker_labels": False,
            "suspicion_score": suspicion_score,
            "dropped_segments": dropped_segments,
            "media": media,
        },
        "text": "\n".join(segment["text"] for segment in normalized),
        "segments": normalized,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if run_dir is not None:
        print(f"RUN_DIR：{run_dir}")
    print(f"输出：{output_path}")
    print(f"运行设备：{device} / {compute_type}")
    print(f"模型：{model_name}")
    print(f"音频时长：{duration / 60:.2f} 分钟")
    print(f"处理耗时：{elapsed / 60:.2f} 分钟")
    if realtime_factor is not None:
        print(f"实时系数：{realtime_factor:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
