import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_DIR / "scripts"
PROJECT_ROOT = SKILL_DIR.parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sanitized_weekly_products.json"
sys.path.insert(0, str(SCRIPT_DIR))

import config
import generate_report_v2 as report
import prepare_and_write_data_v2 as prepare
import sync_independent_base as independent


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def wrapped_products(path: Path, rows):
    path.write_text(json.dumps([{"text": json.dumps(rows, ensure_ascii=False)}], ensure_ascii=False), encoding="utf-8")


class SanitizedFixtureCoverageTests(unittest.TestCase):
    def test_wrapper_json_parsing_and_malformed_payload(self):
        fixture = load_fixture()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            new_file = tmp / "new_products.json"
            up_file = tmp / "up_products.json"
            down_file = tmp / "down_products.json"
            wrapped_products(new_file, fixture["new_products"])
            wrapped_products(up_file, fixture["up_products"])
            wrapped_products(down_file, fixture["down_products"])

            new_rows, up_rows, down_rows = prepare.read_query_results(str(new_file), str(up_file), str(down_file))
            self.assertEqual(len(new_rows), 2)
            self.assertEqual(len(up_rows), 16)
            self.assertEqual(len(down_rows), 11)

            new_file.write_text(json.dumps([{"not_text": "bad"}]), encoding="utf-8")
            with self.assertRaises(KeyError):
                prepare.read_query_results(str(new_file), str(up_file), str(down_file))

    def test_prepare_data_filters_categories_and_applies_top_limits(self):
        fixture = load_fixture()
        rows, summary = prepare.prepare_data(
            fixture["new_products"],
            fixture["up_products"],
            fixture["down_products"],
            fixture["fields_order"],
            fixture["date"],
        )

        names = [row[3] for row in rows]
        self.assertEqual(summary["total_new"], 2)
        self.assertEqual(summary["total_up"], 15)
        self.assertEqual(summary["total_down"], 10)
        self.assertEqual(len(rows), 27)
        self.assertIn("Demo Product Up 16", names)
        self.assertNotIn("Demo Product Up 01", names)
        self.assertIn("Demo Product Down 11", names)
        self.assertNotIn("Demo Product Down 01", names)
        first = rows[0]
        self.assertEqual(first[0], fixture["date"])
        self.assertEqual(first[1], ["手机配件"])
        self.assertEqual(first[7], ["新上榜"])
        self.assertTrue(first[8].startswith("https://example.invalid/"))

    def test_independent_rows_for_category_and_full_table_projection(self):
        fixture = load_fixture()
        rows = independent.rows_for_category(
            fixture["fields_order"],
            fixture["date"],
            "手机配件",
            "手机支架/手机座",
            fixture["new_products"],
            fixture["up_products"],
            fixture["down_products"],
        )
        names = [row[3] for row in rows]

        self.assertEqual(len(rows), 26)
        self.assertIn("Demo Product Up 16", names)
        self.assertNotIn("Demo Product Up 01", names)
        self.assertIn("Demo Product Down 11", names)
        self.assertNotIn("Demo Product Down 01", names)

    def test_report_requires_complete_summary_counts(self):
        fixture = load_fixture()
        categories = report.get_categories()
        grouped = report.group_data_by_category(
            fixture["new_products"],
            fixture["up_products"],
            fixture["down_products"],
            categories,
        )

        with self.assertRaisesRegex(ValueError, "summary_counts.json 缺少类目计数"):
            report.generate_summary_table(categories, grouped, fixture["date"], fixture["summary_counts"])

        complete_counts = {
            (f"{cat['secondary']} - {cat['tertiary']}" if cat["tertiary"] else cat["secondary"]): 100
            for cat in categories
        }
        table = report.generate_summary_table(categories, grouped, fixture["date"], complete_counts)
        self.assertIn("| **合计** |", table)
        self.assertIn("**900**", table)

    def test_date_and_config_validation(self):
        with self.assertRaises(ValueError):
            prepare.validate_report_date("2026-6-15")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(config.ConfigError, "Missing required config"):
                config.DatabaseConfig.from_env()
            with self.assertRaisesRegex(config.ConfigError, "LARK_BASE_TOKEN"):
                config.LarkConfig.from_env()
        with patch.dict(
            os.environ,
            {
                "DORIS_HOST": "db.example.invalid",
                "DORIS_PORT": "30930",
                "DORIS_USER": "demo-user",
                "DORIS_PASSWORD": "demo-password",
                "DORIS_DATABASE": "demo",
                "DORIS_TARGET_TABLE": "weekly_target",
                "DORIS_SOURCE_TABLE": "weekly_source",
                "DORIS_STREAM_LOAD_HOSTS": "stream.example.invalid",
                "DORIS_STREAM_LOAD_PORTS": "33060",
                "DORIS_ALLOWED_STREAM_LOAD_HOST": "other.example.invalid",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(config.ConfigError, "Stream Load host not allowed"):
                config.DatabaseConfig.from_env()
        with patch.dict(
            os.environ,
            {
                "DORIS_HOST": "db.example.invalid",
                "DORIS_PORT": "30930",
                "DORIS_USER": "demo-user",
                "DORIS_PASSWORD": "demo-password",
                "DORIS_DATABASE": "demo",
                "DORIS_TARGET_TABLE": "bad.table",
                "DORIS_SOURCE_TABLE": "weekly_source",
                "DORIS_STREAM_LOAD_HOSTS": "stream.example.invalid",
                "DORIS_STREAM_LOAD_PORTS": "33060",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(config.ConfigError, "DORIS_TARGET_TABLE"):
                config.DatabaseConfig.from_env()

    def test_direct_write_scripts_require_approval_before_writes(self):
        prepare_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "prepare_and_write_data_v2.py"),
                "--date",
                "2026-06-15",
                "--yes",
            ],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(prepare_result.returncode, 0)
        self.assertIn("审批文件", prepare_result.stderr)

        repair_preview_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "prepare_and_write_data_v2.py"),
                "--date",
                "2026-06-15",
                "--preview-only",
                "--repair-table-name",
                "--table-id",
                "tbl_demo",
            ],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(repair_preview_result.returncode, 0)
        self.assertIn("审批文件", repair_preview_result.stderr)

        independent_result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "sync_independent_base.py"),
                "--date",
                "2026-06-15",
                "--yes",
            ],
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(independent_result.returncode, 0)
        self.assertIn("审批文件", independent_result.stderr)

    def test_root_dry_run_requires_explicit_date_and_skips_child_outputs(self):
        runner = PROJECT_ROOT / ".agents" / "workflows" / "run_tt_bsr_weekly_workflow.py"
        no_date = subprocess.run(
            [sys.executable, str(runner), "--dry-run"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(no_date.returncode, 0)
        self.assertIn("dry-run 未提供 --date", no_date.stderr)

        result = subprocess.run(
            [sys.executable, str(runner), "--date", "2026-06-15", "--dry-run"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary_line = next(line for line in result.stdout.splitlines() if "summary:" in line)
        summary_path = Path(summary_line.split("summary:", 1)[1].strip())
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertTrue(all(step["status"] == "skipped_dry_run" for step in payload["steps"]))
        self.assertFalse(Path(payload["output_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
