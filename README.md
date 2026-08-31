# 面试录音复盘 Skill

一个可在本地运行的 Codex Skill，用于把面试录音整理成可核对、可练习的中文复盘报告。

它会完成：语音转写 → 转写纠错 → 问题/追问/回答还原 → 逐题评价 → 推荐回答 → 整场面试总结。默认只保留最终的 `review.md`，不会把录音、模型、原始转写或临时分片提交到仓库。

## 适用场景

- 秋招、春招、社招、实习和模拟面试复盘；
- 技术面、项目面、业务面、HR 面；
- 中文为主、夹杂英文技术术语的双人面试；
- 已有录音、视频或文字转写稿的问答整理。

不适用于未经参与者授权的秘密录音、声纹身份确认，或要求虚构候选人经历的场景。

## 最终产出

输入一段录音，例如：

```text
interview.m4a
```

完整流程结束后只新增：

```text
interview.review.md
```

报告包含：

- 处理方式、模型、耗时、费用和证据限制；
- 带时间戳的问题、追问和候选人真实回答；
- 高置信度转写纠错及不确定片段；
- 切题程度、表达结构、正确性与深度、证据与影响、沟通表现评分；
- 每道题做得好的地方、潜在问题和推荐回答；
- 整场面试诊断、三个优先改进项和练习建议。

## 支持的平台

| 平台 | 默认转写后端 | 默认模型 | 说明 |
|---|---|---|---|
| macOS（Apple 芯片） | `mlx-whisper` | `whisper-large-v3-turbo` | 速度和中英混合识别效果较均衡 |
| macOS（Intel） | `faster-whisper` | `small`（CPU） | 可运行，但速度取决于 CPU |
| Windows（普通 CPU） | `faster-whisper` | `small` + INT8 | 无需独立安装系统 FFmpeg |
| Windows（NVIDIA GPU） | `faster-whisper` | `turbo` + FP16 | 需正确安装 CUDA 12 和 cuDNN 9 |

两条路线都在本机转写，不调用按分钟收费的语音识别 API。首次安装依赖和下载模型需要网络，之后可使用本地缓存。

## 目录结构

```text
interview-audio-review-skill/
├── .gitignore
├── README.md
├── requirements.txt
└── interview-audio-review/
    ├── SKILL.md
    ├── agents/
    ├── references/
    └── scripts/
```

仓库不包含 `.venv`、模型、录音、转写结果或个人资料；这些内容均已加入 `.gitignore`。

## macOS 安装与运行

### 1. 安装 Python 和 FFmpeg

```bash
brew install python ffmpeg
```

建议使用 Python 3.11 或 3.12。创建独立虚拟环境：

```bash
cd interview-audio-review-skill
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` 会根据机器架构选择依赖：Apple 芯片安装 `mlx-whisper`，Intel Mac 安装 `faster-whisper`。

### 2. Apple 芯片下载模型

推荐把模型放在仓库根目录的 `models/`，该目录不会进入 Git：

```bash
hf download mlx-community/whisper-large-v3-turbo \
  --local-dir models/whisper-large-v3-turbo
```

检查环境：

```bash
python interview-audio-review/scripts/transcribe_local.py --check
```

长录音的独立转写测试：

```bash
python interview-audio-review/scripts/transcribe_chunked.py \
  "/path/to/interview.m4a" \
  --language zh \
  --initial-prompt "公司名、岗位名、项目名、Kubernetes、Redis"
```

### 3. Intel Mac 运行

Intel Mac 使用跨平台脚本；模型会在第一次运行时自动下载到 Hugging Face 本地缓存：

```bash
python interview-audio-review/scripts/transcribe_faster_whisper.py --check
python interview-audio-review/scripts/transcribe_faster_whisper.py \
  "/path/to/interview.m4a" \
  --output "/tmp/interview.raw-transcript.json" \
  --language zh
```

## Windows 安装与运行

以下命令在 PowerShell 中执行。

### 1. 安装 Python

