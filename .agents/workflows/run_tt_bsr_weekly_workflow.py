#!/usr/bin/env python3
"""
Production wrapper for the Taotian BSR weekly workflow.

The project-level skill owns the business scripts. This wrapper provides a
repository-level scheduling contract, redacted logs, summary artifacts, and a
write approval gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = PROJECT_ROOT / ".agents" / "skills" / "TT-bsr-ranking-report"
SCRIPT_DIR = SKILL_DIR / "scripts"
LOG_ROOT = PROJECT_ROOT / "logs" / "tt-bsr-weekly-workflow"
SECRET_FLAGS = {
    "--base-token",
    "--template-base-token",
    "--new-base-token",
    "--password",
}
SECRET_KEY_RE = re.compile(r'("(?:[^"]*(?:token|password|secret|api_key|authorization)[^"]*)"\s*:\s*)"[^"]*"', re.I)
BASE_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+\.feishu\.cn/base/[A-Za-z0-9]+")
BASE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{20,}\b")


class WorkflowError(RuntimeError):
    """Raised for expected workflow failures."""


def load_project_env() -> None:
    """Load local runtime configuration before argparse reads env defaults."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for env_path in (PROJECT_ROOT / ".env", SKILL_DIR / ".env"):
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the production Taotian BSR weekly workflow")
    parser.add_argument("--date", help="Report date YYYY-MM-DD. Defaults to the latest date after sync.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Doris sync.")
    parser.add_argument("--skip-query", action="store_true", help="Skip report data query.")
    parser.add_argument("--skip-report", action="store_true", help="Skip Markdown report rendering.")
    parser.add_argument("--write-history-base", action="store_true", help="Write the historical full Base date table.")
    parser.add_argument("--sync-independent-base", action="store_true", help="Copy/write/verify the independent date Base.")
    parser.add_argument("--approval-file", type=Path, help="JSON approval file required for Base writes.")
    parser.add_argument("--base-token", default=os.environ.get("LARK_BASE_TOKEN", ""))
    parser.add_argument("--template-base-token", default=os.environ.get("LARK_INDEPENDENT_TEMPLATE_BASE_TOKEN", ""))
    parser.add_argument("--new-base-token", default="")
    parser.add_argument("--yes", action="store_true", help="Run write-capable child scripts non-interactively.")
    parser.add_argument("--dry-run", action="store_true", help="Write summary artifacts without executing child scripts.")
    parser.add_argument("--sync-timeout", type=int, default=600)
    parser.add_argument("--query-timeout", type=int, default=300)
    parser.add_argument("--report-timeout", type=int, default=180)
    parser.add_argument("--base-timeout", type=int, default=1200)
    parser.add_argument("--independent-timeout", type=int, default=2400)
    return parser.parse_args()


def validate_report_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise WorkflowError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise WorkflowError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


def redact_text(text: str) -> str:
    if not text:
        return text
    text = SECRET_KEY_RE.sub(r'\1"<redacted>"', text)
    text = BASE_URL_RE.sub("https://<feishu-base-redacted>", text)
    return BASE_TOKEN_RE.sub("<redacted-token>", text)


def redact_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for part in cmd:
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            continue
        redacted.append(redact_text(part))
        if part in SECRET_FLAGS:
            hide_next = True
    return redacted


