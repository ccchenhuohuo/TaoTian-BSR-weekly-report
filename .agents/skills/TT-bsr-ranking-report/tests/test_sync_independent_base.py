import unittest
import tempfile
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import sync_independent_base as independent


class IndependentBaseValidationTests(unittest.TestCase):
    def test_deferred_view_validation_is_not_blocking_by_default(self):
        summary = {
            "new_base": {
                "view_name_validation": {},
                "view_visible_order_validation": {},
                "template_validation_details": {},
            },
            "warnings": [],
            "deferred_validations": [],
            "blocking_issues": [],
        }
        result = {
            "view_name_ok": True,
            "view_visible_order_ok": False,
            "view_visible_status": "validation_deferred",
        }

        independent.add_validation_result(summary, "1", result, strict=False)

        self.assertEqual(summary["blocking_issues"], [])
        self.assertEqual(summary["deferred_validations"], ["1: 视图可见字段顺序校验延后"])
        self.assertFalse(summary["new_base"]["view_visible_order_validation"]["1"])

    def test_deferred_view_validation_blocks_in_strict_mode(self):
        summary = {
            "new_base": {
                "view_name_validation": {},
                "view_visible_order_validation": {},
                "template_validation_details": {},
            },
            "warnings": [],
            "deferred_validations": [],
            "blocking_issues": [],
        }
        result = {
            "view_name_ok": True,
            "view_visible_order_ok": False,
            "view_visible_status": "validation_deferred",
        }

        independent.add_validation_result(summary, "1", result, strict=True)

        self.assertIn("1: 视图可见字段顺序无法确认", summary["blocking_issues"])

    def test_write_summary_redacts_base_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.json"
            independent.write_summary(
                {
                    "date": "2026-06-15",
                    "template_base": {"token": "fake-template-token"},
                    "new_base": {
                        "token": "fake-new-base-token",
                        "url": "https://example.invalid/base/fake-base",
                    },
                },
                "2026-06-15",
                str(path),
            )

            text = path.read_text(encoding="utf-8")

        self.assertNotIn("fake-template-token", text)
        self.assertNotIn("fake-new-base-token", text)
        self.assertIn("<redacted>", text)

    def test_duplicate_count_detects_repeated_business_keys(self):
        records = [
            {
                "fields": {
                    "报告周期": "2026-06-15",
                    "二级类目": ["手机配件"],
                    "三级类目": ["手机支架/手机座"],
                    "异动类型": ["升幅"],
                    "商品链接": "https://example.invalid/item?id=duplicate",
                }
            },
            {
                "fields": {
                    "报告周期": "2026-06-15",
                    "二级类目": ["手机配件"],
                    "三级类目": ["手机支架/手机座"],
                    "异动类型": ["升幅"],
                    "商品链接": "https://example.invalid/item?id=duplicate",
                }
            },
        ]

        self.assertEqual(independent.duplicate_count(records), 1)

    def test_table_blocking_issues_cover_mismatch_count_and_duplicates(self):
        issues = independent.blocking_issues_for_table(
            table_name="1",
            expected_rows=3,
            record_count=2,
            preexisting=2,
            write_status="preexisting_mismatch",
            duplicates=1,
        )

        self.assertEqual(len(issues), 3)
        self.assertTrue(any("已有 2 条" in issue for issue in issues))
        self.assertTrue(any("读回记录数 2 与期望 3" in issue for issue in issues))
        self.assertTrue(any("发现 1 条重复记录" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
