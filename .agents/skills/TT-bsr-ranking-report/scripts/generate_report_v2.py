#!/usr/bin/env python3
"""
生成淘天BSR榜单周监测报告（增强版）

功能特性：
- 自动查找最新的 tool-results 目录
- 数据验证（检查数据完整性）
- 数据预览输出
- 更好的错误处理
"""

import json
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any, Tuple


def parse_args():
    parser = argparse.ArgumentParser(description='生成淘天BSR榜单周监测报告（增强版）')
    parser.add_argument('--date', type=str, required=True, help='报告日期(格式: YYYY-MM-DD)')
    parser.add_argument('--data-dir', type=str, help='查询结果数据目录（自动查找最新的tool-results目录）')
    parser.add_argument('--new-file', type=str, help='新上榜数据JSON文件路径')
    parser.add_argument('--up-file', type=str, help='升幅数据JSON文件路径')
    parser.add_argument('--down-file', type=str, help='降幅数据JSON文件路径')
    parser.add_argument('--preview', action='store_true', help='仅预览数据，不保存文件')
    return parser.parse_args()


def validate_report_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


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


def validate_data(new_products: List, up_products: List, down_products: List, report_date: str) -> Tuple[bool, List[str]]:
    """
    验证数据完整性

    Args:
        new_products: 新上榜产品列表
        up_products: 升幅产品列表
        down_products: 降幅产品列表

    Returns:
        (是否有效, 错误信息列表) 元组
    """
    errors = []

    # 空异动是合法情况，只输出提示，不作为错误。
    if not new_products:
        print("   提示: 新上榜数据为空")
    if not up_products:
        print("   提示: 升幅数据为空")
    if not down_products:
        print("   提示: 降幅数据为空")

    # 检查必要字段是否存在
    required_fields = ['secondary_category', 'tertiary_category', 'commodity_name',
                      'shop_name', 'search_rank', 'ranking_change_value']

    def check_fields(products, data_name):
        for i, p in enumerate(products):
            for field in required_fields:
                if field not in p:
                    errors.append(f"{data_name}[{i}] 缺少字段: {field}")

    check_fields(new_products, "新上榜")
    check_fields(up_products, "升幅")
    check_fields(down_products, "降幅")

    for data_name, products in (("新上榜", new_products), ("升幅", up_products), ("降幅", down_products)):
        for i, p in enumerate(products):
            biz_date = str(p.get("business_date", ""))[:10]
            if biz_date and biz_date != report_date:
                errors.append(f"{data_name}[{i}] business_date={biz_date} 与报告日期 {report_date} 不一致")

    return len(errors) == 0, errors


def read_summary_counts(data_dir: str, report_date: str) -> Dict[str, int]:
    path = os.path.join(data_dir, "summary_counts.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"缺少 summary_counts.json: {path}")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("date") != report_date:
        raise ValueError(f"summary_counts.json 日期 {payload.get('date')} 与报告日期 {report_date} 不一致")
    return {key: int(value) for key, value in payload.get("counts", {}).items()}


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
        {"secondary": "摄像机配件", "tertiary": ""},
        {"secondary": "手机配件", "tertiary": "手机拍照配件 > 自拍杆/架"}
    ]


def group_data_by_category(
    new_products: List,
    up_products: List,
    down_products: List,
    categories: List
) -> Dict:
    """
    按类目分组数据

    Args:
        new_products: 新上榜产品列表
        up_products: 升幅产品列表
        down_products: 降幅产品列表
        categories: 类目组合列表

    Returns:
        分组后的数据
    """
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

    return category_data


