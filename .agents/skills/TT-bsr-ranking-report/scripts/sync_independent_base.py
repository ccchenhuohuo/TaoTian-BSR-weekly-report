#!/usr/bin/env python3
"""
Copy, write, and verify the independent per-date Feishu Base.
"""

import argparse
import collections
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import lark_base_helper as helper
from config import load_env_safe
from prepare_and_write_data_v2 import (
    existing_counter,
    expected_counter,
    find_query_files,
    read_query_results,
    scalar,
    validate_source_dates,
)


VIEW_TO_CATEGORY = {
    "闪光灯 > 相机闪光灯": ("直播/摄影配件", "闪光灯 > 相机闪光灯"),
    "影棚设备 > 影室灯": ("直播/摄影配件", "影棚设备 > 影室灯"),
    "影棚设备 > 外拍灯": ("直播/摄影配件", "影棚设备 > 外拍灯"),
    "手机直播配件 > 手机直播补光灯": ("手机配件", "手机直播配件 > 手机直播补光灯"),
    "手机支架/手机座": ("手机配件", "手机支架/手机座"),
    "手机直播配件 > 直播专用支架": ("手机配件", "手机直播配件 > 直播专用支架"),
    "手机拍照配件 > 自拍杆/架": ("手机配件", "手机拍照配件 > 自拍杆/架"),
    "脚架/云台 > 脚架": ("直播/摄影配件", "脚架/云台 > 脚架"),
    "摄像机配件": ("摄像机配件", "—"),
}
BASE_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+\.feishu\.cn/base/[A-Za-z0-9]+")
BASE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9]{20,}\b")
SECRET_KEY_RE = re.compile(r'("(?:[^"]*(?:token|password|secret|api_key|authorization)[^"]*)"\s*:\s*)"[^"]*"', re.I)
SENSITIVE_KEY_RE = re.compile(r"(token|password|secret|api_key|authorization)", re.I)


def parse_args():
    parser = argparse.ArgumentParser(description="Sync the independent per-date BSR Base")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--template-base-token", help="Template independent Base token")
    parser.add_argument("--new-base-token", help="Existing copied Base token. If omitted, copy template.")
    parser.add_argument("--data-dir", help="Directory containing new/up/down product JSON files")
    parser.add_argument("--new-file", help="new_products.json path")
    parser.add_argument("--up-file", help="up_products.json path")
    parser.add_argument("--down-file", help="down_products.json path")
    parser.add_argument("--yes", action="store_true", help="Write without confirmation")
    parser.add_argument("--approval-file", help="Write approval JSON; must contain approved=true and matching report_date")
    parser.add_argument("--allow-ui-fallback", action="store_true", help="Allow Base folder rename UI fallback without failing")
    parser.add_argument("--skip-template-validation", action="store_true", help="Skip template field/view validation.")
    parser.add_argument("--strict-template-validation", action="store_true", help="Fail when template validation is deferred or mismatched.")
    parser.add_argument("--no-repair-view-order", action="store_true", help="Do not repair view visible field order.")
    parser.add_argument("--summary-file", help="Write summary to a custom JSON path.")
    return parser.parse_args()


def normalize_date_name(report_date: str) -> str:
    return report_date.replace("-", "")[2:]


def validate_report_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


def approval_granted(path: str, report_date: str) -> bool:
    if not path:
        return False
    approval_path = Path(path)
    if not approval_path.exists():
        return False
    with approval_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return bool(payload.get("approved")) and payload.get("report_date") == report_date


def summary_output_path(report_date: str, custom_path: str = None) -> Path:
    if custom_path:
        return Path(custom_path)
    ymd = report_date.replace("-", "")
    return Path(__file__).parent.parent / "tool-results" / f"{ymd}_independent_base_summary.json"


