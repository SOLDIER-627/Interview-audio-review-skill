# 面试转写稿格式

用户只要求转写、文字稿、字幕或逐字稿且没有要求分析时，使用本格式。

## 输出文件

输入 `interview.m4a` 时，最终只输出 `interview.transcript.md`。同名文件存在时使用时间戳或递增版本，不得覆盖。

## 必需结构

```markdown
# interview 转写稿

## 转写说明

- 源文件、时长、转写后端和处理日期
- 说话人映射及其不确定性
- 直接影响完整性的听不清、重叠或不可靠范围

## 转写正文

[00:00:12–00:00:18] **面试官** 请简单介绍一下自己。

[00:00:19–00:00:35] **候选人** <只做高置信度纠错的真实内容>
```

## 证据规则

- 每段必须保留开始和结束时间戳；连续碎片可在不跨越说话人和语义边界时合并。
- 角色证据不足时使用“说话人 A/B”或“说话人未区分”，不得猜测身份。
- 只修正高置信度的专有名词、标点和断句；弱回答、停顿、自我修正和事实错误不得优化。
- 听不清、多人重叠或两次转写仍异常时使用 `[听不清]`、`[多人重叠]` 或 `[转写不可靠]`。
- Transcript 模式不包含表现评价、改进建议或推荐回答。

## 验证与清理

先运行：

```bash
python scripts/validate_output.py "/path/interview.transcript.md" --mode transcript
```

通过后运行：

```bash
python scripts/cleanup_run.py \
  --run-dir "/tmp/interview-audio-review-本次目录" \
  --artifact "/path/interview.transcript.md" \
  --mode transcript
```
