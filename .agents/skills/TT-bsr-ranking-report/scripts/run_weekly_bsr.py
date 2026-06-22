#!/usr/bin/env python3
"""
Scheduled orchestration entrypoint for the weekly Taotian BSR workflow.

Safe default: sync Doris, query report data, and render Markdown only.
Feishu completion-summary sending and Base writes require explicit flags.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import ConfigError, DatabaseConfig, load_env_safe
import lark_base_helper as helper


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REPORT_USER_ID = ""
STEP_ORDER = [
    "sync",
    "query",
    "render_report",
    "history_base",
    "independent_base",
    "send_summary",
]
LARK_REQUIRED_SCOPES = [
    "base:app:readonly",
    "base:app:readwrite",
    "base:block:read",
    "base:block:update",
    "im:message:send_as_bot",
]
SECRET_FLAGS = {"--base-token", "--template-base-token", "--new-base-token", "--password"}
BASE_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+\.feishu\.cn/base/[A-Za-z0-9]+")
BASE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{20,}\b")
SECRET_KEY_RE = re.compile(r'("(?:[^"]*(?:token|password|secret|api_key|authorization)[^"]*)"\s*:\s*)"[^"]*"', re.I)
SENSITIVE_KEY_RE = re.compile(r"(token|password|secret|api_key|authorization)", re.I)


class WorkflowError(RuntimeError):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Run the weekly Taotian BSR workflow end-to-end")
    parser.add_argument("--date", help="Report date YYYY-MM-DD. Defaults to latest configured target-table date after sync.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to tool-results/YYYYMMDD.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Doris sync step.")
    parser.add_argument(
        "--send-summary",
        dest="send_summary",
        action="store_true",
        help="Send workflow completion summary, evaluation, and suggestions to Feishu. Does not send report data.",
    )
    parser.add_argument("--report-user-id", default=os.environ.get("LARK_REPORT_USER_ID", DEFAULT_REPORT_USER_ID))
    parser.add_argument("--report-chat-id", default=os.environ.get("LARK_REPORT_CHAT_ID", ""))
    parser.add_argument("--write-history-base", action="store_true", help="Write/sync the historical full Base date table.")
    parser.add_argument("--base-token", default=os.environ.get("LARK_BASE_TOKEN", ""), help="Historical full Base token.")
    parser.add_argument("--sync-independent-base", action="store_true", help="Copy/write/verify the independent date Base.")
    parser.add_argument("--template-base-token", default=os.environ.get("LARK_INDEPENDENT_TEMPLATE_BASE_TOKEN", ""))
    parser.add_argument("--new-base-token", help="Existing independent Base token. If omitted, copy template.")
    parser.add_argument("--allow-ui-fallback", action="store_true", help="Allow independent Base folder rename UI fallback.")
    parser.add_argument("--approval-file", help="JSON approval file required before any Base write.")
    parser.add_argument("--yes", action="store_true", help="Run write-capable sub-scripts non-interactively.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running write-capable steps or Feishu summary sending.")
    parser.add_argument("--resume", action="store_true", help="Resume from an existing run_weekly_bsr_summary.json when possible.")
    parser.add_argument("--from-step", choices=STEP_ORDER, help="Start at the named workflow step and skip earlier steps.")
    parser.add_argument("--sync-timeout", type=int, default=600)
    parser.add_argument("--query-timeout", type=int, default=300)
    parser.add_argument("--report-timeout", type=int, default=180)
    parser.add_argument("--send-timeout", type=int, default=120)
    parser.add_argument("--base-timeout", type=int, default=1200)
    parser.add_argument("--independent-timeout", type=int, default=2400)
    return parser.parse_args()


def should_run_step(args, summary: Dict, step_name: str) -> bool:
    if args.from_step:
        return STEP_ORDER.index(step_name) >= STEP_ORDER.index(args.from_step)
    if not args.resume:
        return True
    for step in summary.get("steps", []):
        if step.get("name") == step_name and step.get("status") in ("ok", "skipped_dry_run"):
            return False
    return True


def load_existing_summary(report_date: Optional[str], output_dir: Optional[Path]) -> Dict:
    if output_dir:
        path = output_dir / "run_weekly_bsr_summary.json"
    elif report_date:
        path = SKILL_DIR / "tool-results" / report_date.replace("-", "") / "run_weekly_bsr_summary.json"
    else:
        return {}
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_history_base_summary(report_date: str) -> Dict:
    path = SKILL_DIR / "tool-results" / report_date.replace("-", "") / "history_base_summary.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    payload["summary_path"] = str(path)
    return payload


def load_sync_summary(report_date: str) -> Dict:
    path = SKILL_DIR / "tool-results" / report_date.replace("-", "") / "sync_summary.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    payload["summary_path"] = str(path)
    return payload


def independent_checkpoint_status(independent: Dict) -> Dict[str, str]:
    if not independent:
        return {}
    new_base = independent.get("new_base") or {}
    table_counts = new_base.get("table_counts") or {}
    folder = new_base.get("folder_rename") or {}
    return {
        "copy_independent_base": "ok" if (
            new_base.get("token_present") or new_base.get("copy_status") in ("copied", "provided")
        ) else "missing",
        "rename_folder": folder.get("status", "not_run"),
        "write_category_tables": "ok" if all(str(i) in table_counts for i in range(1, 10)) else "missing",
        "write_full_table": "ok" if "全量数据" in table_counts else "missing",
        "verify_records": "ok" if table_counts and not independent.get("blocking_issues") else "blocked",
        "validate_template_views": "ok" if new_base.get("all_view_visible_order_ok") else (
            "deferred" if independent.get("deferred_validations") else "not_run"
        ),
    }


def validate_report_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise WorkflowError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise WorkflowError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


def redact_text(value: str) -> str:
    if not value:
        return value
    value = SECRET_KEY_RE.sub(r'\1"<redacted>"', value)
    value = BASE_URL_RE.sub("https://<feishu-base-redacted>", value)
    return BASE_TOKEN_RE.sub("<redacted-token>", value)


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if SENSITIVE_KEY_RE.search(str(key)) else redact_obj(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def approval_granted(path: Optional[str], report_date: str) -> bool:
    if not path:
        return False
    approval_path = Path(path)
    if not approval_path.exists():
        return False
    with approval_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return bool(payload.get("approved")) and payload.get("report_date") == report_date


def latest_report_date() -> str:
    import pymysql

    try:
        cfg = DatabaseConfig.from_env()
    except ConfigError as exc:
        raise WorkflowError(f"配置加载失败: {exc}") from exc

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


def run_command(
    name: str,
    cmd: List[str],
    timeout: int,
    summary: Dict,
    dry_run: bool = False,
) -> subprocess.CompletedProcess:
    print(f"\n========== {name} ==========")
    print(format_command_for_log(cmd))
    step = {
        "name": name,
        "command": format_command_for_log(cmd),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
    }
    summary["steps"].append(step)

    if dry_run:
        step["status"] = "skipped_dry_run"
        step["returncode"] = 0
        return subprocess.CompletedProcess(cmd, 0, "", "")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        step["status"] = "timeout"
        step["timeout_seconds"] = timeout
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
    return result


def format_command_for_log(cmd: List[str]) -> str:
    display = []
    skip_next = False
    for idx, part in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        display.append(redact_text(part))
        if part in SECRET_FLAGS and idx + 1 < len(cmd):
            display.append("<redacted>")
            skip_next = True
        elif part == "--text" and idx + 1 < len(cmd):
            text = cmd[idx + 1]
            display.append(f"<text {len(text)} chars>")
            skip_next = True
    return " ".join(display)


def read_wrapper_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list) and payload and "text" in payload[0]:
        return len(json.loads(payload[0]["text"]))
    if isinstance(payload, list):
        return len(payload)
    raise WorkflowError(f"无法识别 JSON 文件格式: {path}")


def collect_counts(output_dir: Path) -> Dict[str, int]:
    return {
        "new_products": read_wrapper_count(output_dir / "new_products.json"),
        "up_products": read_wrapper_count(output_dir / "up_products.json"),
        "down_products": read_wrapper_count(output_dir / "down_products.json"),
    }


def load_independent_base_summary(report_date: str) -> Dict:
    ymd = report_date.replace("-", "")
    path = SKILL_DIR / "tool-results" / f"{ymd}_independent_base_summary.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    payload["summary_path"] = str(path)
    return payload


def step_status(steps: List[Dict], name: str) -> str:
    aliases = {
        "write_history_base": "history_base",
        "sync_independent_base": "independent_base",
        "query_report_data": "query",
        "generate_report": "render_report",
        "sync_doris": "sync",
    }
    name = aliases.get(name, name)
    for step in reversed(steps):
        step_name = aliases.get(step.get("name"), step.get("name"))
        if step_name == name:
            if step.get("status") == "ok":
                return "已完成"
            if step.get("status") == "skipped_dry_run":
                return "演练未写入"
            return "异常"
    return "未执行"


def build_completion_message(summary: Dict) -> str:
    steps = summary.get("steps", [])
    failed_steps = [step for step in steps if step.get("status") not in ("ok", "skipped_dry_run")]
    dry_run_steps = [step["name"] for step in steps if step.get("status") == "skipped_dry_run"]
    status_label = "成功" if summary.get("status") == "success" and not failed_steps else "异常"
    independent = summary.get("independent_base_summary") or {}
    history = summary.get("history_base_summary") or {}
    new_base = independent.get("new_base") or {}
    manual_actions = independent.get("manual_actions") or []
    deferred_validations = independent.get("deferred_validations") or []

    lines = [
        "淘天 BSR 周报业务产物与流程状态",
        f"流程状态：{status_label}",
        f"报告日期：{summary.get('report_date', 'N/A')}",
        f"历史全量 Base：{step_status(steps, 'history_base')}",
        f"独立日期 Base：{step_status(steps, 'independent_base')}",
    ]
    if new_base.get("copy_status"):
        lines.append(f"新独立 Base 状态：{new_base['copy_status']}")
    if summary.get("report_path"):
        lines.append(f"报告文件：{summary['report_path']}")
    if summary.get("summary_path"):
        lines.append(f"运行摘要：{summary['summary_path']}")
    if history.get("table_id"):
        lines.append(f"历史 Base 表 ID：{history['table_id']}")
    if new_base.get("full_table_change_type_counts"):
        counts = new_base["full_table_change_type_counts"]
        lines.append(
            "独立 Base 全量计数："
            f"新上榜 {counts.get('新上榜', 0)}，"
            f"升幅 {counts.get('升幅', 0)}，"
            f"降幅 {counts.get('降幅', 0)}"
        )
    if dry_run_steps:
        lines.append(f"演练步骤：{', '.join(dry_run_steps)}")
    if failed_steps:
        lines.append(f"异常步骤：{', '.join(step.get('name', 'unknown') for step in failed_steps)}")
    if summary.get("lark_auth", {}).get("missing_scopes"):
        lines.append(f"缺少权限：{', '.join(summary['lark_auth']['missing_scopes'])}")
        if summary["lark_auth"].get("auth_hint"):
            lines.append(f"补权限命令：{summary['lark_auth']['auth_hint']}")
    if independent.get("issues"):
        lines.append(f"独立 Base 注意事项：{'；'.join(independent['issues'])}")
    if deferred_validations:
        lines.append(f"延后校验：{'；'.join(deferred_validations)}")
    if manual_actions:
        lines.append(f"需人工处理：{'；'.join(manual_actions)}")
    if independent.get("blocking_issues"):
        lines.append(f"独立 Base 阻塞事项：{'；'.join(independent['blocking_issues'])}")
    if summary.get("error"):
        lines.append(f"错误摘要：{summary['error']}")
    return "\n".join(lines)


def send_completion_summary(args, summary: Dict):
    if not args.report_chat_id and not args.report_user_id:
        raise WorkflowError("发送流程总结需要 --report-chat-id 或 LARK_REPORT_USER_ID")
    text = build_completion_message(summary)
    cmd = [helper.configured_lark_cli(), "im", "+messages-send", "--as", "bot", "--text", text]
    target = ""
    if args.report_chat_id:
        cmd.extend(["--chat-id", args.report_chat_id])
        target = args.report_chat_id
    else:
        cmd.extend(["--user-id", args.report_user_id])
        target = args.report_user_id
    summary["summary_send_target"] = target
    run_command("send_summary", cmd, args.send_timeout, summary, dry_run=args.dry_run)


def write_summary(summary: Dict, report_date: Optional[str], output_dir: Optional[Path]) -> Path:
    if output_dir:
        summary_dir = output_dir
    elif report_date:
        summary_dir = SKILL_DIR / "tool-results" / report_date.replace("-", "")
    else:
        summary_dir = SKILL_DIR / "tool-results" / "run_summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / "run_weekly_bsr_summary.json"
    path.write_text(json.dumps(redact_obj(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_and_optionally_send_summary(args, summary: Dict, report_date: Optional[str], output_dir: Optional[Path]) -> Path:
    summary_path = write_summary(summary, report_date, output_dir)
    summary["summary_path"] = str(summary_path)
    if args.send_summary:
        send_completion_summary(args, summary)
        summary_path = write_summary(summary, report_date, output_dir)
        summary["summary_path"] = str(summary_path)
        summary_path = write_summary(summary, report_date, output_dir)
    return summary_path


def main() -> int:
    load_env_safe()
    args = parse_args()

    summary = {
        "workflow": "weekly_bsr",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "steps": [],
    }
    report_date = None
    output_dir = None

    try:
        if args.date:
            report_date = validate_report_date(args.date)
        output_dir = Path(args.output_dir) if args.output_dir else (
            SKILL_DIR / "tool-results" / report_date.replace("-", "") if report_date else None
        )
        if args.resume:
            existing = load_existing_summary(report_date, output_dir)
            if existing:
                summary.update(existing)
                summary["status"] = "running"
                summary["resumed_at"] = datetime.now().isoformat(timespec="seconds")
                report_date = report_date or summary.get("report_date")
                if report_date and output_dir is None:
                    output_dir = SKILL_DIR / "tool-results" / report_date.replace("-", "")

        summary["lark_cli_version"] = helper.lark_cli_version()
        needs_lark = args.send_summary or args.write_history_base or args.sync_independent_base
        lark_step_will_run = any(
            should_run_step(args, summary, step)
            for step in ("history_base", "independent_base", "send_summary")
        )
        if needs_lark and lark_step_will_run:
            auth = helper.check_auth_scopes(LARK_REQUIRED_SCOPES)
            summary["lark_auth"] = auth

        if not args.skip_sync and should_run_step(args, summary, "sync"):
            run_command(
                "sync",
                [sys.executable, str(SCRIPT_DIR / "sync_data.py")],
                args.sync_timeout,
                summary,
            )

        if not report_date:
            report_date = latest_report_date()
        summary["report_date"] = report_date

        output_dir = output_dir or SKILL_DIR / "tool-results" / report_date.replace("-", "")
        output_dir.mkdir(parents=True, exist_ok=True)
        summary["output_dir"] = str(output_dir)
        summary["sync_summary"] = load_sync_summary(report_date)

        if should_run_step(args, summary, "query"):
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
            )
        if all((output_dir / name).exists() for name in ("new_products.json", "up_products.json", "down_products.json")):
            summary["report_data_counts"] = collect_counts(output_dir)

        if should_run_step(args, summary, "render_report"):
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
            )
        report_path = SKILL_DIR / "report_collection" / f"bsr_ranking_report_{report_date.replace('-', '')}.md"
        if not report_path.exists():
            raise WorkflowError(f"报告文件未生成: {report_path}")
        summary["report_path"] = str(report_path)

        if args.write_history_base and should_run_step(args, summary, "history_base"):
            if not approval_granted(args.approval_file, report_date):
                raise WorkflowError("写历史全量 Base 需要审批文件，且 approved=true、report_date 必须匹配")
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
                "--approval-file",
                args.approval_file,
            ]
            if args.yes:
                cmd.append("--yes")
            run_command("history_base", cmd, args.base_timeout, summary, dry_run=args.dry_run)
        if args.write_history_base and not args.dry_run:
            summary["history_base_summary"] = load_history_base_summary(report_date)

        if args.sync_independent_base and should_run_step(args, summary, "independent_base"):
            if not approval_granted(args.approval_file, report_date):
                raise WorkflowError("同步独立日期 Base 需要审批文件，且 approved=true、report_date 必须匹配")
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "sync_independent_base.py"),
                "--date",
                report_date,
                "--data-dir",
                str(output_dir),
                "--approval-file",
                args.approval_file,
            ]
            if args.template_base_token:
                cmd.extend(["--template-base-token", args.template_base_token])
            if args.new_base_token:
                cmd.extend(["--new-base-token", args.new_base_token])
            if args.allow_ui_fallback:
                cmd.append("--allow-ui-fallback")
            if args.yes:
                cmd.append("--yes")
            run_command("independent_base", cmd, args.independent_timeout, summary, dry_run=args.dry_run)
        if args.sync_independent_base and not args.dry_run:
            summary["independent_base_summary"] = load_independent_base_summary(report_date)
            summary["checkpoint_status"] = independent_checkpoint_status(summary["independent_base_summary"])

        summary["status"] = "success"
        summary["lark_cli_command_log"] = helper.command_log_summary()
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary_path = write_and_optionally_send_summary(args, summary, report_date, output_dir)
        print(f"\n[完成] workflow success: {summary_path}")
        return 0
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            summary_path = write_and_optionally_send_summary(args, summary, report_date, output_dir)
        except Exception as summary_exc:
            summary["summary_send_error"] = str(summary_exc)
            summary_path = write_summary(summary, report_date, output_dir)
            summary["summary_path"] = str(summary_path)
            summary_path = write_summary(summary, report_date, output_dir)
        print(f"\n[失败] {exc}", file=sys.stderr)
        print(f"summary: {summary_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
