#!/usr/bin/env python3
"""使用 MLX Whisper 在 Apple 芯片 Mac 上生成标准化本地转写 JSON。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import shutil
import sys
import time
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


def check_environment() -> int:
    machine = platform.machine()
    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_mlx_whisper = importlib.util.find_spec("mlx_whisper") is not None

    print(f"系统架构: {machine}")
    print(f"ffmpeg: {'已安装' if has_ffmpeg else '未安装'}")
    print(f"mlx-whisper: {'已安装' if has_mlx_whisper else '未安装'}")

    if machine != "arm64":
        print("错误：默认 MLX 路线要求原生 arm64 Python。", file=sys.stderr)
        return 2
    if not has_ffmpeg or not has_mlx_whisper:
        print(
            "请先安装：brew install ffmpeg；python -m pip install mlx-whisper",
            file=sys.stderr,
        )
        return 1
    return 0


def optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def normalize_segments(result: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, segment in enumerate(result.get("segments") or []):
        normalized.append(
            {
                "id": segment.get("id", index),
                "start": optional_float(segment.get("start")),
                "end": optional_float(segment.get("end")),
                "speaker": None,
                "text": str(segment.get("text") or "").strip(),
                "avg_logprob": optional_float(segment.get("avg_logprob")),
                "no_speech_prob": optional_float(segment.get("no_speech_prob")),
            }
        )
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 MLX Whisper 本地转写面试录音，并输出标准化 JSON。"
    )
    parser.add_argument("input", nargs="?", help="输入音频或视频文件")
    parser.add_argument("--output", help="输出 JSON 文件")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "MLX Whisper 模型目录或 Hugging Face 仓库；默认优先使用 "
            f"{LOCAL_MODEL}，本地不存在时回退到 {HUB_MODEL}"
        ),
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="主要语言代码；使用 auto 自动检测",
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


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        return check_environment()
    if not args.input or not args.output:
        print("错误：必须同时提供输入文件和 --output。", file=sys.stderr)
        return 2
    if check_environment() != 0:
        return 1

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        print(f"错误：找不到输入文件：{input_path}", file=sys.stderr)
        return 2
    if output_path.exists() and not args.force:
        print(f"错误：输出已存在：{output_path}；如需覆盖请使用 --force。", file=sys.stderr)
        return 2
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import mlx_whisper

    language = None if args.language.lower() == "auto" else args.language
    started = time.perf_counter()
    result = mlx_whisper.transcribe(
        str(input_path),
        path_or_hf_repo=args.model,
        language=language,
        task="transcribe",
        word_timestamps=args.word_timestamps,
        initial_prompt=args.initial_prompt,
        verbose=False,
    )
    elapsed = time.perf_counter() - started
    segments = normalize_segments(result)
    duration = max((item["end"] or 0.0 for item in segments), default=0.0)
    realtime_factor = elapsed / duration if duration > 0 else None

    payload = {
        "metadata": {
            "source": str(input_path),
            "backend": "mlx-whisper",
            "model": args.model,
            "language": result.get("language") or language,
            "duration_seconds": duration,
            "elapsed_seconds": elapsed,
            "realtime_factor": realtime_factor,
            "word_timestamps": args.word_timestamps,
            "initial_prompt_used": bool(args.initial_prompt),
            "speaker_labels": False,
        },
        "text": str(result.get("text") or "").strip(),
        "segments": segments,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"输出：{output_path}")
    print(f"音频时长：{duration / 60:.2f} 分钟")
    print(f"处理耗时：{elapsed / 60:.2f} 分钟")
    if realtime_factor is not None:
        print(f"实时系数：{realtime_factor:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
