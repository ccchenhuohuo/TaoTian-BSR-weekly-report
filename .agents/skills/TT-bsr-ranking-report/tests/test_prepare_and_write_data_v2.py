import unittest
from pathlib import Path
from unittest.mock import patch

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import prepare_and_write_data_v2 as prepare


class ResolveHistoryTableTests(unittest.TestCase):
    def test_uses_existing_date_table(self):
        with patch.object(prepare.helper, "table_exists", return_value=(True, "tbl_existing")):
            table_id, status = prepare.resolve_history_table("base", "2026-06-08")

        self.assertEqual(table_id, "tbl_existing")
        self.assertEqual(status, "existing")

    def test_creates_missing_date_table_from_latest_structure(self):
        with patch.object(prepare.helper, "table_exists", return_value=(False, None)), patch.object(
            prepare.helper,
            "create_table_by_copying_latest",
            return_value=("tbl_created", True),
        ) as create_table:
            table_id, status = prepare.resolve_history_table("base", "2026-06-08")

        create_table.assert_called_once_with("base", "2026-06-08")
        self.assertEqual(table_id, "tbl_created")
        self.assertEqual(status, "created")

    def test_preview_does_not_create_missing_date_table(self):
        with patch.object(prepare.helper, "table_exists", return_value=(False, None)), patch.object(
            prepare.helper,
            "find_latest_table",
            return_value={"id": "tbl_latest", "name": "2026-06-01"},
        ), patch.object(prepare.helper, "create_table_by_copying_latest") as create_table:
            table_id, status = prepare.resolve_history_table("base", "2026-06-08", create_missing=False)

        create_table.assert_not_called()
        self.assertEqual(table_id, "tbl_latest")
        self.assertEqual(status, "preview_template")

    def test_missing_date_table_creation_failure_is_blocking(self):
        with patch.object(prepare.helper, "table_exists", return_value=(False, None)), patch.object(
            prepare.helper,
            "create_table_by_copying_latest",
            return_value=(None, False),
        ):
            with self.assertRaisesRegex(RuntimeError, "自动创建表 '2026-06-08' 失败"):
                prepare.resolve_history_table("base", "2026-06-08")

    def test_row_key_includes_rank_and_payload_fields(self):
        base = {
            "报告周期": "2026-06-08",
            "二级类目": ["手机配件"],
            "三级类目": ["手机支架/手机座"],
            "商品名称": "商品 A",
            "店铺名称": "店铺 A",
            "当周排名": 10,
            "异动值": 3,
            "异动类型": ["升幅"],
            "商品链接": "https://example.invalid/item?id=demo-row-key",
            "商品图片URL": "https://example.invalid/images/demo-row-key.jpg",
        }
        changed = dict(base)
        changed["当周排名"] = 11

        self.assertNotEqual(prepare.row_key_from_fields(base), prepare.row_key_from_fields(changed))


if __name__ == "__main__":
    unittest.main()
