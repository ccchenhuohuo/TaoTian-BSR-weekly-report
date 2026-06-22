#!/usr/bin/env python3
"""
TT-bsr-ranking-report 数据同步脚本
自动化执行 Doris Stream Load 数据同步

用法:
    python sync_data.py                    # 自动检测并同步
    python sync_data.py --date 2026-03-30 # 指定日期同步
    python sync_data.py --check-only       # 仅检查状态

依赖:
    pip install pymysql python-dotenv

Stream Load 逻辑复用 stream-load skill 的 stream_load.py
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 加载 .env 配置
from config import load_env_safe, DatabaseConfig, ConfigError

db_config = None

# stream_load.py 路径：项目级 skill 优先，用户级 skill 兜底
PROJECT_STREAM_LOAD_SCRIPT = Path(__file__).parent.parent.parent / "stream-load" / "scripts" / "stream_load.py"
USER_STREAM_LOAD_SCRIPT = Path.home() / ".agents" / "skills" / "stream-load" / "scripts" / "stream_load.py"
STREAM_LOAD_SCRIPT = PROJECT_STREAM_LOAD_SCRIPT if PROJECT_STREAM_LOAD_SCRIPT.exists() else USER_STREAM_LOAD_SCRIPT


def get_db_config():
    """Load database configuration lazily so importing this module is test-safe."""
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


def target_table() -> str:
    return get_db_config().target_table


def source_table() -> str:
    return get_db_config().source_table


def get_connection():
    """按优先级建立 Doris 查询连接。"""
    import pymysql
    last_error = None
    cfg = get_db_config()

    for host, port in cfg.connection_targets():
        try:
            print("[连接Doris] configured query endpoint")
            return pymysql.connect(
                host=host,
                port=port,
                user=cfg.user,
                password=cfg.password,
                database=cfg.database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=10,
                read_timeout=120,
                write_timeout=120,
            )
        except pymysql.err.OperationalError as e:
            last_error = e
            print(f"[警告] 数据库连接失败，尝试下一个地址 {host}:{port} -> {e}")

    print(f"[错误] 数据库连接失败: {last_error}")
    raise last_error


def check_sync_status():
    """检查源表和目标表的同步状态，返回所有需要同步的日期列表"""
    conn = get_connection()
    cursor = conn.cursor()

    # 获取目标表最新日期
    target_max_sql = f"SELECT MAX(business_date) AS target_max FROM {target_table()}"
    cursor.execute(target_max_sql)
    target_max = cursor.fetchone()['target_max']

    # 获取源表中所有 search_rank <= 100 的业务日期列表（去重升序）
    # 如果目标表为空（target_max is None），则同步所有可用日期
    if target_max is None:
        source_dates_sql = f"""
            SELECT DISTINCT DATE(business_date) AS biz_date
            FROM {source_table()}
            WHERE search_rank <= 100
            ORDER BY biz_date
        """
    else:
        source_dates_sql = f"""
            SELECT DISTINCT DATE(business_date) AS biz_date
            FROM {source_table()}
            WHERE search_rank <= 100
            AND DATE(business_date) > DATE('{target_max}')
            ORDER BY biz_date
        """
    cursor.execute(source_dates_sql)
    source_dates = [row['biz_date'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    print("[检查同步状态]")
    tgt_str = target_max.strftime('%Y-%m-%d') if hasattr(target_max, 'strftime') else str(target_max) if target_max else 'N/A'
    print(f"  目标表最新日期: {tgt_str}")

    if not source_dates:
        print("  → 源表无新增日期需要同步")
        return []

    for d in source_dates:
        d_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)
        print(f"  → 需要同步 {d_str} 的数据")

    return source_dates


def latest_target_date():
    """Return the latest business date currently in the target table."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT MAX(business_date) AS target_max FROM {target_table()}")
        return cursor.fetchone()["target_max"]
    finally:
        cursor.close()
        conn.close()


def verify_existing_date(sync_date):
    """Verify an already-present date before treating the sync as complete."""
    sync_str = biz_date_str(sync_date)
    print(f"[已有数据核验] {sync_str}")
    diff = bidirectional_diff(sync_date)
    print(json.dumps({"diff_existing": diff}, ensure_ascii=False, indent=2))
    if not diff_is_clean(diff):
        print(f"[错误] {sync_str} 已存在但双向差异核验未通过")
        sys.exit(1)
    print(f"[完成] {sync_str} 已存在且双向差异为 0")


