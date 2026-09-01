# 本地安装与运行

默认使用本地路线。首次安装依赖和下载模型需要联网；模型缓存后可离线转写。不要把虚拟环境、模型、录音、Token 或转写结果提交到版本库。

## 平台选择

| 环境 | 后端 | 推荐配置 |
|---|---|---|
| Apple 芯片 Mac | `mlx-whisper` | `whisper-large-v3-turbo` |
| Intel Mac | `faster-whisper` | CPU `small` + INT8 |
| Windows CPU | `faster-whisper` | `small` + INT8 |
| Windows NVIDIA GPU | `faster-whisper` | `turbo` + FP16 |

建议使用 Python 3.11 或 3.12。根目录 `requirements.txt` 带有平台条件，会安装当前平台所需后端。

## macOS：Apple 芯片

```bash
brew install python ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
hf download mlx-community/whisper-large-v3-turbo \
  --local-dir models/whisper-large-v3-turbo
python interview-audio-review/scripts/transcribe_local.py --check
```

模型目录默认位于仓库根目录：

```text
models/whisper-large-v3-turbo/
```

脚本会从自身位置逐级向上查找该相对目录。需要使用其他目录时，通过 `--model "<模型目录>"` 显式传入；文档和代码中不得写入某个使用者的绝对路径。

十五分钟以上录音使用：

```bash
python interview-audio-review/scripts/transcribe_chunked.py \
  "/path/to/interview.m4a" \
  --language zh \
  --initial-prompt "公司名、岗位名、项目名、专业术语"
```

脚本会创建带安全标记的系统临时目录，输出 `RUN_DIR` 和合并 JSON 路径。最终报告完成后，由 `cleanup_run.py` 删除该目录。

十五分钟及以下可使用 `transcribe_local.py`，但输出也要放进本次临时目录。

## macOS：Intel 芯片

Intel Mac 使用 `faster-whisper`：

```bash
brew install python
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python interview-audio-review/scripts/transcribe_faster_whisper.py --check
python interview-audio-review/scripts/transcribe_faster_whisper.py \
  "/path/to/interview.m4a" \
  --language zh
```

未指定 `--output` 时，脚本会在系统临时目录创建可安全清理的运行目录。CPU 默认使用 `small` + INT8；可用 `--model medium` 或 `--model turbo` 提高准确率，但会增加耗时和内存。

## Windows：CPU

在 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python interview-audio-review\scripts\transcribe_faster_whisper.py --check
python interview-audio-review\scripts\transcribe_faster_whisper.py `
  "D:\recordings\interview.m4a" `
  --language zh
```

`faster-whisper` 使用 PyAV 解码音频，通常不要求系统单独安装 FFmpeg。若需要手工裁剪、转码或使用 `ffprobe` 检查媒体，再安装 FFmpeg。

模型在第一次运行时自动下载到 Hugging Face 缓存。CPU 默认 `small` + INT8，是兼顾资源占用和识别效果的设置。

## Windows：NVIDIA GPU（可选）

GPU 路线需要与当前 CTranslate2 兼容的 NVIDIA 运行库。以 `faster-whisper` 官方文档为准；当前主线要求 CUDA 12 和 cuDNN 9。

```powershell
python interview-audio-review\scripts\transcribe_faster_whisper.py `
  "D:\recordings\interview.m4a" `
  --language zh `
  --device cuda `
  --model turbo `
  --compute-type float16
```

默认 `--device auto`。检测到 CUDA 但初始化失败时，脚本回退 CPU；显式指定 `--device cuda` 时失败应直接报告，不静默改变用户选择。

## 代表性片段检查

首次处理长录音时，选择包含双方对话和技术术语的代表性五分钟片段完成一次转写，检查术语识别、断句、重复文本、角色区分和本机运行情况。

处理速度明显不适合当前任务时，按顺序处理：

1. 关闭逐词时间戳；
2. 确认当前平台使用正确后端；
3. Windows/Intel Mac CPU 改用 `small`；
4. Apple 芯片改用较小的 MLX 模型；
5. 复核问答可读性和技术术语，避免为缩短处理时间牺牲关键信息。

## 可选说话人分离

只有角色推断明显失败时再安装：

```bash
python -m pip install pyannote.audio
```

使用模型可能需要 Hugging Face 账户、接受模型条款和只读 Token。Token 只能保存在本地环境，不得写入 Skill、脚本、报告或版本库。

## 隐私边界

- 未经用户明确授权，不上传录音；
- Token、录音、转写结果和个人资料不得写入 Skill、报告或版本库；
- 使用外部服务前，必须确认用户授权范围和隐私要求。

## 清理

报告验证完成后运行：

macOS：

```bash
python interview-audio-review/scripts/cleanup_run.py \
  --run-dir "/tmp/interview-audio-review-本次随机目录" \
  --review "/path/to/interview.review.md"
```

Windows PowerShell：

```powershell
python interview-audio-review\scripts\cleanup_run.py `
  --run-dir "$env:TEMP\interview-audio-review-本次随机目录" `
  --review "D:\recordings\interview.review.md"
```

若失败且没有报告，改用 `--failed`。清理脚本只接受系统临时目录中、名称和标记都符合规则的本次目录，不删除原录音、模型、最终报告或其他用户文件。
