#!/usr/bin/env python3
"""
增强版：准备和写入数据到飞书Base

功能特性：
- 数据预览功能（--preview-only）
- 用户确认机制
- 使用 lark_base_helper.py 辅助函数
- 自动获取字段顺序
- 正确的 Select 选项值处理
- 更好的错误处理和重试机制
- 数据验证
"""

import json
import os
import sys
import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
from urllib.parse import parse_qs, urlparse

# 添加 scripts 目录到路径以便导入辅助模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import lark_base_helper as helper
from config import load_env_safe, LarkConfig, ConfigError


def parse_args():
    parser = argparse.ArgumentParser(description='增强版：准备和写入数据到飞书Base')
    parser.add_argument('--date', type=str, required=True, help='报告日期(格式: YYYY-MM-DD)')
    parser.add_argument('--base-token', type=str, help='飞书Base令牌 (也可通过 LARK_BASE_TOKEN 环境变量设置)')
    parser.add_argument('--table-id', type=str, help='飞书Base表格ID（可选，自动查找或创建）')
    parser.add_argument('--data-dir', type=str, help='查询结果数据目录（自动查找最新的tool-results目录）')
    parser.add_argument('--new-file', type=str, help='新上榜数据JSON文件路径')
    parser.add_argument('--up-file', type=str, help='升幅数据JSON文件路径')
    parser.add_argument('--down-file', type=str, help='降幅数据JSON文件路径')
    parser.add_argument('--preview-only', action='store_true', help='仅预览数据，不写入')
    parser.add_argument('--yes', action='store_true', help='跳过确认直接写入')
    parser.add_argument('--approval-file', type=str, help='写入审批 JSON；必须包含 approved=true 和匹配 report_date')
    parser.add_argument('--repair-table-name', action='store_true', help='指定 --table-id 时将表名修正为报告日期')
    parser.add_argument('--summary-file', type=str, help='写入历史 Base 同步摘要 JSON 路径')
    return parser.parse_args()


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


def default_data_dir(report_date: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tool-results",
        report_date.replace("-", ""),
    )