def fetch_source_data(business_date):
    """从源表获取数据"""
    conn = get_connection()
    cursor = conn.cursor()

    # 格式化日期字符串，避免 pymysql 参数绑定与 LIKE % 冲突
    biz_str = business_date.strftime('%Y-%m-%d') if hasattr(business_date, 'strftime') else str(business_date)

    # Doris 兼容写法：使用 INT 而非 UNSIGNED
    sql = f"""
    SELECT
        commodity_id,
        primary_industry,
        secondary_category,
        tertiary_category,
        shop_name,
        commodity_name,
        REPLACE(commodity_picture, '_36x36.jpg', '_600x600.jpg') AS commodity_picture,
        commodity_link,
        search_rank,
        business_date,
        CASE
            WHEN ranking_changes LIKE '%新上榜%' THEN 9999
            WHEN ranking_changes REGEXP '^升[0-9]+名$' THEN CAST(REPLACE(REPLACE(ranking_changes, '升', ''), '名', '') AS INT)
            WHEN ranking_changes REGEXP '^降[0-9]+名$' THEN -CAST(REPLACE(REPLACE(ranking_changes, '降', ''), '名', '') AS INT)
            WHEN ranking_changes LIKE '%升%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '升', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '升', -1), '名', 1), '名', '') AS INT)
            WHEN ranking_changes LIKE '%降%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '降', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '降', -1), '名', 1), '名', '') AS INT)
            ELSE 0
        END AS ranking_change_value
    FROM {source_table()}
    WHERE search_rank <= 100
    AND DATE(business_date) = '{biz_str}'
    ORDER BY commodity_id, search_rank
    """
    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
    except Exception as e:
        print(f"[错误] 查询源表失败: {e}")
        cursor.close()
        conn.close()
        return None
    cursor.close()
    conn.close()

    print(f"[获取源数据] 日期: {biz_str}")
    if not rows:
        print("  → 源表无数据可同步")
        return None

    print(f"  → 获取到 {len(rows)} 条记录")
    return rows


def generate_json(rows, business_date):
    """生成 JSON 数据"""
    beijing_tz = timezone(timedelta(hours=8))
    gather_time = datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
    biz_date = business_date.strftime('%Y-%m-%d') if hasattr(business_date, 'strftime') else str(business_date)
    data = []

    for row in rows:
        data.append({
            'business_date': f"{biz_date} 00:00:00",
            'commodity_id': str(row.get('commodity_id', '')),
            'primary_industry': row.get('primary_industry') or '',
            'secondary_category': row.get('secondary_category') or '',
            'tertiary_category': row.get('tertiary_category') or '',
            'shop_name': row.get('shop_name') or '',
            'commodity_name': row.get('commodity_name') or '',
            'commodity_picture': row.get('commodity_picture') or '',
            'commodity_link': row.get('commodity_link') or '',
            'search_rank': str(row.get('search_rank', '')),
            'ranking_change_value': int(row.get('ranking_change_value', 0) or 0),
            'gather_time': gather_time
        })

    return json.dumps(data, ensure_ascii=False)


def biz_date_str(value):
    return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)


def source_parsed_key_sql(sync_str):
    return f"""
    SELECT CONCAT_WS('||',
      IFNULL(CAST(commodity_id AS STRING),''),
      IFNULL(primary_industry,''),
      IFNULL(secondary_category,''),
      IFNULL(tertiary_category,''),
      IFNULL(shop_name,''),
      IFNULL(commodity_name,''),
      IFNULL(REPLACE(commodity_picture, '_36x36.jpg', '_600x600.jpg'),''),
      IFNULL(commodity_link,''),
      CAST(search_rank + 0 AS STRING),
      CAST(CASE
        WHEN ranking_changes LIKE '%新上榜%' THEN 9999
        WHEN ranking_changes REGEXP '^升[0-9]+名$' THEN CAST(REPLACE(REPLACE(ranking_changes, '升', ''), '名', '') AS INT)
        WHEN ranking_changes REGEXP '^降[0-9]+名$' THEN -CAST(REPLACE(REPLACE(ranking_changes, '降', ''), '名', '') AS INT)
        WHEN ranking_changes LIKE '%升%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '升', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '升', -1), '名', 1), '名', '') AS INT)
        WHEN ranking_changes LIKE '%降%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '降', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '降', -1), '名', 1), '名', '') AS INT)
        ELSE 0 END AS STRING)
    ) AS row_key
    FROM {source_table()}
    WHERE search_rank <= 100 AND DATE(business_date) = '{sync_str}'
    """