def write_summary(summary: Dict, report_date: str, custom_path: str = None) -> Path:
    output_path = summary_output_path(report_date, custom_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(redact_obj(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def redact_text(value: str) -> str:
    if not value:
        return value
    value = SECRET_KEY_RE.sub(r'\1"<redacted>"', value)
    value = BASE_URL_RE.sub("https://<feishu-base-redacted>", value)
    return BASE_TOKEN_RE.sub("<redacted-token>", value)


def redact_obj(value):
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


def resolve_template_base_token(report_date: str, explicit_token: str = None) -> Tuple[str, str]:
    if explicit_token:
        return explicit_token, "argument"
    env_token = os.environ.get("LARK_INDEPENDENT_TEMPLATE_BASE_TOKEN")
    if env_token:
        return env_token, "environment"

    tool_results = Path(__file__).parent.parent / "tool-results"
    candidates = sorted(tool_results.glob("*_independent_base_summary.json"), reverse=True)
    for path in candidates:
        if report_date.replace("-", "") in path.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        token = (payload.get("new_base") or {}).get("token")
        if token:
            return token, f"summary:{path.name}"

    memory_path = Path.home() / ".codex" / "automations" / "bsr" / "memory.md"
    if memory_path.exists():
        text = memory_path.read_text(encoding="utf-8")
        match = re.search(r"Independent Base: new token `([^`]+)`", text)
        if match:
            return match.group(1), "automation_memory"
    return "", ""


def get_tables_by_name(base_token: str) -> Dict[str, str]:
    tables = helper.list_all_tables(base_token)
    if tables is None:
        raise RuntimeError("无法读取 Base 表列表")
    return {table["name"]: table["id"] for table in tables}


def get_single_view(base_token: str, table_id: str) -> Tuple[str, str]:
    views = helper.list_views(base_token, table_id)
    if not views:
        raise RuntimeError(f"表 {table_id} 无可用视图")
    return views[0]["id"], views[0]["name"]


def filter_category(products: List[Dict], sec: str, tert: str) -> List[Dict]:
    if sec == "摄像机配件":
        return [p for p in products if p["secondary_category"] == sec]
    return [
        p for p in products
        if p["secondary_category"] == sec and (p.get("tertiary_category") or "") == tert
    ]


def build_row(fields_order: List[str], report_date: str, sec: str, tert: str, product: Dict, change_type: str) -> List:
    row = []
    for field_name in fields_order:
        if field_name == "报告周期":
            row.append(report_date)
        elif field_name == "二级类目":
            row.append([sec])
        elif field_name == "三级类目":
            row.append([tert])
        elif field_name == "商品名称":
            row.append(product["commodity_name"])
        elif field_name == "店铺名称":
            row.append(product["shop_name"])
        elif field_name == "当周排名":
            row.append(int(product["search_rank"]))
        elif field_name == "异动值":
            row.append(9999 if change_type == "新上榜" else int(product["ranking_change_value"]))
        elif field_name == "异动类型":
            row.append([change_type])
        elif field_name == "商品链接":
            row.append(product["commodity_link"])
        elif field_name == "商品图片URL":
            row.append(product["commodity_picture"])
        elif field_name in ("附图", "补充图"):
            row.append([])
        else:
            row.append(None)
    return row


def rows_for_category(
    fields_order: List[str],
    report_date: str,
    sec: str,
    tert: str,
    new_products: List[Dict],
    up_products: List[Dict],
    down_products: List[Dict],
) -> List[List]:
    cat_new = filter_category(new_products, sec, tert)
    cat_up = sorted(filter_category(up_products, sec, tert), key=lambda p: p["ranking_change_value"], reverse=True)[:15]
    cat_down = sorted(filter_category(down_products, sec, tert), key=lambda p: p["ranking_change_value"])[:10]

    rows = [build_row(fields_order, report_date, sec, tert, p, "新上榜") for p in cat_new]
    rows.extend(build_row(fields_order, report_date, sec, tert, p, "升幅") for p in cat_up)
    rows.extend(build_row(fields_order, report_date, sec, tert, p, "降幅") for p in cat_down)
    return rows


def duplicate_count(records: List[Dict]) -> int:
    counter = collections.Counter()
    for record in records:
        fields = record.get("fields", {})
        key = (
            fields.get("报告周期", ""),
            tuple(fields.get("二级类目", []) or []),
            tuple(fields.get("三级类目", []) or []),
            tuple(fields.get("异动类型", []) or []),
            fields.get("商品链接", ""),
        )
        counter[key] += 1
    return sum(value - 1 for value in counter.values() if value > 1)


def change_type_counts(records: List[Dict]) -> Dict[str, int]:
    counter = collections.Counter()
    for record in records:
        change_type = (record.get("fields", {}).get("异动类型") or [""])[0]
        counter[change_type] += 1
    return dict(counter)


def write_if_empty(base_token: str, table_id: str, fields_order: List[str], rows: List[List], report_date: str) -> Tuple[int, int, int, str]:
    records = helper.list_records(base_token, table_id)
    if records is None:
        raise RuntimeError(f"无法读取表 {table_id} 现有记录")
    expected = expected_counter(fields_order, rows)
    if len(records) > 0:
        wrong_date = [
            record for record in records
            if scalar(record.get("fields", {}).get("报告周期")) != report_date
        ]
        if not wrong_date and existing_counter(records) == expected:
            return len(records), 0, 0, "preexisting_ok"
        return len(records), 0, 1, "preexisting_mismatch"
    success, fail = helper.batch_create_records(base_token, table_id, fields_order, rows)
    status = "written" if fail == 0 and success == len(rows) else "write_failed"
    return 0, success, fail, status


def blocking_issues_for_table(table_name: str, expected_rows: int, record_count: int, preexisting: int, write_status: str, duplicates: int) -> List[str]:
    issues = []
    if write_status == "preexisting_mismatch":
        issues.append(f"{table_name}: 表已有 {preexisting} 条但与本期 {expected_rows} 条期望数据不一致，跳过写入以避免重复")
    if record_count != expected_rows:
        issues.append(f"{table_name}: 读回记录数 {record_count} 与期望 {expected_rows} 不一致")
    if duplicates:
        issues.append(f"{table_name}: 发现 {duplicates} 条重复记录")
    return issues


def validate_view_order(template_base: str, new_base: str, template_table_id: str, new_table_id: str, repair: bool = True) -> Dict:
    template_view_id, template_view_name = get_single_view(template_base, template_table_id)
    new_view_id, new_view_name = get_single_view(new_base, new_table_id)
    visible_result = helper.validate_and_repair_view_visible_fields(
        template_base,
        new_base,
        template_table_id,
        new_table_id,
        template_view_id,
        new_view_id,
        repair=repair,
    )
    return {
        "view_name_ok": template_view_name == new_view_name,
        "view_visible_order_ok": bool(visible_result.get("ok")),
        "view_visible_status": visible_result.get("status"),
        "view_visible_result": visible_result,
        "template_view_name": template_view_name,
        "new_view_name": new_view_name,
    }


def add_validation_result(summary: Dict, table_name: str, result: Dict, strict: bool) -> None:
    summary["new_base"]["view_name_validation"][table_name] = result.get("view_name_ok")
    summary["new_base"]["view_visible_order_validation"][table_name] = result.get("view_visible_order_ok")
    summary["new_base"]["template_validation_details"][table_name] = result

    status = result.get("view_visible_status")
    if not result.get("view_name_ok"):
        message = f"{table_name}: 视图名称与模板不一致"
        if strict:
            summary["blocking_issues"].append(message)
        else:
            summary["warnings"].append(message)
    if status == "validation_deferred":
        summary["deferred_validations"].append(f"{table_name}: 视图可见字段顺序校验延后")
        if strict:
            summary["blocking_issues"].append(f"{table_name}: 视图可见字段顺序无法确认")
    elif not result.get("view_visible_order_ok"):
        message = f"{table_name}: 视图可见字段顺序与模板不一致或修复失败"
        if strict:
            summary["blocking_issues"].append(message)
        else:
            summary["warnings"].append(message)


def main() -> int:
    args = parse_args()
    load_env_safe()
    try:
        report_date = validate_report_date(args.date)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if not approval_granted(args.approval_file, report_date):
        print("错误: 同步独立日期 Base 需要审批文件，且 approved=true、report_date 必须匹配", file=sys.stderr)
        return 1

    template_base_token, template_source = resolve_template_base_token(report_date, args.template_base_token)
    if not template_base_token and not args.new_base_token:
        print("错误: 需要 --template-base-token 或 --new-base-token", file=sys.stderr)
        return 1

    ymd = report_date.replace("-", "")
    data_dir = args.data_dir or str(Path(__file__).parent.parent / "tool-results" / ymd)
    new_file, up_file, down_file = find_query_files(data_dir, args.new_file, args.up_file, args.down_file)
    new_products, up_products, down_products = read_query_results(new_file, up_file, down_file)
    date_errors = validate_source_dates(report_date, new_products, up_products, down_products)
    if date_errors:
        print("错误: 查询结果日期与报告日期不一致", file=sys.stderr)
        for err in date_errors[:10]:
            print(f"  - {err}", file=sys.stderr)
        return 1

    new_base_token = args.new_base_token
    new_base_url = None
    summary = {
        "date": report_date,
        "template_base": {
            "token_present": bool(template_base_token),
            "source": template_source,
        },
        "new_base": {
            "token_present": bool(new_base_token),
            "url_available": bool(new_base_token),
            "folder_rename": {},
            "table_counts": {},
            "full_table_change_type_counts": {},
            "view_name_validation": {},
            "view_visible_order_validation": {},
            "template_validation_details": {},
            "lark_cli": {
                "version": helper.lark_cli_version(),
            },
        },
        "warnings": [],
        "deferred_validations": [],
        "manual_actions": [],
        "issues": [],
        "blocking_issues": [],
    }
    if not new_base_token:
        new_name = f"{normalize_date_name(report_date)}淘天BSR榜单异动数据统计"
        if not args.yes:
            response = input(f"确认复制独立 Base 为 {new_name}? (y/N): ").strip().lower()
            if response not in ("y", "yes", "是"):
                print("已取消")
                return 0
        copied_base, error = helper.copy_base(template_base_token, new_name, without_content=True)
        if error or not copied_base:
            print(f"错误: 复制 Base 失败: {error}", file=sys.stderr)
            return 1
        new_base_token = copied_base["base_token"]
        new_base_url = copied_base.get("url")
        summary["new_base"]["token_present"] = bool(new_base_token)
        summary["new_base"]["url_available"] = True
        summary["new_base"]["copy_status"] = "copied"
        write_summary(summary, report_date, args.summary_file)
    else:
        summary["new_base"]["token_present"] = bool(new_base_token)
        summary["new_base"]["url_available"] = bool(new_base_token)
        summary["new_base"]["copy_status"] = "provided"

    folder_rename = helper.rename_date_folder_if_possible(new_base_token, report_date)
    summary["new_base"]["folder_rename"] = folder_rename
    if folder_rename.get("status") in ("needs_auth_scope", "needs_ui_fallback"):
        summary["manual_actions"].append(folder_rename.get("message"))
        if folder_rename.get("auth_hint"):
            summary["manual_actions"].append(folder_rename.get("auth_hint"))

    template_tables = get_tables_by_name(template_base_token) if template_base_token else {}
    new_tables = get_tables_by_name(new_base_token)
    required_tables = [str(i) for i in range(1, 10)] + ["全量数据"]
    missing = [name for name in required_tables if name not in new_tables]
    if missing:
        raise RuntimeError(f"新 Base 缺少表: {missing}")

    full_rows = []
    for table_name in [str(i) for i in range(1, 10)]:
        table_id = new_tables[table_name]
        _, view_name = get_single_view(new_base_token, table_id)
        if view_name not in VIEW_TO_CATEGORY:
            raise RuntimeError(f"表 {table_name} 视图名无法映射类目: {view_name}")
        sec, tert = VIEW_TO_CATEGORY[view_name]
        fields_order = helper.get_field_order(new_base_token, table_id)
        rows = rows_for_category(fields_order, report_date, sec, tert, new_products, up_products, down_products)
        full_rows.extend((sec, tert, row) for row in rows)
        preexisting, written, failed, write_status = write_if_empty(new_base_token, table_id, fields_order, rows, report_date)
        records = helper.list_records(new_base_token, table_id) or []
        duplicates = duplicate_count(records)

        summary["new_base"]["table_counts"][table_name] = {
            "view_name": view_name,
            "expected": len(rows),
            "preexisting": preexisting,
            "written": written,
            "write_failed": failed,
            "write_status": write_status,
            "count": len(records),
            "duplicates": duplicates,
        }
        summary["blocking_issues"].extend(
            blocking_issues_for_table(table_name, len(rows), len(records), preexisting, write_status, duplicates)
        )

    full_table_id = new_tables["全量数据"]
    full_fields_order = helper.get_field_order(new_base_token, full_table_id)
    full_rows_projected = []
    for table_name in [str(i) for i in range(1, 10)]:
        table_id = new_tables[table_name]
        _, view_name = get_single_view(new_base_token, table_id)
        sec, tert = VIEW_TO_CATEGORY[view_name]
        full_rows_projected.extend(
            rows_for_category(full_fields_order, report_date, sec, tert, new_products, up_products, down_products)
        )

    preexisting, written, failed, write_status = write_if_empty(new_base_token, full_table_id, full_fields_order, full_rows_projected, report_date)
    full_records = helper.list_records(new_base_token, full_table_id) or []
    full_duplicates = duplicate_count(full_records)
    summary["new_base"]["table_counts"]["全量数据"] = {
        "view_name": get_single_view(new_base_token, full_table_id)[1],
        "expected": len(full_rows_projected),
        "preexisting": preexisting,
        "written": written,
        "write_failed": failed,
        "write_status": write_status,
        "count": len(full_records),
        "duplicates": full_duplicates,
    }
    summary["blocking_issues"].extend(
        blocking_issues_for_table("全量数据", len(full_rows_projected), len(full_records), preexisting, write_status, full_duplicates)
    )
    summary["new_base"]["full_table_change_type_counts"] = change_type_counts(full_records)
    if template_base_token and template_tables and not args.skip_template_validation:
        for table_name in [str(i) for i in range(1, 10)] + ["全量数据"]:
            if table_name not in template_tables or table_name not in new_tables:
                summary["warnings"].append(f"{table_name}: 模板或新 Base 缺少同名表，跳过模板校验")
                continue
            try:
                result = validate_view_order(
                    template_base_token,
                    new_base_token,
                    template_tables[table_name],
                    new_tables[table_name],
                    repair=not args.no_repair_view_order,
                )
                add_validation_result(summary, table_name, result, args.strict_template_validation)
            except Exception as exc:
                message = f"{table_name}: 模板视图校验异常，已延后: {exc}"
                summary["deferred_validations"].append(message)
                if args.strict_template_validation:
                    summary["blocking_issues"].append(message)
    elif args.skip_template_validation:
        summary["deferred_validations"].append("已按参数跳过模板字段/视图校验")

    summary["new_base"]["all_view_name_ok"] = all(summary["new_base"]["view_name_validation"].values()) if summary["new_base"]["view_name_validation"] else None
    summary["new_base"]["all_view_visible_order_ok"] = all(summary["new_base"]["view_visible_order_validation"].values()) if summary["new_base"]["view_visible_order_validation"] else None
    summary["new_base"]["lark_cli"]["command_log"] = helper.command_log_summary()

    output_path = write_summary(summary, report_date, args.summary_file)
    print(json.dumps(redact_obj(summary), ensure_ascii=False, indent=2))
    print(f"summary: {output_path}")
    has_write_failures = any(v.get("write_failed", 0) for v in summary["new_base"]["table_counts"].values())
    return 1 if has_write_failures or summary["blocking_issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