def find_latest_tool_results_dir() -> str:
    """
    查找最新的 tool-results 目录

    Returns:
        最新的 tool-results 目录路径
    """
    possible_paths = [
        os.path.join(os.getcwd(), "tool-results"),
        os.path.join(os.path.dirname(os.getcwd()), "tool-results"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tool-results"),
    ]

    all_candidates = []
    for path in possible_paths:
        if os.path.exists(path):
            all_candidates.append(path)

    if not all_candidates:
        print("警告: 未找到 tool-results 目录，请使用 --data-dir 指定")
        return os.getcwd()

    # 按修改时间排序，取最新的
    all_candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    latest_dir = all_candidates[0]
    print(f"使用数据目录: {latest_dir}")
    return latest_dir


def find_query_files(data_dir: str,
                    new_file_arg: str = None,
                    up_file_arg: str = None,
                    down_file_arg: str = None) -> Tuple[str, str, str]:
    """
    在指定目录中查找查询结果文件，或使用直接指定的文件

    Args:
        data_dir: 数据目录
        new_file_arg: 直接指定的新上榜文件路径
        up_file_arg: 直接指定的升幅文件路径
        down_file_arg: 直接指定的降幅文件路径

    Returns:
        (new_file, up_file, down_file) 元组
    """
    # 如果直接指定了文件，使用它们
    if new_file_arg and up_file_arg and down_file_arg:
        if os.path.exists(new_file_arg) and os.path.exists(up_file_arg) and os.path.exists(down_file_arg):
            print(f"新上榜文件: {os.path.basename(new_file_arg)}")
            print(f"升幅文件: {os.path.basename(up_file_arg)}")
            print(f"降幅文件: {os.path.basename(down_file_arg)}")
            return new_file_arg, up_file_arg, down_file_arg
        else:
            raise FileNotFoundError("指定的一个或多个数据文件不存在")

    named_files = (
        os.path.join(data_dir, "new_products.json"),
        os.path.join(data_dir, "up_products.json"),
        os.path.join(data_dir, "down_products.json"),
    )
    if all(os.path.exists(path) for path in named_files):
        print(f"新上榜文件: {os.path.basename(named_files[0])}")
        print(f"升幅文件: {os.path.basename(named_files[1])}")
        print(f"降幅文件: {os.path.basename(named_files[2])}")
        return named_files

    raise FileNotFoundError(f"在 {data_dir} 中未找到标准文件 new_products.json/up_products.json/down_products.json")


def read_query_results(new_file: str, up_file: str, down_file: str) -> Tuple[List, List, List]:
    """
    读取查询结果文件

    Args:
        new_file: 新上榜数据文件
        up_file: 升幅数据文件
        down_file: 降幅数据文件

    Returns:
        (new_products, up_products, down_products) 元组
    """
    with open(new_file, 'r', encoding='utf-8') as f:
        new_products = json.loads(json.load(f)[0]['text'])
    with open(up_file, 'r', encoding='utf-8') as f:
        up_products = json.loads(json.load(f)[0]['text'])
    with open(down_file, 'r', encoding='utf-8') as f:
        down_products = json.loads(json.load(f)[0]['text'])

    return new_products, up_products, down_products


def validate_source_dates(report_date: str, *product_lists: List[Dict]) -> List[str]:
    errors = []
    for products in product_lists:
        for i, product in enumerate(products):
            biz_date = str(product.get("business_date", ""))[:10]
            if biz_date and biz_date != report_date:
                errors.append(f"第 {i + 1} 条 business_date={biz_date} 与报告日期 {report_date} 不一致")
    return errors


def normalize_link_key(link: str) -> str:
    parsed = urlparse(link or "")
    params = parse_qs(parsed.query)
    for name in ("id", "itemId", "item_id"):
        if params.get(name):
            return f"id={params[name][0]}"
    return link or ""


def row_to_fields(fields_order: List[str], row: List[Any]) -> Dict[str, Any]:
    return {
        field_name: row[idx] if idx < len(row) else None
        for idx, field_name in enumerate(fields_order)
    }


def scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def row_key_from_fields(fields: Dict[str, Any]) -> Tuple:
    return (
        scalar(fields.get("报告周期")),
        scalar(fields.get("二级类目")),
        scalar(fields.get("三级类目")),
        scalar(fields.get("商品名称")),
        scalar(fields.get("店铺名称")),
        scalar(fields.get("当周排名")),
        scalar(fields.get("异动值")),
        scalar(fields.get("异动类型")),
        normalize_link_key(str(fields.get("商品链接") or "")),
        scalar(fields.get("商品图片URL")),
    )


def expected_counter(fields_order: List[str], rows: List[List[Any]]) -> Counter:
    return Counter(row_key_from_fields(row_to_fields(fields_order, row)) for row in rows)


def existing_counter(records: List[Dict]) -> Counter:
    return Counter(row_key_from_fields(record.get("fields", {})) for record in records)


def verify_or_write_records(base_token: str, table_id: str, fields_order: List[str], rows: List[List[Any]], report_date: str) -> Tuple[int, int, int, str]:
    records = helper.list_records(base_token, table_id)
    if records is None:
        raise RuntimeError("无法读取现有记录，停止写入以避免重复")

    expected = expected_counter(fields_order, rows)
    if records:
        existing = existing_counter(records)
        wrong_date = [
            record for record in records
            if scalar(record.get("fields", {}).get("报告周期")) != report_date
        ]
        if not wrong_date and existing == expected:
            print(f"   表内已有 {len(records)} 条且与本期数据完全一致，跳过写入")
            return len(records), 0, 0, "preexisting_ok"
        raise RuntimeError(
            f"表已有 {len(records)} 条但与本期 {len(rows)} 条期望数据不一致，停止写入以避免重复；"
            f"错误日期记录 {len(wrong_date)} 条"
        )

    success_count, fail_count = helper.batch_create_records(base_token, table_id, fields_order, rows)
    readback = helper.list_records(base_token, table_id)
    if readback is None:
        raise RuntimeError("写入后读回失败")
    if existing_counter(readback) != expected:
        raise RuntimeError(f"写入后读回数据与期望不一致：读回 {len(readback)} 条，期望 {len(rows)} 条")
    return 0, success_count, fail_count, "written"


def history_summary_path(report_date: str, custom_path: str = None) -> str:
    if custom_path:
        return custom_path
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tool-results",
        report_date.replace("-", ""),
        "history_base_summary.json",
    )