def run_command(
    name: str,
    cmd: list[str],
    timeout: int,
    summary: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    step = {
        "name": name,
        "command": redact_command(cmd),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
    }
    summary["steps"].append(step)
    print(f"\n========== {name} ==========")
    print(" ".join(step["command"]))

    if dry_run:
        step["status"] = "skipped_dry_run"
        step["returncode"] = 0
        step["finished_at"] = datetime.now().isoformat(timespec="seconds")
        return

    try:
        result = subprocess.run(
            cmd,
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        step["status"] = "timeout"
        step["timeout_seconds"] = timeout
        step["finished_at"] = datetime.now().isoformat(timespec="seconds")
        raise WorkflowError(f"{name} 超时（{timeout}s）") from exc

    step["returncode"] = result.returncode
    step["stdout_tail"] = redact_text(result.stdout[-4000:])
    step["stderr_tail"] = redact_text(result.stderr[-4000:])
    step["finished_at"] = datetime.now().isoformat(timespec="seconds")
    step["status"] = "ok" if result.returncode == 0 else "failed"
    if result.stdout:
        print(redact_text(result.stdout))
    if result.stderr:
        print(redact_text(result.stderr), file=sys.stderr)
    if result.returncode != 0:
        raise WorkflowError(f"{name} 失败，returncode={result.returncode}")


def approval_granted(path: Path | None, report_date: str) -> bool:
    if path is None or not path.exists():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    return bool(payload.get("approved")) and payload.get("report_date") == report_date


def latest_report_date_from_db() -> str:
    sys.path.insert(0, str(SCRIPT_DIR))
    from config import DatabaseConfig, load_env_safe

    import pymysql

    load_env_safe()
    cfg = DatabaseConfig.from_env()
    conn = pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT MAX(DATE(business_date)) AS latest_week FROM {cfg.target_table}")
            latest = cursor.fetchone()["latest_week"]
    finally:
        conn.close()
    if not latest:
        raise WorkflowError("目标表无业务日期")
    return latest.strftime("%Y-%m-%d") if hasattr(latest, "strftime") else str(latest)


def write_artifacts(summary: dict[str, Any], run_dir: Path) -> tuple[Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_lines = [
        f"# 淘天 BSR Workflow Run {summary['run_id']}",
        "",
        f"- Status: {summary.get('status')}",
        f"- Report date: {summary.get('report_date', 'N/A')}",
        f"- Started at: {summary.get('started_at')}",
        f"- Finished at: {summary.get('finished_at', 'N/A')}",
        "",
        "## Steps",
    ]
    for step in summary.get("steps", []):
        report_lines.append(f"- {step.get('name')}: {step.get('status')} ({step.get('returncode', 'N/A')})")
    if summary.get("error"):
        report_lines.extend(["", "## Error", redact_text(str(summary["error"]))])
    run_report_path = run_dir / "run-report.md"
    run_report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary_path, run_report_path


def main() -> int:
    load_project_env()
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = LOG_ROOT / run_id
    summary: dict[str, Any] = {
        "workflow": "tt-bsr-weekly",
        "run_id": run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "steps": [],
        "dry_run": args.dry_run,
    }

    try:
        report_date = validate_report_date(args.date) if args.date else None
        if not args.skip_sync:
            run_command(
                "sync",
                [sys.executable, str(SCRIPT_DIR / "sync_data.py")],
                args.sync_timeout,
                summary,
                dry_run=args.dry_run,
            )

        if report_date is None and not args.dry_run:
            report_date = latest_report_date_from_db()
        if report_date is None:
            raise WorkflowError("dry-run 未提供 --date；生产运行会从 Doris 查询最新报告日期，不读取本地旧输出推断日期")
        summary["report_date"] = report_date

        output_dir = run_dir / "tool-results" / report_date.replace("-", "")
        summary["output_dir"] = str(output_dir)

        if not args.skip_query:
            run_command(
                "query",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "query_report_data.py"),
                    "--date",
                    report_date,
                    "--output-dir",
                    str(output_dir),
                ],
                args.query_timeout,
                summary,
                dry_run=args.dry_run,
            )

        if not args.skip_report:
            run_command(
                "render_report",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "generate_report_v2.py"),
                    "--date",
                    report_date,
                    "--data-dir",
                    str(output_dir),
                ],
                args.report_timeout,
                summary,
                dry_run=args.dry_run,
            )

        needs_write = args.write_history_base or args.sync_independent_base
        if needs_write and not approval_granted(args.approval_file, report_date):
            raise WorkflowError("Base 写入需要审批文件，且 approved=true、report_date 必须匹配本次报告日期")

        if args.write_history_base:
            if not args.base_token:
                raise WorkflowError("写历史全量 Base 需要 --base-token 或 LARK_BASE_TOKEN")
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "prepare_and_write_data_v2.py"),
                "--date",
                report_date,
                "--base-token",
                args.base_token,
                "--data-dir",
                str(output_dir),
                "--summary-file",
                str(run_dir / "history_base_summary.json"),
                "--approval-file",
                str(args.approval_file),
            ]
            if args.yes:
                cmd.append("--yes")
            run_command("history_base", cmd, args.base_timeout, summary, dry_run=args.dry_run)

        if args.sync_independent_base:
            if not args.template_base_token and not args.new_base_token:
                raise WorkflowError("同步独立日期 Base 需要 --template-base-token 或 --new-base-token")
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "sync_independent_base.py"),
                "--date",
                report_date,
                "--data-dir",
                str(output_dir),
                "--summary-file",
                str(run_dir / "independent_base_summary.json"),
                "--approval-file",
                str(args.approval_file),
            ]
            if args.template_base_token:
                cmd.extend(["--template-base-token", args.template_base_token])
            if args.new_base_token:
                cmd.extend(["--new-base-token", args.new_base_token])
            if args.yes:
                cmd.append("--yes")
            run_command("independent_base", cmd, args.independent_timeout, summary, dry_run=args.dry_run)

        summary["status"] = "success"
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary_path, run_report_path = write_artifacts(summary, run_dir)
        print(f"\n[完成] summary: {summary_path}")
        print(f"[完成] run report: {run_report_path}")
        return 0
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = redact_text(str(exc))
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary_path, run_report_path = write_artifacts(summary, run_dir)
        print(f"\n[失败] {summary['error']}", file=sys.stderr)
        print(f"summary: {summary_path}", file=sys.stderr)
        print(f"run report: {run_report_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