def generate_summary_table(categories: List, category_data: Dict, date: str, summary_counts: Dict[str, int] = None) -> str:
    """
    生成汇总表

    Args:
        categories: 类目组合列表
        category_data: 分组后的数据
        date: 报告日期

    Returns:
        汇总表 Markdown 字符串
    """
    summary_table = f"# 淘天BSR榜单周监测报告 ({date})\n\n"
    summary_table += """## 汇总表

| # | 二级类目 | 三级类目 | 最新周数据量 | 新上榜 | 升幅 | 降幅 |
|:---:|---------|---------|:---:|:---:|:---:|:---:|
"""
    total_count = 0
    total_new = 0
    total_up = 0
    total_down = 0
    missing_counts = [
        f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']
        for cat in categories
        if not summary_counts or (f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']) not in summary_counts
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
        summary_table += f"| {i} | {cat['secondary']} | {display_tert} | {data_count} | {new_count} | {up_count} | {down_count} |\n"

    summary_table += f"| **合计** | | | **{total_count}** | **{total_new}** | **{total_up}** | **{total_down}** |\n\n"

    return summary_table


def generate_detail_section(categories: List, category_data: Dict) -> str:
    """
    生成异动明细部分

    Args:
        categories: 类目组合列表
        category_data: 分组后的数据

    Returns:
        异动明细 Markdown 字符串
    """
    detail_section = """## 异动明细

"""

    for cat in categories:
        cat_key = f"{cat['secondary']} - {cat['tertiary']}" if cat['tertiary'] else cat['secondary']
        data = category_data[cat_key]

        display_key = cat_key if cat['tertiary'] else cat['secondary']
        detail_section += f"### {display_key}\n\n"

        # 新上榜TOP5
        if data["new"]:
            detail_section += "新上榜 TOP5：\n"
            detail_section += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            detail_section += "|---------|---------|:-------:|:------:|\n"
            for product in data["new"][:5]:
                detail_section += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | 新上榜 |\n"
            detail_section += "\n"

        # 升幅TOP5
        if data["up"]:
            # 按异动值降序排序
            sorted_up = sorted(data["up"], key=lambda x: x['ranking_change_value'], reverse=True)
            detail_section += "升幅 TOP5：\n"
            detail_section += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            detail_section += "|---------|---------|:-------:|:------:|\n"
            for product in sorted_up[:5]:
                detail_section += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | +{product['ranking_change_value']} |\n"
            detail_section += "\n"

        # 降幅TOP3
        if data["down"]:
            # 按异动值升序排序（负数越小代表降幅越大）
            sorted_down = sorted(data["down"], key=lambda x: x['ranking_change_value'])
            detail_section += "降幅 TOP3：\n"
            detail_section += "| 商品名称 | 店铺名称 | 当周排名 | 异动值 |\n"
            detail_section += "|---------|---------|:-------:|:------:|\n"
            for product in sorted_down[:3]:
                detail_section += f"| {product['commodity_name']} | {product['shop_name']} | {product['search_rank']} | {product['ranking_change_value']} |\n"
            detail_section += "\n"

    return detail_section


def print_preview(summary_table: str, detail_section: str):
    """
    打印报告预览

    Args:
        summary_table: 汇总表
        detail_section: 异动明细
    """
    print("\n" + "="*60)
    print("报告预览")
    print("="*60)

    # 只打印汇总表和部分明细
    print(summary_table)

    # 打印第一个类别的明细作为示例
    if "###" in detail_section:
        first_detail = detail_section.split("###")[1]
        print("###" + first_detail.split("###")[0])
        print("... (更多内容请查看完整报告)")

    print("="*60)


def main():
    args = parse_args()
    try:
        DATE = validate_report_date(args.date)
    except ValueError as exc:
        print(f"错误: {exc}")
        return 1

    print("="*60)
    print("淘天BSR榜单周监测报告生成工具（增强版）")
    print("="*60)
    print(f"报告日期: {DATE}")

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
        summary_counts = read_summary_counts(data_dir, DATE)
        print(f"   新上榜: {len(new_products)} 条")
        print(f"   升幅: {len(up_products)} 条")
        print(f"   降幅: {len(down_products)} 条")
    except Exception as e:
        print(f"错误: 读取查询结果失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 3. 验证数据
    print("\n3. 验证数据...")
    is_valid, errors = validate_data(new_products, up_products, down_products, DATE)
    if not is_valid:
        print("   错误: 数据验证发现以下问题:")
        for err in errors:
            print(f"   - {err}")
        return 1
    else:
        print("   数据验证通过")

    # 4. 分组数据
    print("\n4. 分组数据...")
    categories = get_categories()
    category_data = group_data_by_category(new_products, up_products, down_products, categories)
    print("   数据分组完成")

    # 5. 生成报告
    print("\n5. 生成报告...")
    summary_table = generate_summary_table(categories, category_data, DATE, summary_counts)
    detail_section = generate_detail_section(categories, category_data)
    full_report = summary_table + detail_section
    print("   报告生成完成")

    # 6. 预览
    if args.preview:
        print_preview(summary_table, detail_section)
        return 0

    # 7. 保存报告
    print("\n6. 保存报告...")
    report_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "report_collection")
    if not os.path.exists(report_dir):
        os.makedirs(report_dir)
    report_file = os.path.join(report_dir, f"bsr_ranking_report_{DATE.replace('-', '')}.md")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(full_report)

    print(f"报告已生成：{report_file}")

    # 打印报告路径以便复制
    print(f"\n完整报告路径:\n{report_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