def write_history_summary(summary: Dict, report_date: str, custom_path: str = None) -> str:
    path = history_summary_path(report_date, custom_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return path


def resolve_history_table(base_token: str, table_name: str, table_id: str = None, create_missing: bool = True) -> Tuple[str, str]:
    """
    Resolve the history Base table used for the current report date.

    Normal workflow creates the new weekly table from the latest date table
    when it does not exist yet. Preview mode may reuse the latest date table
    only to read field order without mutating Base.
    """
    if table_id:
        print(f"   使用指定表 ID: {table_id}")
        return table_id, "provided"

    exists, existing_table_id = helper.table_exists(base_token, table_name)
    if exists:
        print(f"   表 '{table_name}' 已存在，ID: {existing_table_id}")
        return existing_table_id, "existing"

    if not create_missing:
        latest_table = helper.find_latest_table(base_token)
        if not latest_table:
            raise RuntimeError(f"表 '{table_name}' 不存在，且未找到可用于预览字段顺序的最新日期表")
        print(
            f"   表 '{table_name}' 不存在；预览模式使用最新表 "
            f"'{latest_table['name']}' (ID: {latest_table['id']}) 读取字段顺序"
        )
        return latest_table["id"], "preview_template"

    print(f"   表 '{table_name}' 不存在，自动复制最新日期表结构创建")
    new_table_id, copied = helper.create_table_by_copying_latest(base_token, table_name)
    if not new_table_id:
        raise RuntimeError(f"自动创建表 '{table_name}' 失败，请检查历史 Base 模板表和 lark-cli 权限")
    print(f"   表 '{table_name}' 已自动创建，ID: {new_table_id}")
    return new_table_id, "created"


def get_categories():
    """
    获取类目组合配置

    Returns:
        类目组合列表
    """
    return [
        {"secondary": "直播/摄影配件", "tertiary": "闪光灯 > 相机闪光灯"},
        {"secondary": "直播/摄影配件", "tertiary": "影棚设备 > 影室灯"},
        {"secondary": "直播/摄影配件", "tertiary": "影棚设备 > 外拍灯"},
        {"secondary": "手机配件", "tertiary": "手机直播配件 > 手机直播补光灯"},
        {"secondary": "手机配件", "tertiary": "手机支架/手机座"},
        {"secondary": "手机配件", "tertiary": "手机直播配件 > 直播专用支架"},
        {"secondary": "直播/摄影配件", "tertiary": "脚架/云台 > 脚架"},
        {"secondary": "摄像机配件", "tertiary": "—"},
        {"secondary": "手机配件", "tertiary": "手机拍照配件 > 自拍杆/架"},
    ]


def prepare_data(
    new_products: List,
    up_products: List,
    down_products: List,
    fields_order: List[str],
    date: str
) -> Tuple[List[List], Dict]:
    """
    准备要写入的数据

    Args:
        new_products: 新上榜产品列表
        up_products: 升幅产品列表
        down_products: 降幅产品列表
        fields_order: 字段顺序列表
        date: 报告日期

    Returns:
        (all_rows, summary) 元组
    """
    categories = get_categories()
    all_rows = []
    summary = {
        "categories": [],
        "total_new": 0,
        "total_up": 0,
        "total_down": 0,
    }

    for cat in categories:
        sec = cat["secondary"]
        tert = cat["tertiary"]

        # 筛选该类目的数据
        if sec == "摄像机配件":
            cat_new = [p for p in new_products if p["secondary_category"] == sec]
            cat_up = [p for p in up_products if p["secondary_category"] == sec]
            cat_down = [p for p in down_products if p["secondary_category"] == sec]
        else:
            # 注意：数据库中的三级类目使用原始符号 >
            db_tert = tert.replace("—", "")
            cat_new = [p for p in new_products if p["secondary_category"] == sec and p["tertiary_category"] == db_tert]
            cat_up = [p for p in up_products if p["secondary_category"] == sec and p["tertiary_category"] == db_tert]
            cat_down = [p for p in down_products if p["secondary_category"] == sec and p["tertiary_category"] == db_tert]

        # 记录统计
        cat_summary = {
            "category": f"{sec} / {tert}",
            "new": len(cat_new),
            "up": min(len(cat_up), 15),
            "down": min(len(cat_down), 10),
        }
        summary["categories"].append(cat_summary)
        summary["total_new"] += cat_summary["new"]
        summary["total_up"] += cat_summary["up"]
        summary["total_down"] += cat_summary["down"]

        # 新上榜 - 全部保留
        for p in cat_new:
            row = []
            for field_name in fields_order:
                if field_name == "报告周期":
                    row.append(date)
                elif field_name == "二级类目":
                    row.append([sec])
                elif field_name == "三级类目":
                    row.append([tert])
                elif field_name == "商品名称":
                    row.append(p["commodity_name"])
                elif field_name == "店铺名称":
                    row.append(p["shop_name"])
                elif field_name == "当周排名":
                    row.append(int(p["search_rank"]))
                elif field_name == "异动值":
                    row.append(9999)
                elif field_name == "异动类型":
                    row.append(["新上榜"])
                elif field_name == "商品链接":
                    row.append(p["commodity_link"])
                elif field_name == "商品图片URL":
                    row.append(p["commodity_picture"])
                elif field_name == "附图":
                    row.append([])
                else:
                    row.append(None)
            all_rows.append(row)

        # 升幅 - TOP 15
        cat_up_sorted = sorted(cat_up, key=lambda x: x["ranking_change_value"], reverse=True)
        for p in cat_up_sorted[:15]:
            row = []
            for field_name in fields_order:
                if field_name == "报告周期":
                    row.append(date)
                elif field_name == "二级类目":
                    row.append([sec])
                elif field_name == "三级类目":
                    row.append([tert])
                elif field_name == "商品名称":
                    row.append(p["commodity_name"])
                elif field_name == "店铺名称":
                    row.append(p["shop_name"])
                elif field_name == "当周排名":
                    row.append(int(p["search_rank"]))
                elif field_name == "异动值":
                    row.append(p["ranking_change_value"])
                elif field_name == "异动类型":
                    row.append(["升幅"])
                elif field_name == "商品链接":
                    row.append(p["commodity_link"])
                elif field_name == "商品图片URL":
                    row.append(p["commodity_picture"])
                elif field_name == "附图":
                    row.append([])
                else:
                    row.append(None)
            all_rows.append(row)

        # 降幅 - TOP 10
        cat_down_sorted = sorted(cat_down, key=lambda x: x["ranking_change_value"])
        for p in cat_down_sorted[:10]:
            row = []
            for field_name in fields_order:
                if field_name == "报告周期":
                    row.append(date)
                elif field_name == "二级类目":
                    row.append([sec])
                elif field_name == "三级类目":
                    row.append([tert])
                elif field_name == "商品名称":
                    row.append(p["commodity_name"])
                elif field_name == "店铺名称":
                    row.append(p["shop_name"])
                elif field_name == "当周排名":
                    row.append(int(p["search_rank"]))
                elif field_name == "异动值":
                    row.append(p["ranking_change_value"])
                elif field_name == "异动类型":
                    row.append(["降幅"])
                elif field_name == "商品链接":
                    row.append(p["commodity_link"])
                elif field_name == "商品图片URL":
                    row.append(p["commodity_picture"])
                elif field_name == "附图":
                    row.append([])
                else:
                    row.append(None)
            all_rows.append(row)

    return all_rows, summary


def print_preview(summary: Dict, sample_rows: List[List], fields_order: List[str]):
    """
    打印数据预览

    Args:
        summary: 数据摘要
        sample_rows: 样本行
        fields_order: 字段顺序
    """
    print("\n" + "="*60)
    print("数据预览")
    print("="*60)

    print("\n【数据统计】")
    for cat_sum in summary["categories"]:
        print(f"  {cat_sum['category']}: "
              f"新上榜 {cat_sum['new']} 条, "
              f"升幅 {cat_sum['up']} 条, "
              f"降幅 {cat_sum['down']} 条")

    print(f"\n  总计: 新上榜 {summary['total_new']} 条, "
          f"升幅 {summary['total_up']} 条, "
          f"降幅 {summary['total_down']} 条, "
          f"共 {summary['total_new'] + summary['total_up'] + summary['total_down']} 条")

    print(f"\n【字段顺序】")
    for i, field in enumerate(fields_order):
        print(f"  {i+1}. {field}")

    if sample_rows:
        print(f"\n【样本数据】（前 3 条）")
        for i, row in enumerate(sample_rows[:3]):
            print(f"\n  样本 {i+1}:")
            for field_name, value in zip(fields_order, row):
                # 截断过长的值
                value_str = str(value)
                if len(value_str) > 50:
                    value_str = value_str[:47] + "..."
                print(f"    {field_name}: {value_str}")

    print("\n" + "="*60)


def confirm_write() -> bool:
    """
    询问用户是否确认写入

    Returns:
        是否确认
    """
    try:
        response = input("\n确认写入数据到飞书Base? (y/N): ").strip().lower()
        return response in ('y', 'yes', '是')
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return False


def main():
    args = parse_args()

    # 加载 .env 配置
    load_env_safe()
    try:
        DATE = validate_report_date(args.date)
    except ValueError as exc:
        print(f"错误: {exc}")
        return 1

    needs_approval = (not args.preview_only) or args.repair_table_name
    if needs_approval and not approval_granted(args.approval_file, DATE):
        print("错误: 写入历史 Base 需要审批文件，且 approved=true、report_date 必须匹配", file=sys.stderr)
        return 1

    # 优先使用命令行参数，否则使用环境变量
    if args.base_token:
        BASE_TOKEN = args.base_token
    else:
        try:
            lark_config = LarkConfig.from_env()
            BASE_TOKEN = lark_config.base_token
        except ConfigError as e:
            print(f"[ERROR] 配置加载失败: {e}", file=sys.stderr)
            print("请使用 --base-token 参数或设置 LARK_BASE_TOKEN 环境变量", file=sys.stderr)
            sys.exit(1)

    TABLE_ID = args.table_id

    print("=" * 60)
    print("增强版数据同步工具")
    print("=" * 60)
    print(f"报告日期: {DATE}")
    print(f"Base Token: {BASE_TOKEN[:8]}...{BASE_TOKEN[-4:]}")  # 只显示部分 Token

    # 1. 查找数据文件
    print("\n1. 查找数据文件...")
    data_dir = args.data_dir or default_data_dir(DATE)
    try:
        new_file, up_file, down_file = find_query_files(
            data_dir,
            args.new_file,
            args.up_file,
            args.down_file
        )
    except FileNotFoundError as e:
        print(f"错误: {e}")
        return 1

    # 2. 读取查询结果
    print("\n2. 读取查询结果...")
    try:
        new_products, up_products, down_products = read_query_results(new_file, up_file, down_file)
        date_errors = validate_source_dates(DATE, new_products, up_products, down_products)
        if date_errors:
            print("错误: 查询结果日期与报告日期不一致")
            for err in date_errors[:10]:
                print(f"   - {err}")
            return 1
        print(f"   新上榜: {len(new_products)} 条")
        print(f"   升幅: {len(up_products)} 条")
        print(f"   降幅: {len(down_products)} 条")
    except Exception as e:
        print(f"错误: 读取查询结果失败: {e}")
        return 1

    # 3. 检查表是否存在或自动创建
    print("\n3. 检查飞书Base表...")
    try:
        TABLE_ID, table_status = resolve_history_table(
            BASE_TOKEN,
            DATE,
            TABLE_ID,
            create_missing=not args.preview_only,
        )
    except Exception as e:
        print(f"错误: {e}")
        return 1
    if args.repair_table_name and args.table_id:
        renamed, rename_error = helper.update_table_name(BASE_TOKEN, TABLE_ID, DATE)
        if renamed:
            print(f"   已将表名修正为 {DATE}")
        else:
            print(f"   警告: 表名修正失败: {rename_error}")

    # 4. 获取字段顺序
    print("\n4. 获取字段顺序...")
    fields_order = helper.get_field_order(BASE_TOKEN, TABLE_ID)
    if not fields_order:
        print("错误: 获取字段顺序失败")
        return 1
    print(f"   字段顺序: {fields_order}")

    # 5. 准备数据
    print("\n5. 准备数据...")
    all_rows, summary = prepare_data(new_products, up_products, down_products, fields_order, DATE)
    print(f"   共准备 {len(all_rows)} 条记录")

    # 6. 预览数据
    print_preview(summary, all_rows[:3], fields_order)

    if args.preview_only:
        print("\n预览模式，不写入数据")
        return 0

    # 7. 确认写入
    if not args.yes:
        if not confirm_write():
            print("\n已取消写入")
            return 0

    # 8. 写入数据
    print("\n6. 写入数据...")
    try:
        preexisting, success_count, fail_count, write_status = verify_or_write_records(
            BASE_TOKEN, TABLE_ID, fields_order, all_rows, DATE
        )
    except RuntimeError as e:
        print(f"错误: {e}")
        return 1

    server_counts, server_count_error = helper.aggregate_change_type_counts(BASE_TOKEN, TABLE_ID, DATE)
    summary_payload = {
        "date": DATE,
        "base_token_present": bool(BASE_TOKEN),
        "table_id": TABLE_ID,
        "table_status": table_status,
        "write_status": write_status,
        "preexisting": preexisting,
        "written": success_count,
        "write_failed": fail_count,
        "expected_rows": len(all_rows),
        "expected_change_type_counts": {
            "新上榜": summary["total_new"],
            "升幅": summary["total_up"],
            "降幅": summary["total_down"],
        },
        "server_side_change_type_counts": server_counts,
        "server_side_validation": {
            "status": "ok" if server_counts else "deferred",
            "error": server_count_error,
        },
        "lark_cli": {
            "version": helper.lark_cli_version(),
            "command_log": helper.command_log_summary(),
        },
    }
    summary_path = write_history_summary(summary_payload, DATE, args.summary_file)

    print(f"\n完成！状态 {write_status}，已有 {preexisting} 条，成功写入 {success_count} 条，失败 {fail_count} 条")
    print("飞书Base链接: <redacted; see LARK_BASE_TOKEN>")
    print(f"历史 Base 摘要: {summary_path}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