建议从 [Python 官网](https://www.python.org/downloads/windows/) 安装 Python 3.11 或 3.12，并勾选 **Add Python to PATH**。也可以使用 Windows 包管理器：

```powershell
winget install --exact --id Python.Python.3.12
```

`faster-whisper` 通过 PyAV 解码音频，一般无需单独安装系统 FFmpeg。若还要手工裁剪、转码或检查音频，可选安装：

```powershell
winget install --exact --id Gyan.FFmpeg
```

### 2. 创建虚拟环境并安装依赖

```powershell
cd interview-audio-review-skill
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

检查环境：

```powershell
python interview-audio-review\scripts\transcribe_faster_whisper.py --check
```

### 3. CPU 运行（默认、无需额外配置）

```powershell
python interview-audio-review\scripts\transcribe_faster_whisper.py `
  "D:\recordings\interview.m4a" `
  --output "$env:TEMP\interview.raw-transcript.json" `
  --language zh
```

CPU 默认使用 `small` 模型和 INT8，以兼顾速度与内存。若设备性能充足并更看重准确率，可添加 `--model medium` 或 `--model turbo`，但耗时和内存占用会增加。

### 4. NVIDIA GPU 运行（可选）

安装与 `faster-whisper` 当前版本兼容的 CUDA 12 和 cuDNN 9，并确保相关动态库在 `PATH` 中。然后执行：

```powershell
python interview-audio-review\scripts\transcribe_faster_whisper.py `
  "D:\recordings\interview.m4a" `
  --output "$env:TEMP\interview.raw-transcript.json" `
  --language zh `
  --device cuda `
  --model turbo `
  --compute-type float16
```

GPU 配置以 [`faster-whisper` 官方说明](https://github.com/SYSTRAN/faster-whisper#gpu)为准。若使用 `--device auto` 且 GPU 环境不可用，脚本会自动回退到 CPU。

## 让 Codex 使用这个 Skill

最简单的方式是在 Codex 中直接提供 Skill 目录和录音路径：

```text
请使用 interview-audio-review Skill 完整复盘这段面试录音。
Skill 目录：<仓库路径>/interview-audio-review
录音：<录音文件路径>
要求本地处理，完成后只保留 review.md。
```

也可以安装到个人 Skill 目录。

macOS：

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/interview-audio-review" ~/.codex/skills/interview-audio-review
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills"
Copy-Item ".\interview-audio-review" `
  "$env:USERPROFILE\.codex\skills\interview-audio-review" `
  -Recurse
```

如果目标目录已经存在，应先确认内容，不要直接覆盖。复制安装后，仓库更新不会自动同步，需要重新复制。

## Skill 的完整处理流程

1. 检查输入、平台、依赖和可用模型；
2. 选择 macOS MLX 或 Windows/Intel Mac 的 `faster-whisper` 路线；
3. 在系统临时目录完成转写、纠错、角色推断和问答还原；
4. 逐题评价候选人的真实回答，生成不虚构经历的推荐回答；
5. 验证报告结构；
6. 清理本次音频分片、JSON 和草稿，只保留最终 `review.md`。

手工运行转写脚本只会生成标准化 JSON；完整的纠错、评价、推荐答案与清理由 Codex 按 `SKILL.md` 执行。

## 模型、速度与费用

- 本地路线不产生语音识别 API 费用；会消耗本机算力、存储和首次下载流量。
- 速度取决于芯片、内存、模型大小、录音质量、重叠说话和是否发生局部重试。
- “一小时录音约二十分钟完成全流程”是较新设备热运行时的优化目标，不是固定承诺。
- Apple 芯片优先使用 MLX Turbo；Windows CPU 优先使用 `small`；Windows NVIDIA GPU 优先使用 `turbo`。
- 音质差或技术术语密集时，建议提供公司名、项目名和术语表作为识别提示。

## 隐私与事实边界

- 默认不上传录音，不调用付费转写 API；
- 原始录音不会被修改或删除；
- 听不清的内容会标记为 `[听不清]`、`[多人重叠]` 或候选词，不会静默补写；
- 推荐回答只能基于录音和用户材料中的真实经历，缺失信息用占位符提示补充；
- 使用录音前请确认符合当地法律、公司规定并获得必要授权。

## 不要提交到 GitHub

- `.venv/` 和 Python 缓存；
- `models/`、Hugging Face 缓存和模型权重；
- 面试录音、视频、简历和个人资料；
- 原始转写、纠错稿、最终复盘和临时音频片段；
- Token、`.env` 或其他凭证。

## 关键文件

- `interview-audio-review/SKILL.md`：完整工作流和安全边界；
- `interview-audio-review/scripts/transcribe_chunked.py`：Apple 芯片长录音分片转写；
- `interview-audio-review/scripts/transcribe_local.py`：Apple 芯片短录音转写；
- `interview-audio-review/scripts/transcribe_faster_whisper.py`：Windows 和 Intel Mac 本地转写；
- `interview-audio-review/scripts/cleanup_run.py`：验证最终报告后安全清理临时目录；
- `interview-audio-review/references/report-format.md`：最终报告结构。

## 许可证与第三方组件

提交 GitHub 前请为仓库选择合适的许可证，并分别遵守 `mlx-whisper`、`faster-whisper`、Whisper 模型及其他可选组件的许可证和模型条款。
