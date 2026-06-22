import unittest
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import run_weekly_bsr


class CompletionMessageTests(unittest.TestCase):
    def test_success_message_is_plain_and_concise(self):
        message = run_weekly_bsr.build_completion_message(
            {
                "status": "success",
                "report_date": "2026-06-08",
                "report_path": "/tmp/report.md",
                "summary_path": "/tmp/summary.json",
                "report_data_counts": {
                    "new_products": 83,
                    "up_products": 676,
                    "down_products": 86,
                },
                "steps": [
                    {"name": "write_history_base", "status": "ok"},
                    {"name": "sync_independent_base", "status": "ok"},
                ],
                "independent_base_summary": {
                    "new_base": {
                        "copy_status": "copied",
                        "token_present": True,
                    }
                },
            }
        )

        self.assertNotIn("#", message)
        self.assertNotIn("##", message)
        self.assertNotIn("- ", message)
        self.assertNotIn("新上榜", message)
        self.assertNotIn("升幅", message)
        self.assertNotIn("降幅", message)
        self.assertIn("流程状态：成功", message)
        self.assertIn("新独立 Base 状态：copied", message)
        self.assertNotIn("base_token", message)
        self.assertNotIn("Token", message)

    def test_failure_message_keeps_only_key_error_context(self):
        message = run_weekly_bsr.build_completion_message(
            {
                "status": "failed",
                "report_date": "2026-06-08",
                "steps": [
                    {"name": "query_report_data", "status": "ok"},
                    {"name": "write_history_base", "status": "failed"},
                ],
                "error": "write_history_base 失败，returncode=1",
            }
        )

        self.assertIn("流程状态：异常", message)
        self.assertIn("异常步骤：write_history_base", message)
        self.assertIn("错误摘要：write_history_base 失败，returncode=1", message)
        self.assertNotIn("流程评价", message)
        self.assertNotIn("建议", message)

    def test_independent_checkpoint_status_marks_deferred_validation(self):
        table_counts = {str(i): {} for i in range(1, 10)}
        table_counts["全量数据"] = {}
        status = run_weekly_bsr.independent_checkpoint_status(
            {
                "new_base": {
                    "token_present": True,
                    "folder_rename": {"status": "needs_auth_scope"},
                    "table_counts": table_counts,
                    "all_view_visible_order_ok": False,
                },
                "deferred_validations": ["1: delayed"],
                "blocking_issues": [],
            }
        )

        self.assertEqual(status["copy_independent_base"], "ok")
        self.assertEqual(status["rename_folder"], "needs_auth_scope")
        self.assertEqual(status["validate_template_views"], "deferred")


if __name__ == "__main__":
    unittest.main()
