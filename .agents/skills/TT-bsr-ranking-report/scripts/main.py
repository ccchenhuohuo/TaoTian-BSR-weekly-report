#!/usr/bin/env python3
"""
淘天BSR榜单监测快报 - 主流程整合脚本

功能：
1. 检查数据同步状态
2. 指导用户执行 Doris 查询并保存结果
3. 生成报告
4. 同步到飞书 Base

使用方法：
    # 完整流程
    python3 scripts/main.py --date 2026-04-13

    # 仅检查同步状态
    python3 scripts/main.py --date 2026-04-13 --check-sync

    # 指定数据文件路径
    python3 scripts/main.py --date 2026-04-13 \
        --new-file new_products.json \
        --up-file up_products.json \
        --down-file down_products.json
"""

import json
import os
import sys
import argparse
import subprocess
from datetime import datetime
from typing import List, Dict, Any


def check_sync_status() -> bool:
    """执行数据同步；sync_data.py 无新增时会直接成功退出。"""
    print("检查并同步 Doris 数据...")
    script_path = os.path.join(os.path.dirname(__file__), "sync_data.py")
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode == 0


def validate_report_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


def get_categories() -> List[Dict]:
    """获取类目组合配置"""
    return [
        {"secondary": "直播/摄影配件", "tertiary": "闪光灯 > 相机闪光灯"},
        {"secondary": "直播/摄影配件", "tertiary": "影棚设备 > 影室灯"},
        {"secondary": "直播/摄影配件", "tertiary": "影棚设备 > 外拍灯"},
        {"secondary": "手机配件", "tertiary": "手机直播配件 > 手机直播补光灯"},
        {"secondary": "手机配件", "tertiary": "手机支架/手机座"},
        {"secondary": "手机配件", "tertiary": "手机直播配件 > 直播专用支架"},
        {"secondary": "直播/摄影配件", "tertiary": "脚架/云台 > 脚架"},
        {"secondary": "摄像机配件", "tertiary": ""},
        {"secondary": "手机配件", "tertiary": "手机拍照配件 > 自拍杆/架"}
    ]


