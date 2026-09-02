#!/usr/bin/env python3
"""Perform a real local-runtime and media preflight before transcription."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transcription_utils import DEFAULT_MODEL, apple_preflight, probe_media


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="检查 MLX、Metal、本地模型、磁盘和输入音频。")
    result.add_argument("input", nargs="?", help="可选的音频或视频文件")
    result.add_argument("--model", default=DEFAULT_MODEL, help="本地模型目录或 Hugging Face 仓库")
    result.add_argument("--no-metal", action="store_true", help="仅做静态检查，不初始化 Metal")
    result.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return result


def main() -> int:
    args = parser().parse_args()
    report = apple_preflight(args.model, require_metal=not args.no_metal)
    if args.input:
        source = Path(args.input).expanduser().resolve()
        if not source.is_file():
            report["errors"].append(f"找不到输入文件：{source}")
        elif not report["ffprobe"]:
            report["errors"].append("缺少 ffprobe，无法检查媒体")
        else:
            try:
                report["media"] = probe_media(source)
            except Exception as error:
                report["errors"].append(f"媒体检查失败：{error}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"平台：{report['platform']} / {report['machine']}")
        print(f"Python：{report['python']}")
        print(f"MLX Whisper：{'可用' if report['mlx_whisper'] else '不可用'}")
        print(f"Metal：{report['metal_ok'] if report['metal_ok'] is not None else '未检查'}")
        print(f"模型：{report['model']}")
        if report.get("media"):
            media = report["media"]
            stream = media["audio_streams"][0]
            print(
                f"媒体：{media['duration_seconds'] / 60:.2f} 分钟 / "
                f"{stream.get('codec_name')} / {stream.get('channels')} 声道 / {stream.get('sample_rate')} Hz"
            )
        for warning in report["warnings"]:
            print(f"警告：{warning}")
        for error in report["errors"]:
            print(f"错误：{error}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
