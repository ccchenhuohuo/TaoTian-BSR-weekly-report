import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import lark_base_helper as helper


class LarkBaseHelperTests(unittest.TestCase):
    def test_parse_missing_scopes_from_json_error(self):
        payload = {
            "ok": False,
            "error": {
                "message": "missing required scope(s): base:block:update",
                "missing_scopes": ["base:block:update"],
            },
        }

        self.assertEqual(helper.parse_missing_scopes(json.dumps(payload)), ["base:block:update"])

    def test_folder_rename_reports_missing_update_scope(self):
        with patch.object(helper, "list_blocks", return_value=([{"id": "bfl1", "name": "2026-06-08"}], "")), patch.object(
            helper,
            "rename_block",
            return_value=(False, json.dumps({"error": {"missing_scopes": ["base:block:update"]}})),
        ):
            result = helper.rename_date_folder_if_possible("base", "2026-06-15")

        self.assertEqual(result["status"], "needs_auth_scope")
        self.assertEqual(result["missing_scopes"], ["base:block:update"])
        self.assertIn("lark-cli auth login", result["auth_hint"])

    def test_validate_and_repair_view_visible_fields(self):
        with patch.object(
            helper,
            "get_view_visible_fields",
            side_effect=[["A", "B"], ["B", "A"], ["A", "B"]],
        ), patch.object(helper, "set_view_visible_fields", return_value=(True, "")) as set_visible:
            result = helper.validate_and_repair_view_visible_fields(
                "template",
                "new",
                "tbl_template",
                "tbl_new",
                "view_template",
                "view_new",
                repair=True,
            )

        set_visible.assert_called_once_with("new", "tbl_new", "view_new", ["A", "B"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "repaired")

    def test_command_redaction_masks_tokens_and_payloads(self):
        command = [
            "lark-cli",
            "base",
            "+record-batch-create",
            "--base-token",
            "fake-history-token",
            "--json",
            '{"rows":[["large payload"]]}',
        ]

        display = helper.redact_command_args(command)

        self.assertIn("<redacted>", display)
        self.assertIn("<json", display)
        self.assertNotIn("fake-history-token", display)
        self.assertNotIn("large payload", display)

    def test_write_command_detection(self):
        self.assertTrue(helper.is_write_lark_command(["lark-cli", "base", "+record-batch-create"]))
        self.assertFalse(helper.is_write_lark_command(["lark-cli", "base", "+record-list"]))

    def test_lark_cli_bin_replaces_generic_executable(self):
        with patch.dict(os.environ, {"LARK_CLI_BIN": "/usr/local/bin/lark-cli"}):
            args = helper.normalize_lark_args(["lark-cli", "--version"])

        self.assertEqual(args[0], "/usr/local/bin/lark-cli")


if __name__ == "__main__":
    unittest.main()
