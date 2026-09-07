from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from output_validation import validate_review_text, validate_transcript_text  # noqa: E402


class OutputValidationTests(unittest.TestCase):
    def valid_review(self) -> str:
        return """# 报告

## 处理与证据说明

来源明确。{padding}

## 总体结论

总体表现明确。

# 面试问答

## Q1. 项目介绍 [00:00:01–00:00:30]

**面试官问题**

请介绍项目。

**我的回答**

这是我的真实回答。

**改进建议**

- 补充结果。

**推荐回答**

1. 先说结论。
2. 再说依据。
""".format(padding="证据" * 500)

    def test_valid_review(self) -> None:
        self.assertEqual(validate_review_text(self.valid_review()), [])

    def test_review_accepts_numbered_required_headings(self) -> None:
        text = self.valid_review()
        text = text.replace("## 处理与证据说明", "## 1. 处理与证据说明")
        text = text.replace("## 总体结论", "## 2. 总体结论")
        text = text.replace("# 面试问答", "## 3. 面试问答")
        self.assertEqual(validate_review_text(text), [])

    def test_review_validates_candidate_question_and_interviewer_answer(self) -> None:
        text = self.valid_review() + """

## C1. 团队方向 [00:00:31–00:01:10]

**候选人问题**

这个岗位入职后主要负责什么方向？

**面试官回答**

主要负责 Agent 工具、评测和业务接入。

**反问建议**

- 问题与岗位相关，可以继续追问近期目标。

**推荐问法**

这个岗位前三个月最希望交付什么结果？
"""
        self.assertEqual(validate_review_text(text), [])

    def test_review_rejects_candidate_question_without_interviewer_answer(self) -> None:
        text = self.valid_review() + """

## C1. 团队方向 [00:00:31–00:01:10]

**候选人问题**

这个岗位入职后主要负责什么方向？

**面试官回答**

**反问建议**

- 问题与岗位相关。

**推荐问法**

这个岗位前三个月最希望交付什么结果？
"""
        self.assertTrue(
            any("C1" in item and "面试官回答" in item and "为空" in item for item in validate_review_text(text))
        )

    def test_review_rejects_out_of_order_q_and_c_blocks(self) -> None:
        text = self.valid_review() + """

## C1. 团队方向 [00:00:00–00:00:01]

**候选人问题**

这个岗位负责什么方向？

**面试官回答**

负责 Agent 工程。

**反问建议**

- 问题有信息价值。

**推荐问法**

这个岗位前三个月的目标是什么？
"""
        self.assertIn("Q/C 问答未按时间顺序排列", validate_review_text(text))

    def test_interviewer_question_can_resume_after_candidate_question(self) -> None:
        text = self.valid_review() + """

## C1. 团队方向 [00:00:31–00:01:10]

**候选人问题**

这个岗位负责什么方向？

**面试官回答**

负责 Agent 工程。

**反问建议**

- 可以继续追问近期目标。

**推荐问法**

这个岗位前三个月的目标是什么？

## Q2. 音视频经验 [00:01:11–00:02:00]

**面试官问题**

你有哪些音视频经验？

**我的回答**

我做过离线视频处理。

**改进建议**

- 补充端到端链路。

**推荐回答**

1. 先说明经验边界。
2. 再介绍实际项目。
"""
        self.assertEqual(validate_review_text(text), [])

    def test_review_rejects_missing_answer(self) -> None:
        text = self.valid_review().replace("这是我的真实回答。", "")
        self.assertTrue(any("我的回答" in item and "为空" in item for item in validate_review_text(text)))

    def test_review_rejects_missing_timestamp(self) -> None:
        text = self.valid_review().replace(" [00:00:01–00:00:30]", "")
        self.assertIn("没有带时间戳的正式问题", validate_review_text(text))

    def test_transcript_validation(self) -> None:
        text = """# 示例转写稿

## 转写说明

这是说明。{padding}

## 转写正文

[00:00:01–00:00:03] **面试官** 你好。
""".format(padding="说明" * 100)
        self.assertEqual(validate_transcript_text(text), [])


if __name__ == "__main__":
    unittest.main()
