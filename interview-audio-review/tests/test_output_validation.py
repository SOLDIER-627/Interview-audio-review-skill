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
