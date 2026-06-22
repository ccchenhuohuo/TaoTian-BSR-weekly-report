import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / ".agents" / "workflows" / "run_tt_bsr_weekly_workflow.py"


class WorkflowRunnerTests(unittest.TestCase):
    def test_dry_run_writes_redacted_summary(self):
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--date",
                "2026-06-15",
                "--skip-sync",
                "--skip-query",
                "--skip-report",
                "--dry-run",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary_line = next(line for line in result.stdout.splitlines() if "summary:" in line)
        summary_path = Path(summary_line.split("summary:", 1)[1].strip())
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["report_date"], "2026-06-15")

    def test_write_requires_approval_file(self):
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--date",
                "2026-06-15",
                "--skip-sync",
                "--skip-query",
                "--skip-report",
                "--write-history-base",
                "--dry-run",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("审批文件", result.stderr)

    def test_redacts_secret_command_parts(self):
        command = [
            "python",
            "script.py",
            "--base-token",
            "fake-history-token",
            "--new-base-token",
            "fake-new-token",
        ]

        import importlib.util

        spec = importlib.util.spec_from_file_location("workflow_runner", RUNNER)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        redacted = module.redact_command(command)
        self.assertIn("<redacted>", redacted)
        self.assertNotIn("fake-history-token", redacted)
        self.assertNotIn("fake-new-token", redacted)


if __name__ == "__main__":
    unittest.main()