def target_key_sql(sync_str):
    return f"""
    SELECT CONCAT_WS('||',
      IFNULL(CAST(commodity_id AS STRING),''),
      IFNULL(primary_industry,''),
      IFNULL(secondary_category,''),
      IFNULL(COALESCE(tertiary_category,''),''),
      IFNULL(shop_name,''),
      IFNULL(commodity_name,''),
      IFNULL(commodity_picture,''),
      IFNULL(commodity_link,''),
      CAST(search_rank + 0 AS STRING),
      CAST(ranking_change_value + 0 AS STRING)
    ) AS row_key
    FROM {target_table()}
    WHERE DATE(business_date) = '{sync_str}'
    """


def bidirectional_diff(sync_date, sample_limit=3):
    """Compare parsed source rows with target rows for one business date."""
    sync_str = biz_date_str(sync_date)
    conn = get_connection()
    cursor = conn.cursor()
    source_sql = source_parsed_key_sql(sync_str)
    target_sql = target_key_sql(sync_str)
    try:
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM ({source_sql}) s")
        source_count = cursor.fetchone()["cnt"]
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM ({target_sql}) t")
        target_count = cursor.fetchone()["cnt"]
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM (({source_sql}) EXCEPT ({target_sql})) x")
        source_minus_target = cursor.fetchone()["cnt"]
        cursor.execute(f"SELECT COUNT(*) AS cnt FROM (({target_sql}) EXCEPT ({source_sql})) x")
        target_minus_source = cursor.fetchone()["cnt"]
        cursor.execute(f"SELECT row_key FROM (({source_sql}) EXCEPT ({target_sql})) x LIMIT {int(sample_limit)}")
        source_samples = [row["row_key"] for row in cursor.fetchall()]
        cursor.execute(f"SELECT row_key FROM (({target_sql}) EXCEPT ({source_sql})) x LIMIT {int(sample_limit)}")
        target_samples = [row["row_key"] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()
    return {
        "business_date": sync_str,
        "source_count": int(source_count or 0),
        "target_count": int(target_count or 0),
        "source_minus_target": int(source_minus_target or 0),
        "target_minus_source": int(target_minus_source or 0),
        "sample_source_minus_target": source_samples,
        "sample_target_minus_source": target_samples,
    }


def diff_is_clean(diff):
    return (
        diff.get("source_count") == diff.get("target_count")
        and diff.get("source_minus_target") == 0
        and diff.get("target_minus_source") == 0
    )


def insert_from_source_if_empty(sync_date):
    """Fallback import using INSERT INTO ... SELECT when target date is empty."""
    sync_str = biz_date_str(sync_date)
    before = confirm_sync(sync_date)
    if before and before.get("total_rows", 0):
        print(f"[兜底跳过] 目标表 {sync_str} 已有 {before.get('total_rows')} 条，避免重复 INSERT")
        return False

    conn = get_connection()
    cursor = conn.cursor()
    sql = f"""
    INSERT INTO {target_table()} (
        business_date,
        commodity_id,
        primary_industry,
        secondary_category,
        tertiary_category,
        shop_name,
        commodity_name,
        commodity_picture,
        commodity_link,
        search_rank,
        ranking_change_value,
        gather_time
    )
    SELECT
        DATE(business_date) AS business_date,
        commodity_id,
        primary_industry,
        secondary_category,
        tertiary_category,
        shop_name,
        commodity_name,
        REPLACE(commodity_picture, '_36x36.jpg', '_600x600.jpg') AS commodity_picture,
        commodity_link,
        search_rank,
        CASE
            WHEN ranking_changes LIKE '%新上榜%' THEN 9999
            WHEN ranking_changes REGEXP '^升[0-9]+名$' THEN CAST(REPLACE(REPLACE(ranking_changes, '升', ''), '名', '') AS INT)
            WHEN ranking_changes REGEXP '^降[0-9]+名$' THEN -CAST(REPLACE(REPLACE(ranking_changes, '降', ''), '名', '') AS INT)
            WHEN ranking_changes LIKE '%升%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '升', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '升', -1), '名', 1), '名', '') AS INT)
            WHEN ranking_changes LIKE '%降%' THEN CAST(SUBSTRING_INDEX(ranking_changes, '降', 1) AS INT) - CAST(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(ranking_changes, '降', -1), '名', 1), '名', '') AS INT)
            ELSE 0
        END AS ranking_change_value,
        NOW() AS gather_time
    FROM {source_table()}
    WHERE search_rank <= 100
      AND DATE(business_date) = '{sync_str}'
    """
    try:
        cursor.execute(sql)
    finally:
        cursor.close()
        conn.close()
    print(f"[兜底完成] 已执行 INSERT INTO ... SELECT: {sync_str}")
    return True


def recover_after_stream_load_failure(sync_date, expected_rows):
    """Recover from Stream Load failure/timeout if data already landed or can be inserted safely."""
    sync_str = biz_date_str(sync_date)
    print(f"[恢复检查] Stream Load 未正常确认，核验 {sync_str} 目标表")
    diff = bidirectional_diff(sync_date)
    print(json.dumps({"diff_before_fallback": diff}, ensure_ascii=False, indent=2))
    if diff_is_clean(diff):
        print("[恢复成功] 目标表已落库且双向差异为 0，按 partial_process_success 继续")
        return {
            "status": "partial_process_success",
            "diff": diff,
            "fallback_inserted": False,
        }

    if diff.get("target_count", 0) == 0:
        insert_from_source_if_empty(sync_date)
        after = bidirectional_diff(sync_date)
        print(json.dumps({"diff_after_fallback": after}, ensure_ascii=False, indent=2))
        if diff_is_clean(after) and after.get("target_count") == expected_rows:
            print("[恢复成功] SQL 兜底写入后双向差异为 0")
            return {
                "status": "fallback_insert_success",
                "diff": after,
                "fallback_inserted": True,
            }
        return {
            "status": "fallback_insert_failed",
            "diff": after,
            "fallback_inserted": True,
        }

    print("[恢复失败] 目标表已有部分或不一致数据，停止以避免重复写入")
    return {
        "status": "unrecoverable_mismatch",
        "diff": diff,
        "fallback_inserted": False,
    }


def write_sync_summary(entries):
    if not entries:
        return None
    latest = entries[-1].get("business_date", "unknown").replace("-", "")
    output_dir = Path(__file__).parent.parent / "tool-results" / latest
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "sync_summary.json"
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[同步摘要] {path}")
    return path


def do_stream_load(json_data, business_date, expected_rows):
    """通过 stream_load.py 执行 Stream Load"""
    if not STREAM_LOAD_SCRIPT.exists():
        print(f"[错误] 未找到 stream_load.py: {STREAM_LOAD_SCRIPT}")
        return False

    biz_date_str = business_date.strftime('%Y-%m-%d') if hasattr(business_date, 'strftime') else str(business_date)
    # 加 UUID 后缀避免 Label 重复导致幂等性冲突
    label = f"ranking_weekly_{biz_date_str.replace('-', '')}_{uuid.uuid4().hex[:8]}"

    columns = "business_date,commodity_id,primary_industry,secondary_category,tertiary_category,shop_name,commodity_name,commodity_picture,commodity_link,search_rank,ranking_change_value,gather_time"
    cfg = get_db_config()

    cmd = [
        sys.executable,
        str(STREAM_LOAD_SCRIPT),  # Path 对象转字符串
        "--hosts", cfg.stream_load_hosts,
        "--port", cfg.stream_load_ports,
        "--user", cfg.user,
        "--password", cfg.password,
        "--database", cfg.database,
        "--table", target_table(),
        "--columns", columns,
        "--label", label,
        "--chunk-size", "0",
    ]

    print(f"[执行Stream Load] 调用 stream_load.py")
    print(f"  Label: {label}")
    print(f"  数据量: {len(json_data)} bytes")
    print(f"  期望行数: {expected_rows}")
    print("  数据传输: stdin")

    try:
        result = subprocess.run(cmd, input=json_data, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        print("[错误] Stream Load 超时（120秒）")
        return False
    except Exception as e:
        print(f"[错误] Stream Load 执行失败: {e}")
        return False

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # 检查 exit code 和响应 Status 字段
    if result.returncode != 0:
        return False

    # 尝试从 stdout 解析 JSON 响应，检查 Status
    try:
        resp = json.loads(result.stdout)
        if resp.get("Chunks"):
            print("[错误] Stream Load 返回切片结果，未执行导入；本项目禁止切片落盘")
            return False
        if resp.get("Status") != "Success":
            print(f"[警告] Stream Load 响应 Status 非 Success: {resp.get('Status')} - {resp.get('Message', '')}")
            return False
    except (json.JSONDecodeError, TypeError):
        # stdout 不是 JSON（如只有纯文本日志），依赖 exit code 判断
        pass

    return True


def confirm_sync(sync_date, expected_rows=None):
    """确认同步完成，验证指定日期的记录数"""
    conn = get_connection()
    cursor = conn.cursor()

    sync_str = sync_date.strftime('%Y-%m-%d') if hasattr(sync_date, 'strftime') else str(sync_date)
    sql = f"SELECT COUNT(*) AS total_rows, MAX(business_date) AS latest_date FROM {target_table()} WHERE DATE(business_date) = '{sync_str}'"
    cursor.execute(sql)
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    print("[确认同步状态]")
    print(f"  同步日期: {sync_str}")
    print(f"  记录数: {result.get('total_rows', 'N/A')}")
    latest = result.get('latest_date')
    print(f"  最新日期: {latest.strftime('%Y-%m-%d') if hasattr(latest, 'strftime') else latest}")

    if expected_rows is not None and result.get('total_rows', 0) != expected_rows:
        print(f"  [错误] 目标表记录数 {result.get('total_rows', 0)} 与源表期望 {expected_rows} 不一致")
        return None

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description='TT-bsr-ranking-report 数据同步脚本')
    parser.add_argument('--date', type=str, help='指定要同步的业务日期 (YYYY-MM-DD)')
    parser.add_argument('--check-only', action='store_true', help='仅检查同步状态')
    args = parser.parse_args()

    # 检查模式
    if args.check_only:
        check_sync_status()
        return

    # 检查同步状态，获取所有需要同步的日期
    sync_dates = check_sync_status()

    if not sync_dates:
        if args.date:
            verify_existing_date(args.date)
        else:
            latest = latest_target_date()
            if latest:
                verify_existing_date(latest)
        print("\n[完成] 数据已是最新，无需同步")
        return

    # 指定日期模式：只同步该日期（如已在表中则跳过）
    if args.date:
        sync_dates = [d for d in sync_dates if str(d) == args.date]
        if not sync_dates:
            verify_existing_date(args.date)
            print(f"\n[完成] {args.date} 已同步且核验通过")
            return

    # 逐个日期同步
    sync_entries = []
    for biz_date in sync_dates:
        biz_str = biz_date.strftime('%Y-%m-%d') if hasattr(biz_date, 'strftime') else str(biz_date)
        print(f"\n========== 开始同步 {biz_str} ==========")

        rows = fetch_source_data(biz_date)
        if not rows:
            print(f"[警告] {biz_str} 源表无数据，跳过")
            continue

        json_data = generate_json(rows, biz_date)
        expected_rows = len(rows)
        success = do_stream_load(json_data, biz_date, expected_rows)

        if success:
            result = confirm_sync(biz_date, expected_rows)
            if not result or result.get('total_rows', 0) == 0:
                print(f"[错误] {biz_str} 同步确认未通过")
                sys.exit(1)
            else:
                diff = bidirectional_diff(biz_date)
                print(json.dumps({"diff_after_stream_load": diff}, ensure_ascii=False, indent=2))
                if not diff_is_clean(diff):
                    print(f"[错误] {biz_str} 双向差异核验未通过")
                    sync_entries.append({
                        "business_date": biz_str,
                        "status": "stream_load_diff_failed",
                        "expected_rows": expected_rows,
                        "diff": diff,
                    })
                    write_sync_summary(sync_entries)
                    sys.exit(1)
                sync_entries.append({
                    "business_date": biz_str,
                    "status": "stream_load_success",
                    "expected_rows": expected_rows,
                    "diff": diff,
                })
                print(f"[完成] {biz_str} 同步成功!")
        else:
            recovery = recover_after_stream_load_failure(biz_date, expected_rows)
            sync_entries.append({
                "business_date": biz_str,
                "status": recovery["status"],
                "expected_rows": expected_rows,
                "diff": recovery.get("diff"),
                "fallback_inserted": recovery.get("fallback_inserted", False),
            })
            if recovery["status"] not in ("partial_process_success", "fallback_insert_success"):
                print(f"[错误] {biz_str} 同步失败且无法安全恢复，请检查日志")
                write_sync_summary(sync_entries)
                sys.exit(1)

    write_sync_summary(sync_entries)
    print(f"\n[完成] 全部 {len(sync_dates)} 个日期同步完成!")


if __name__ == "__main__":
    main()
