# 面试录音复盘 Skill

这是一个面向真实面试录音的本地复盘 Skill。它把音频转写、转写纠错、问题与回答还原、逐题评价和推荐答案整合为一套流程，最终只保留一份可直接阅读的 `review.md`。

## 适合做什么

- 复盘技术面试、业务面试或模拟面试录音；
- 按时间顺序还原面试官的问题、追问和候选人的回答；
- 修正 Whisper 的明显错字、断句和中英文技术术语；
- 区分“候选人实际说了什么”和“更好的推荐回答”；
- 从切题程度、表达结构、正确性与深度、证据与影响、沟通表现五个维度逐题评价；
- 总结整场面试的优势、风险和优先练习计划。

不适用于未经参与者授权的秘密录音、根据声音确认现实身份，或需要虚构候选人经历的场景。

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

仓库不包含 `.venv`、Whisper 模型、面试录音、转写中间文件和复盘结果。这些内容均由使用者在本地创建，并已写入 `.gitignore`。

## 安装

### 1. 安装系统依赖

需要 Apple Silicon Mac、Homebrew、原生 arm64 Python 3.10 或更高版本，以及 `ffmpeg`：

```bash
brew install python ffmpeg
```

确认当前终端使用 arm64：

```bash
uname -m
python3 -c "import platform; print(platform.machine())"
```

两条命令都应输出 `arm64`。

### 2. 创建虚拟环境并安装 Python 依赖

在仓库根目录执行：

```bash
cd interview-audio-review-skill
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

默认依赖只有 `mlx-whisper`，其余运行包会由它自动安装。不要把生成的 `.venv` 提交到 Git。

### 3. 下载本地 Whisper 模型

推荐把模型下载到仓库根目录的 `models/`。该目录已被 Git 忽略：

```bash
source .venv/bin/activate
hf download mlx-community/whisper-large-v3-turbo \
  --local-dir models/whisper-large-v3-turbo
```

模型约占 1.5 GB。下载完成后的结构为：

```text
interview-audio-review-skill/
└── models/
    └── whisper-large-v3-turbo/
        ├── config.json
        └── weights.safetensors
```

脚本会从 Skill 目录逐级向上查找 `models/whisper-large-v3-turbo`。也可以把模型放在仓库的上级目录共享；如果始终找不到本地模型，`mlx-whisper` 会使用 Hugging Face 仓库标识下载到本机缓存。

### 4. 检查环境

在仓库根目录执行：

```bash
source .venv/bin/activate
python interview-audio-review/scripts/transcribe_local.py --check
```

预期看到：

```text
系统架构: arm64
ffmpeg: 已安装
mlx-whisper: 已安装
```

### 5. 让 Codex 发现这个 Skill

可以直接把 `interview-audio-review/` 目录交给 Codex，或者在本机 Skill 目录创建符号链接：

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/interview-audio-review" ~/.codex/skills/interview-audio-review
```

如果目标链接已经存在，先确认它指向哪里，不要直接覆盖。

## 运行需要什么

### 必需环境

- Apple Silicon Mac（M1/M2/M3/M4 等）；
- 原生 arm64 Python 3.10 或更高版本；
- `ffmpeg` 和 `ffprobe`；
- Python 包 `mlx-whisper`；
- 本地 `whisper-large-v3-turbo` 模型。

仓库不会携带虚拟环境和大模型。按照上面的安装命令完成后，转写在本机执行，不产生语音转写 API 费用。

### 输入材料

至少提供以下一种材料：

- 面试录音，如 `.m4a`、`.mp3`、`.wav`；
- 包含面试声音的视频；
- 已有的文字转写稿。

可选材料能提高分析质量：

- 应聘岗位说明；
- 个人简历；
- 项目说明；
- 公司、产品、姓名和中英文技术术语表。

只有录音中或用户材料里能够确认的经历才会进入推荐答案。缺少的数据使用 `[补充真实指标]` 等占位符，不会自动编造。

## 如何使用

在 Codex 中提供录音路径并要求使用本 Skill，例如：

```text
请使用 interview-audio-review Skill 完整复盘这段面试录音：
/path/to/interview.m4a
要求本地处理，不产生额外费用，完成后只保留 review.md。
```

也可以单独验证长录音转写脚本：

```bash
source .venv/bin/activate
python interview-audio-review/scripts/transcribe_chunked.py \
  "/path/to/interview.m4a" \
  --language zh \
  --initial-prompt "公司名、岗位名、Skill、Agent、MCP"
```

这个命令只完成本地分片转写并输出临时运行目录；完整的纠错、问答评价、推荐答案和清理流程由 Codex 按 `SKILL.md` 执行。

Skill 会自动完成：

1. 检查录音时长、格式、声道和本机环境；
2. 对长录音按十分钟分片，保留十秒重叠；
3. 使用本地 MLX Whisper 转写并合并绝对时间轴；
4. 检测重复短语、长时间短句等 Whisper 幻觉，可疑分片缩短后重试一次；
5. 根据对话语义推断面试官和候选人；
6. 纠正转写并一一还原问题、追问和回答；
7. 逐题评价并生成忠于真实经历的推荐答案；
8. 验证最终报告并清理本次音频分片、JSON 和草稿。

## 最终产出

假设输入是：

```text
面试录音.m4a
```

最终只新增：

```text
面试录音.review.md
```

报告包含：

- 处理方式、模型、耗时、费用和证据限制；
- 带时间戳的面试问题和忠实回答；
- 候选人可能想表达的核心意思；
- 五维逐题评分及评分依据；
- 做得好的地方和面试官可能产生的顾虑；
- 可以直接用于下次面试的推荐回答；
- 实质性转写纠错记录和不确定片段；
- 跨问题诊断、三个最高优先级改进项和练习计划。

原始录音和本地模型不会被修改或删除。音频切片、原始转写 JSON、纠错草稿和分析草稿只存在于本次系统临时目录；成功或失败结束后都会清理。

## 性能与费用

- 默认完全在本机运行，不上传录音；
- 不调用按分钟收费的语音识别 API；
- 首次模型下载需要网络，模型已经存在时可以离线转写；
- 在 M3、16 GB 级别设备上，以约一小时录音在二十分钟左右完成为优化目标，但噪声、多人重叠和局部重试会增加时间；
- 报告会记录真实耗时，不承诺固定完成时间。

## GitHub 提交边界

建议提交：

- `README.md`、`requirements.txt` 和 `.gitignore`；
- `interview-audio-review/SKILL.md`；
- `agents/`、`references/` 和 `scripts/`。

不要提交：

- `.venv/`；
- `models/` 和模型权重；
- 面试录音、视频或个人简历；
- 原始转写、纠错稿、`review.md` 和临时分片；
- Hugging Face Token、`.env` 或其他凭证。

## 关键文件

- `interview-audio-review/SKILL.md`：完整处理规则；
- `interview-audio-review/scripts/transcribe_chunked.py`：长录音分片、幻觉检测、局部重试和合并；
- `interview-audio-review/scripts/transcribe_local.py`：短录音本地转写；
- `interview-audio-review/scripts/cleanup_run.py`：验证报告后安全清理本次中间产物；
- `interview-audio-review/references/report-format.md`：最终报告结构。
