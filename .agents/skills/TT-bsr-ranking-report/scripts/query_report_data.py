#!/usr/bin/env python3
"""
Query Doris directly and write report input JSON files.

Outputs the wrapper format consumed by generate_report_v2.py:
  [{"text": "[...rows...]"}]
"""

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import DatabaseConfig, ConfigError, load_env_safe


CATEGORY_FILTER = """
(
    (secondary_category = '直播/摄影配件' AND tertiary_category = '闪光灯 > 相机闪光灯')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '影棚设备 > 影室灯')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '影棚设备 > 外拍灯')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机直播配件 > 手机直播补光灯')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机支架/手机座')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机直播配件 > 直播专用支架')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '脚架/云台 > 脚架')
    OR (secondary_category = '摄像机配件' AND (tertiary_category = '摄像机配件' OR tertiary_category IS NULL OR tertiary_category = ''))
    OR (secondary_category = '手机配件' AND tertiary_category = '手机拍照配件 > 自拍杆/架')
)
"""

BASE_SELECT = """
SELECT
    business_date,
    secondary_category,
    COALESCE(tertiary_category, '') AS tertiary_category,
    commodity_id,
    commodity_name,
    commodity_picture,
    commodity_link,
    shop_name,
    search_rank,
    ranking_change_value,
    '{change_type}' AS 异动描述
FROM {target_table}
WHERE DATE(business_date) = '{report_date}'
  AND {change_predicate}
  AND {category_filter}
ORDER BY secondary_category, tertiary_category, {order_by}
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Query BSR report data from Doris")
    parser.add_argument("--date", help="Report date YYYY-MM-DD. Defaults to MAX(business_date).")
    parser.add_argument("--output-dir", help="Output directory. Defaults to tool-results/YYYYMMDD.")
    return parser.parse_args()


def validate_report_date(value: str) -> str:
    """Validate YYYY-MM-DD dates before interpolating into Doris SQL."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"日期格式错误: {value}，应为 YYYY-MM-DD")
    return value


db_config = None


def get_db_config() -> DatabaseConfig:
    global db_config
    if db_config is not None:
        return db_config

    load_env_safe()
    try:
        db_config = DatabaseConfig.from_env()
    except ConfigError as e:
        print(f"[ERROR] 配置加载失败: {e}", file=sys.stderr)
        sys.exit(1)
    return db_config


def connect():
    import pymysql

    cfg = get_db_config()

    print("[连接Doris] configured query endpoint", file=sys.stderr)
    return pymysql.connect(
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


def normalize_value(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value


def normalize_rows(rows: List[Dict]) -> List[Dict]:
    return [{key: normalize_value(value) for key, value in row.items()} for row in rows]


def latest_report_date(conn) -> str:
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT MAX(DATE(business_date)) AS latest_week FROM {get_db_config().target_table}")
        latest = cursor.fetchone()["latest_week"]
    if not latest:
        raise RuntimeError("目标表无业务日期")
    return latest.strftime("%Y-%m-%d") if hasattr(latest, "strftime") else str(latest)


def run_query(conn, sql: str) -> List[Dict]:
    with conn.cursor() as cursor:
        cursor.execute(sql)
        return normalize_rows(cursor.fetchall())


def write_wrapper(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"text": json.dumps(rows, ensure_ascii=False)}]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def category_key(row: Dict) -> str:
    tertiary = row.get("tertiary_category") or ""
    return f"{row.get('secondary_category', '')} - {tertiary}" if tertiary else row.get("secondary_category", "")


def main() -> int:
    args = parse_args()
    if args.date:
        try:
            report_date = validate_report_date(args.date)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
    else:
        report_date = None

    conn = connect()
    try:
        report_date = report_date or latest_report_date(conn)
        ymd = report_date.replace("-", "")
        output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent.parent / "tool-results" / ymd

        queries = {
            "new_products.json": BASE_SELECT.format(
                target_table=get_db_config().target_table,
                report_date=report_date,
                change_type="新上榜",
                change_predicate="ranking_change_value = 9999",
                category_filter=CATEGORY_FILTER,
                order_by="search_rank + 0",
            ),
            "up_products.json": BASE_SELECT.format(
                target_table=get_db_config().target_table,
                report_date=report_date,
                change_type="升幅",
                change_predicate="ranking_change_value > 0 AND ranking_change_value != 9999",
                category_filter=CATEGORY_FILTER,
                order_by="ranking_change_value DESC, search_rank + 0",
            ),
            "down_products.json": BASE_SELECT.format(
                target_table=get_db_config().target_table,
                report_date=report_date,
                change_type="降幅",
                change_predicate="ranking_change_value < 0",
                category_filter=CATEGORY_FILTER,
                order_by="ranking_change_value ASC, search_rank + 0",
            ),
        }
        summary_sql = f"""
        SELECT
            secondary_category,
            COALESCE(tertiary_category, '') AS tertiary_category,
            COUNT(*) AS latest_week_count
        FROM {get_db_config().target_table}
        WHERE DATE(business_date) = '{report_date}'
          AND {CATEGORY_FILTER}
        GROUP BY secondary_category, COALESCE(tertiary_category, '')
        ORDER BY secondary_category, tertiary_category
        """

        summary = {"date": report_date, "output_dir": str(output_dir), "files": {}}
        for filename, sql in queries.items():
            rows = run_query(conn, sql)
            write_wrapper(output_dir / filename, rows)
            summary["files"][filename] = len(rows)
            print(f"[查询完成] {filename}: {len(rows)} rows")

        summary_rows = run_query(conn, summary_sql)
        summary_counts = {
            category_key(row): int(row.get("latest_week_count", 0) or 0)
            for row in summary_rows
        }
        (output_dir / "summary_counts.json").write_text(
            json.dumps({"date": report_date, "counts": summary_counts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary["files"]["summary_counts.json"] = len(summary_counts)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
