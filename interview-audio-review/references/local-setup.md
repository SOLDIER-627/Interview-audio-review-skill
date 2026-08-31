# 本地安装与性能目标

本方案适用于 Apple 芯片 Mac，默认不调用任何付费 API。首次安装和模型下载需要联网；模型缓存完成后可离线转写。

## 最小安装

需要：

- Homebrew；
- 原生 arm64 Python 3.10 或更高版本；
- `ffmpeg`；
- Python 包 `mlx-whisper`。

在仓库根目录执行。虚拟环境位于仓库根目录，不进入 `interview-audio-review/` Skill 包，也不得提交到 Git：

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

验证环境：

```bash
python interview-audio-review/scripts/transcribe_local.py --check
```

推荐在仓库根目录执行下面的命令下载模型；`models/` 已通过 `.gitignore` 排除：

```bash
hf download mlx-community/whisper-large-v3-turbo \
  --local-dir models/whisper-large-v3-turbo
```

脚本会从 Skill 目录逐级向上查找 `models/whisper-large-v3-turbo`。找不到本地模型时，脚本才会使用 `mlx-community/whisper-large-v3-turbo` 仓库标识并由 `mlx-whisper` 下载到本机缓存。模型下载时间和占用空间不计入二十分钟热运行目标。

## 默认执行：长录音

```bash
source .venv/bin/activate
python interview-audio-review/scripts/transcribe_chunked.py \
  "/path/to/interview.m4a" \
  --language zh \
  --initial-prompt "公司名、岗位名、Kubernetes、RAG、项目专有名词"
```

脚本会输出 `RUN_DIR` 和临时合并 JSON 路径。把纠错草稿和分析草稿也写进该 `RUN_DIR`，最终只把 `<录音名>.review.md` 写入录音目录。

需要显式指定已经移动的本地模型时使用：

```bash
python interview-audio-review/scripts/transcribe_chunked.py \
  "/path/to/interview.m4a" \
  --model "/Users/Admin/Desktop/intervew/models/whisper-large-v3-turbo" \
  --language zh
```

十五分钟及以下的短录音仍可使用 `transcribe_local.py`，但 `--output` 必须指向本次临时目录。

中文面试中夹杂英文术语时仍使用 `--language zh`。整段主要语言不确定时使用 `--language auto`，但自动检测可能稍慢。

## 五分钟基准

先使用 `ffmpeg` 截取一段有代表性的五分钟样本，不覆盖原录音：

```bash
ffmpeg -ss 600 -i "/path/to/interview.m4a" -t 300 -c copy "/tmp/interview-benchmark.m4a"
python interview-audio-review/scripts/transcribe_local.py \
  "/tmp/interview-benchmark.m4a" \
  --output "/tmp/interview-benchmark.json" \
  --language zh
```

脚本会输出音频时长、处理耗时和实时系数。对一小时录音的完整二十分钟目标，建议语音识别阶段实时系数不高于约 `0.15`。

基准音频和 JSON 也必须放入本次临时目录，不能留在录音目录。

如果太慢，先确认 Python 是 arm64 原生版本，再关闭逐词时间戳；仍然太慢时才使用更小模型：

```bash
python interview-audio-review/scripts/transcribe_local.py \
  "/path/to/interview.m4a" \
  --output "/path/to/interview.raw-transcript.json" \
  --language zh \
  --model mlx-community/whisper-small-mlx
```

更小模型速度更快，但技术词、中英混说和远场语音准确率可能下降。必须在报告中披露模型变化。

## 可选说话人分离

仅当快速角色推断明显失败时安装：

```bash
source .venv/bin/activate
python -m pip install pyannote.audio
```

随后需要：

1. 注册免费的 Hugging Face 账户；
2. 接受 `pyannote/speaker-diarization-community-1` 的使用条款；
3. 创建只读访问令牌；
4. 首次联网下载模型，之后在本地运行。

访问令牌只保存在本地环境中，不得写入 Skill、脚本、报告或版本库。pyannote 是可选增强项，不应成为清晰双人面试的固定依赖。

## 成本与云端边界

- 本地 `mlx-whisper`、开源 pyannote 模型和 `ffmpeg` 不按录音时长收费。
- 运行会消耗本机电量、存储和网络下载流量，但不产生转写 API 费用。
- OpenAI 等按分钟或按令牌计费的转写 API 不属于本 Skill 的默认免费路线。
- 云端服务即使宣称有免费额度，也必须在每次使用前重新确认额度、隐私和是否需要绑定支付方式。

## 性能说明

二十分钟是 M3、16 GB 级别 Apple 芯片设备处理约一小时清晰双人录音的优化目标，不是保证值。噪声、多人重叠、重复二次转写、完整说话人分离以及超长复盘都会增加耗时。报告必须写真实耗时，不得为了达标省略质量问题。

## 完成后的清理

最终报告通过检查后执行：

```bash
python interview-audio-review/scripts/cleanup_run.py \
  --run-dir "/private/tmp/interview-audio-review-本次随机目录" \
  --review "/path/to/interview.review.md"
```

如果本次失败、没有报告，也要清理本次临时目录：

```bash
python interview-audio-review/scripts/cleanup_run.py \
  --run-dir "/private/tmp/interview-audio-review-本次随机目录" \
  --failed
```

清理脚本只接受带运行标记的专用临时目录，不删除原始录音、本地模型、最终报告或录音目录中以前已有的文件。