def load_json_data(file_path: str) -> List[Dict]:
    """从JSON文件加载数据"""
    if not os.path.exists(file_path):
        print(f"警告: 文件不存在: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        # 如果是MCP工具结果格式，提取data字段
        if isinstance(data, dict) and 'data' in data:
            return data['data']
        # 如果是包装格式 [{"text": "..."}]
        elif isinstance(data, list) and len(data) > 0 and 'text' in data[0]:
            return json.loads(data[0]['text'])
        return data


def print_query_instructions(date: str, output_dir: str):
    """打印查询说明"""
    print("\n" + "="*80)
    print("【Step 1-2】执行 Doris 查询")
    print("="*80)
    print(f"\n请使用 Doris MCP 执行以下查询，并将结果保存为 JSON 文件：")
    print(f"\n保存目录: {output_dir}")
    print("\n查询顺序:")
    print("  1. 模板四：各组合数据统计（汇总）")
    print("  2. 模板一：新上榜产品 (ranking_change_value = 9999)")
    print("  3. 模板二：升幅较大产品 (ranking_change_value > 0 AND != 9999)")
    print("  4. 模板三：降幅较大产品 (ranking_change_value < 0)")
    print(f"\nSQL 模板位置: references/query_ranking_change_doris.md")
    print(f"\n⚠️  重要提示:")
    print(f"  - 日期占位符 :latest_week 替换为 '{date}'")
    print(f"  - SQL 中不要使用末尾分号 ';'")
    print(f"  - 使用 mcp__doris__exec_query 工具执行查询")
    print(f"\n查询完成后，请将结果保存为以下文件:")
    print(f"  1. {os.path.join(output_dir, 'new_products.json')} (新上榜产品)")
    print(f"  2. {os.path.join(output_dir, 'up_products.json')} (升幅产品)")
    print(f"  3. {os.path.join(output_dir, 'down_products.json')} (降幅产品)")
    print(f"\n然后重新运行此脚本继续执行。")


def load_summary_counts(output_dir: str, date: str) -> Dict[str, int]:
    path = os.path.join(output_dir, "summary_counts.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"缺少 summary_counts.json: {path}")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("date") != date:
        raise ValueError(f"summary_counts.json 日期 {payload.get('date')} 与报告日期 {date} 不一致")
    return {key: int(value) for key, value in payload.get("counts", {}).items()}


def validate_loaded_dates(date: str, *product_lists: List[Dict]) -> List[str]:
    errors = []
    for products in product_lists:
        for i, product in enumerate(products[:50]):
            biz_date = str(product.get("business_date", ""))[:10]
            if biz_date and biz_date != date:
                errors.append(f"第 {i + 1} 条 business_date={biz_date} 与报告日期 {date} 不一致")
    return errors


def generate_report(date: str, new_products: List, up_products: List, down_products: List, summary_counts: Dict[str, int] = None) -> str:
    """生成报告"""
    categories = get_categories()

    # 按类目分组数据
    category_data = {}
    for cat in categories:
        cat_key = f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']
        category_data[cat_key] = {
            "new": [],
            "up": [],
            "down": []
        }

    # 分组新上榜产品
    for product in new_products:
        sec = product['secondary_category']
        tert = product['tertiary_category']
        cat_key = f"{sec} - {tert}" if tert else sec
        if cat_key in category_data:
            category_data[cat_key]["new"].append(product)

    # 分组升幅产品
    for product in up_products:
        sec = product['secondary_category']
        tert = product['tertiary_category']
        cat_key = f"{sec} - {tert}" if tert else sec
        if cat_key in category_data:
            category_data[cat_key]["up"].append(product)

    # 分组降幅产品
    for product in down_products:
        sec = product['secondary_category']
        tert = product['tertiary_category']
        cat_key = f"{sec} - {tert}" if tert else sec
        if cat_key in category_data:
            category_data[cat_key]["down"].append(product)

    # 渲染汇总表
    report = f"# 淘天BSR榜单周监测报告 ({date})\n\n"
    report += """## 汇总表

| # | 二级类目 | 三级类目 | 最新周数据量 | 新上榜 | 升幅 | 降幅 |
|:---:|---------|---------|:---:|:---:|:---:|:---:|
"""
    total_count = 0
    total_new = 0
    total_up = 0
    total_down = 0
    missing_counts = [
        f"{cat['secondary']} - {cat['tertiary']}" if cat["tertiary"] else cat["secondary"]
        for cat in categories
        if not summary_counts or (f"{cat['secondary']} - {cat['tertiary']}" if cat["tertiary"] else cat["secondary"]) not in summary_counts
    ]
    if missing_counts:
        raise ValueError(f"summary_counts.json 缺少类目计数: {', '.join(missing_counts)}")

    for i, cat in enumerate(categories, 1):
        cat_key = f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']
        data_count = summary_counts[cat_key]
        new_count = len(category_data[cat_key]["new"])
        up_count = len(category_data[cat_key]["up"])
        down_count = len(category_data[cat_key]["down"])

        total_count += data_count
        total_new += new_count
        total_up += up_count
        total_down += down_count

        display_tert = cat['tertiary'] if cat['tertiary'] else "—"
        report += f"| {i} | {cat['secondary']} | {display_tert} | {data_count} | {new_count} | {up_count} | {down_count} |\n"

    report += f"| **合计** | | | **{total_count}** | **{total_new}** | **{total_up}** | **{total_down}** |\n\n"

    # 渲染异动明细
    report += "## 异动明细\n\n"

    for cat in categories:
        cat_key = f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']
        data = category_data[cat_key]

        display_key = cat_key if cat['tertiary'] else cat['secondary']
        report += f"### {display_key}\n\n"

        # 新上榜TOP5
        if data["new"]:
            report += "新上榜 TOP5：\n"
            report += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            report += "|---------|---------|:-------:|:------:|\n"
            for product in data["new"][:5]:
                report += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | 新上榜 |\n"
            report += "\n"

        # 升幅TOP5
        if data["up"]:
            sorted_up = sorted(data["up"], key=lambda x: x['ranking_change_value'], reverse=True)
            report += "升幅 TOP5：\n"
            report += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            report += "|---------|---------|:-------:|:------:|\n"
            for product in sorted_up[:5]:
                report += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | +{product['ranking_change_value']} |\n"
            report += "\n"

        # 降幅TOP3
        if data["down"]:
            sorted_down = sorted(data["down"], key=lambda x: x['ranking_change_value'])
            report += "降幅 TOP3：\n"
            report += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            report += "|---------|---------|:-------:|:------:|\n"
            for product in sorted_down[:3]:
                report += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | {product['ranking_change_value']} |\n"
            report += "\n"

    return report


def main():
    parser = argparse.ArgumentParser(description='淘天BSR榜单监测快报主流程')
    parser.add_argument('--date', type=str, required=True, help='报告日期(格式: YYYY-MM-DD)')
    parser.add_argument('--check-sync', action='store_true', help='仅检查数据同步状态')
    parser.add_argument('--data-dir', type=str, help='查询结果数据目录')
    parser.add_argument('--new-file', type=str, help='新上榜数据JSON文件路径')
    parser.add_argument('--up-file', type=str, help='升幅数据JSON文件路径')
    parser.add_argument('--down-file', type=str, help='降幅数据JSON文件路径')
    args = parser.parse_args()

    try:
        DATE = validate_report_date(args.date)
    except ValueError as exc:
        print(f"错误: {exc}")
        return 1

    print("="*80)
    print("淘天BSR榜单监测快报")
    print("="*80)
    print(f"报告日期: {DATE}")

    # Step 0: 检查数据同步
    print("\n【Step 0】检查数据同步状态...")
    if not check_sync_status():
        print("错误: 数据同步失败")
        print("\n请先运行: python3 scripts/sync_data.py")
        return 1

    if args.check_sync:
        print("\n仅检查同步状态，退出。")
        return 0

    # 确定数据文件路径
    default_output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tool-results",
        DATE.replace("-", "")
    )
    output_dir = args.data_dir or default_output_dir
    new_file = args.new_file or os.path.join(output_dir, "new_products.json")
    up_file = args.up_file or os.path.join(output_dir, "up_products.json")
    down_file = args.down_file or os.path.join(output_dir, "down_products.json")

    # 检查数据文件是否存在
    has_data = os.path.exists(new_file) and os.path.exists(up_file) and os.path.exists(down_file)

    if not has_data:
        print("\n【Step 1-2】自动查询 Doris 并生成报告数据...")
        query_script = os.path.join(os.path.dirname(__file__), "query_report_data.py")
        result = subprocess.run(
            [sys.executable, query_script, "--date", DATE, "--output-dir", output_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            print_query_instructions(DATE, output_dir)
            return result.returncode
        has_data = os.path.exists(new_file) and os.path.exists(up_file) and os.path.exists(down_file)
        if not has_data:
            print("错误: Doris 查询脚本完成后仍未生成完整的 new/up/down JSON 文件")
            print_query_instructions(DATE, output_dir)
            return 1

    # Step 3: 加载数据并生成报告
    print("\n【Step 3】加载数据...")
    new_products = load_json_data(new_file)
    up_products = load_json_data(up_file)
    down_products = load_json_data(down_file)

    print(f"  新上榜: {len(new_products)} 条")
    print(f"  升幅: {len(up_products)} 条")
    print(f"  降幅: {len(down_products)} 条")

    if new_products is None or up_products is None or down_products is None:
        print("\n错误: 数据文件格式不正确")
        return 1
    date_errors = validate_loaded_dates(DATE, new_products, up_products, down_products)
    if date_errors:
        print("\n错误: 数据文件日期与报告日期不一致")
        for err in date_errors[:10]:
            print(f"  - {err}")
        return 1
    try:
        summary_counts = load_summary_counts(output_dir, DATE)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n错误: {e}")
        return 1

    # 生成报告
    print("\n【Step 4】生成报告...")
    try:
        report = generate_report(DATE, new_products, up_products, down_products, summary_counts)
    except ValueError as e:
        print(f"\n错误: {e}")
        return 1

    # 保存报告
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "report_collection")
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)
    report_file = os.path.join(report_dir, f"bsr_ranking_report_{DATE.replace('-', '')}.md")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"报告已生成：{report_file}")

    # 显示报告预览
    print("\n" + "="*80)
    print("报告预览")
    print("="*80)
    print("\n".join(report.split("\n")[:50]))
    if len(report.split("\n")) > 50:
        print("... (更多内容请查看完整报告)")

    print("\n" + "="*80)
    print("【Step 5】接下来的步骤")
    print("="*80)
    print("\n1. 请检查报告内容是否满意")
    print("\n2. 如满意，继续执行飞书Base同步:")
    print(f"   python3 scripts/prepare_and_write_data_v2.py --date {DATE} \\\n"
          f"       --approval-file /secure/path/tt-bsr-approval.json \\\n"
          f"       --new-file {new_file} \\\n"
          f"       --up-file {up_file} \\\n"
          f"       --down-file {down_file}")
    print("\n3. 如不满意，调整查询条件后重新生成")

    return 0


if __name__ == "__main__":
    sys.exit(main())
