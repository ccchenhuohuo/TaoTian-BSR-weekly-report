#!/usr/bin/env python3
"""
飞书 Base 操作辅助函数库

提供常用的飞书 Base 操作函数，包括：
- 检查表是否存在
- 创建表和字段
- 获取字段顺序
- 批量写入记录
- 验证和裁剪记录
- Select 选项值处理（HTML 实体转原始符号）
"""

import json
import os
import re
import signal
import shlex
import subprocess
import time
from typing import List, Dict, Any, Optional, Tuple


DEFAULT_LARK_TIMEOUT = int(os.environ.get("LARK_CLI_TIMEOUT", "90"))
DEFAULT_LARK_RETRIES = int(os.environ.get("LARK_CLI_RETRIES", "2"))
DEFAULT_LARK_BACKOFF = float(os.environ.get("LARK_CLI_BACKOFF", "1.5"))
SLOW_COMMAND_SECONDS = float(os.environ.get("LARK_CLI_SLOW_SECONDS", "15"))
LARK_COMMAND_LOG: List[Dict[str, Any]] = []
SECRET_FLAGS = {"--base-token", "--template-base-token", "--new-base-token"}
PAYLOAD_FLAGS = {"--json", "--dsl", "--text"}
WRITE_COMMAND_MARKERS = (
    "+base-copy",
    "+view-set-visible-fields",
    "+base-block-rename",
    "+table-create",
    "+table-update",
    "+field-create",
    "+record-delete",
    "+record-batch-create",
    "+messages-send",
)


def configured_lark_cli() -> str:
    """Return the single lark-cli executable configured for this deployment."""
    return os.environ.get("LARK_CLI_BIN", "lark-cli")


def normalize_lark_args(args: List[str]) -> List[str]:
    """Replace the generic lark-cli name with the configured executable."""
    if args and args[0] == "lark-cli":
        return [configured_lark_cli(), *args[1:]]
    return args


def command_log_summary() -> Dict[str, Any]:
    return {
        "total": len(LARK_COMMAND_LOG),
        "slow_commands": [entry for entry in LARK_COMMAND_LOG if entry.get("slow")],
        "timeouts": [entry for entry in LARK_COMMAND_LOG if entry.get("timed_out")],
        "missing_scope_commands": [
            entry for entry in LARK_COMMAND_LOG if entry.get("error_kind") == "missing_scope"
        ],
    }


def q(value: Any) -> str:
    """Shell-quote one lark-cli argument."""
    return shlex.quote(str(value))


def parse_missing_scopes(text: str) -> List[str]:
    """Extract missing OAuth scopes from lark-cli JSON or text errors."""
    scopes = []
    if not text:
        return scopes
    try:
        payload = json.loads(text)
        error = payload.get("error", payload)
        scopes.extend(error.get("missing_scopes") or [])
    except Exception:
        pass
    scopes.extend(re.findall(r"[\w:.-]+:[\w:.-]+(?=[\\\"'\\s,\]])", text))
    return sorted(set(scope for scope in scopes if scope.startswith(("base:", "im:"))))


def classify_lark_error(stderr: str = "", stdout: str = "") -> Dict[str, Any]:
    """Classify common lark-cli failures for summaries and recovery hints."""
    text = "\n".join(part for part in (stderr, stdout) if part)
    missing_scopes = parse_missing_scopes(text)
    if "命令超时" in text or "timeout" in text.lower():
        kind = "timeout"
    elif missing_scopes or "missing required scope" in text:
        kind = "missing_scope"
    elif "not found" in text.lower() or "unknown command" in text.lower():
        kind = "unsupported_cli"
    elif text:
        kind = "command_error"
    else:
        kind = ""
    return {
        "kind": kind,
        "missing_scopes": missing_scopes,
        "auth_hint": auth_login_hint(missing_scopes) if missing_scopes else "",
    }


def auth_login_hint(scopes: List[str]) -> str:
    if not scopes:
        return ""
    joined = " ".join(sorted(set(scopes)))
    return f'{q(configured_lark_cli())} auth login --scope "{joined}" --no-wait --json'


def redact_command_args(args: List[str]) -> str:
    display = []
    redact_next = False
    summarize_next = ""
    for part in args:
        if redact_next:
            display.append("<redacted>")
            redact_next = False
            continue
        if summarize_next:
            display.append(f"<{summarize_next} {len(part)} chars>")
            summarize_next = ""
            continue
        display.append(part)
        if part in SECRET_FLAGS:
            redact_next = True
        elif part in PAYLOAD_FLAGS:
            summarize_next = part.lstrip("-")
    return " ".join(display)


def is_write_lark_command(args: List[str]) -> bool:
    return any(marker in args for marker in WRITE_COMMAND_MARKERS)


def run_lark_command(
    cmd: str,
    timeout: int = DEFAULT_LARK_TIMEOUT,
    retries: Optional[int] = None,
    write_operation: Optional[bool] = None,
) -> Tuple[str, str]:
    """
    执行 lark-cli 命令

    Args:
        cmd: 要执行的命令字符串
        timeout: 超时时间（秒）

    Returns:
        (stdout, stderr) 元组
    """
    args = normalize_lark_args(shlex.split(cmd))
    is_write = is_write_lark_command(args) if write_operation is None else write_operation
    effective_retries = (0 if is_write else DEFAULT_LARK_RETRIES) if retries is None else retries
    attempts = max(1, effective_retries + 1)
    last_stdout = ""
    last_stderr = ""
    redacted_cmd = redact_command_args(args)

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        process = subprocess.Popen(
            args,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            stdout, stderr = "", f"命令超时（{timeout}s）: {redacted_cmd}"

        elapsed = round(time.monotonic() - started, 3)
        last_stdout, last_stderr = stdout, stderr
        classification = classify_lark_error(stderr, stdout)
        LARK_COMMAND_LOG.append({
            "cmd": redacted_cmd,
            "attempt": attempt,
            "elapsed_seconds": elapsed,
            "timeout_seconds": timeout,
            "timed_out": timed_out,
            "write_operation": is_write,
            "slow": elapsed >= SLOW_COMMAND_SECONDS,
            "error_kind": classification.get("kind", ""),
            "missing_scopes": classification.get("missing_scopes", []),
        })

        should_retry = timed_out or classification.get("kind") == "timeout"
        if not should_retry or attempt == attempts:
            return stdout, stderr
        time.sleep(DEFAULT_LARK_BACKOFF ** (attempt - 1))

    return last_stdout, last_stderr


def run_lark_json(
    cmd: str,
    timeout: int = DEFAULT_LARK_TIMEOUT,
    retries: Optional[int] = None,
    write_operation: Optional[bool] = None,
) -> Tuple[Optional[Dict], str]:
    """
    执行 lark-cli 命令并解析 JSON 输出。

    Returns:
        (result, error)；成功时 error 为空字符串。
    """
    stdout, stderr = run_lark_command(
        cmd,
        timeout=timeout,
        retries=retries,
        write_operation=write_operation,
    )
    if stderr:
        return None, stderr
    try:
        result = json.loads(stdout)
    except Exception as e:
        return None, f"解析 JSON 输出失败: {e}"
    if not result.get("ok", False):
        return result, json.dumps(result.get("error", result), ensure_ascii=False)
    return result, ""


def lark_cli_version() -> str:
    stdout, stderr = run_lark_command("lark-cli --version", timeout=20, retries=0)
    if stderr:
        return f"unknown ({stderr.strip()})"
    return stdout.strip()


def check_auth_scopes(scopes: List[str]) -> Dict[str, Any]:
    """Check current lark-cli auth scopes and return a structured summary."""
    unique_scopes = sorted(set(scope for scope in scopes if scope))
    if not unique_scopes:
        return {"requested_scopes": [], "ok": True, "missing_scopes": [], "auth_hint": ""}
    cmd = f'lark-cli auth check --scope {q(" ".join(unique_scopes))} --json'
    result, error = run_lark_json(cmd, timeout=30, retries=1)
    missing = parse_missing_scopes(error)
    ok = bool(result and result.get("ok") and not missing)
    if result and not missing:
        payload = result.get("data", result)
        missing = payload.get("missing_scopes") or payload.get("missing") or []
        ok = ok and not missing
    return {
        "requested_scopes": unique_scopes,
        "ok": ok,
        "missing_scopes": sorted(set(missing)),
        "auth_hint": auth_login_hint(missing),
        "raw_error": error,
    }


def html_entity_to_raw(text: str) -> str:
    """
    将 HTML 实体转换为原始符号

    飞书 Base 的 Select 选项值需要使用原始符号，而不是 HTML 实体

    Args:
        text: 包含 HTML 实体的文本

    Returns:
        转换后的文本
    """
    if not text:
        return text
    text = text.replace("&gt;", ">")
    text = text.replace("&lt;", "<")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    return text


def raw_to_html_entity(text: str) -> str:
    """
    将原始符号转换为 HTML 实体（用于显示）

    Args:
        text: 包含原始符号的文本

    Returns:
        转换后的文本
    """
    if not text:
        return text
    text = text.replace("&", "&amp;")
    text = text.replace(">", "&gt;")
    text = text.replace("<", "&lt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&#39;")
    return text


def list_all_tables(base_token: str) -> Optional[List[Dict]]:
    """
    获取所有表的列表

    Args:
        base_token: Base Token

    Returns:
        表列表，失败返回 None
    """
    tables = []
    offset = 0
    limit = 100
    while True:
        list_cmd = f'lark-cli base +table-list --base-token {q(base_token)} --offset {offset} --limit {limit}'
        stdout, stderr = run_lark_command(list_cmd, timeout=30)

        if stderr:
            print(f"  警告: 获取表列表时出错: {stderr}")
            return None

        try:
            result = json.loads(stdout)
            if not result.get("ok"):
                print(f"  错误: 获取表列表失败: {result}")
                return None
            data = result["data"]
            page_tables = data.get("tables", [])
            tables.extend(page_tables)
            if not data.get("has_more", False) or not page_tables:
                return tables
            offset += len(page_tables)
        except Exception as e:
            print(f"  错误: 解析表列表响应失败: {e}")
            return None


def copy_base(base_token: str, new_name: str, without_content: bool = True) -> Tuple[Optional[Dict], str]:
    """复制 Base，默认只复制结构。"""
    copy_cmd = f'lark-cli base +base-copy --base-token {q(base_token)} --name {q(new_name)}'
    if without_content:
        copy_cmd += " --without-content"
    result, error = run_lark_json(copy_cmd)
    if error:
        return None, error
    return result.get("data", {}).get("base"), ""


def list_views(base_token: str, table_id: str) -> Optional[List[Dict]]:
    """获取表视图列表。"""
    list_cmd = f"lark-cli base +view-list --base-token {q(base_token)} --table-id {q(table_id)} --format json"
    result, error = run_lark_json(list_cmd, timeout=20)
    if error:
        print(f"  错误: 获取视图列表失败: {error}")
        return None
    return result.get("data", {}).get("views", [])


def get_view_visible_fields(base_token: str, table_id: str, view_id: str) -> Optional[List[str]]:
    """获取视图可见字段顺序。"""
    list_cmd = (
        f"lark-cli base +view-get-visible-fields --base-token {q(base_token)} "
        f"--table-id {q(table_id)} --view-id {q(view_id)} --format json"
    )
    result, error = run_lark_json(list_cmd, timeout=60)
    if error:
        print(f"  错误: 获取视图可见字段失败: {error}")
        return None
    return result.get("data", {}).get("visible_fields", [])


def set_view_visible_fields(base_token: str, table_id: str, view_id: str, visible_fields: List[str]) -> Tuple[bool, str]:
    """设置视图可见字段顺序。"""
    payload = json.dumps({"visible_fields": visible_fields}, ensure_ascii=False)
    cmd = (
        f"lark-cli base +view-set-visible-fields --base-token {q(base_token)} "
        f"--table-id {q(table_id)} --view-id {q(view_id)} --json {q(payload)} --format json"
    )
    result, error = run_lark_json(cmd, timeout=90)
    if error:
        return False, error
    return bool(result and result.get("ok")), ""


def validate_and_repair_view_visible_fields(
    template_base: str,
    new_base: str,
    template_table_id: str,
    new_table_id: str,
    template_view_id: str,
    new_view_id: str,
    repair: bool = True,
) -> Dict[str, Any]:
    """Compare visible field order with template and optionally repair it."""
    template_visible = get_view_visible_fields(template_base, template_table_id, template_view_id)
    new_visible = get_view_visible_fields(new_base, new_table_id, new_view_id)
    if template_visible is None or new_visible is None:
        return {
            "status": "validation_deferred",
            "ok": False,
            "message": "视图可见字段接口超时或返回失败",
        }
    if template_visible == new_visible:
        return {"status": "ok", "ok": True, "repaired": False}
    if not repair:
        return {
            "status": "mismatch",
            "ok": False,
            "repaired": False,
            "template_visible": template_visible,
            "new_visible": new_visible,
        }
    repaired, error = set_view_visible_fields(new_base, new_table_id, new_view_id, template_visible)
    if not repaired:
        return {
            "status": "repair_failed",
            "ok": False,
            "repaired": False,
            "error": error,
            "classification": classify_lark_error(error),
        }
    readback = get_view_visible_fields(new_base, new_table_id, new_view_id)
    return {
        "status": "repaired" if readback == template_visible else "repair_unconfirmed",
        "ok": readback == template_visible,
        "repaired": True,
    }


def list_blocks(base_token: str, block_type: Optional[str] = None) -> Tuple[Optional[List[Dict]], str]:
    """获取 Base block 列表；需要 base:block:read 权限。"""
    list_cmd = f"lark-cli base +base-block-list --base-token {q(base_token)} --format json"
    if block_type:
        list_cmd += f" --type {q(block_type)}"
    result, error = run_lark_json(list_cmd, timeout=90)
    if error:
        return None, error
    return result.get("data", {}).get("blocks", []), ""


def rename_block(base_token: str, block_id: str, new_name: str) -> Tuple[bool, str]:
    """重命名 Base block；需要对应 block 权限。"""
    rename_cmd = (
        f'lark-cli base +base-block-rename --base-token {q(base_token)} '
        f'--block-id {q(block_id)} --name {q(new_name)} --format json'
    )
    result, error = run_lark_json(rename_cmd, timeout=90)
    if error:
        return False, error
    return bool(result and result.get("ok")), ""


def rename_date_folder_if_possible(base_token: str, target_date: str) -> Dict[str, Any]:
    """
    尝试将独立 Base 左侧日期文件夹改为当前报告日期。

    API 权限不足时返回 needs_ui_fallback，不中断数据写入流程。
    """
    folders, error = list_blocks(base_token, block_type="folder")
    if error:
        classification = classify_lark_error(error)
        missing_scopes = classification.get("missing_scopes") or ["base:block:read"]
        return {
            "status": "needs_auth_scope" if missing_scopes else "needs_ui_fallback",
            "error": error,
            "missing_scopes": missing_scopes,
            "auth_hint": auth_login_hint(missing_scopes),
            "message": "缺少 Base block 读取权限，补权限后可用 CLI 重命名左侧日期文件夹。"
        }
    if not folders:
        return {"status": "no_folder", "message": "未找到可重命名的 folder block"}

    for folder in folders:
        name = folder.get("name", "")
        if name == target_date:
            return {"status": "already_ok", "folder_id": folder.get("id"), "name": name}

    date_like = [
        folder for folder in folders
        if len(folder.get("name", "")) == 10
        and folder.get("name", "")[4] == "-"
        and folder.get("name", "")[7] == "-"
    ]
    target = date_like[0] if date_like else folders[0]
    ok, rename_error = rename_block(base_token, target.get("id", ""), target_date)
    if not ok:
        classification = classify_lark_error(rename_error)
        missing_scopes = classification.get("missing_scopes") or ["base:block:update"]
        return {
            "status": "needs_auth_scope" if missing_scopes else "needs_ui_fallback",
            "folder_id": target.get("id"),
            "old_name": target.get("name"),
            "error": rename_error,
            "missing_scopes": missing_scopes,
            "auth_hint": auth_login_hint(missing_scopes),
            "message": "API 重命名失败；优先补 Base block 更新权限后重跑，必要时再用 UI 兜底。"
        }
    return {
        "status": "renamed",
        "folder_id": target.get("id"),
        "old_name": target.get("name"),
        "new_name": target_date
    }


def table_exists(base_token: str, table_name: str) -> Tuple[bool, Optional[str]]:
    """
    检查指定名称的表是否存在

    Args:
        base_token: Base Token
        table_name: 表名（如 "2026-04-13"）

    Returns:
        (是否存在, 表ID或None)
    """
    tables = list_all_tables(base_token)
    if tables is None:
        return False, None

    for table in tables:
        if table["name"] == table_name:
            return True, table["id"]

    return False, None


def find_latest_table(base_token: str) -> Optional[Dict]:
    """
    查找最新的表（按名称排序，假设表名是日期格式 YYYY-MM-DD）

    Args:
        base_token: Base Token

    Returns:
        最新的表信息字典，失败返回 None
    """
    tables = list_all_tables(base_token)
    if tables is None or len(tables) == 0:
        return None

    # 过滤看起来像日期的表名 (YYYY-MM-DD)
    date_tables = []
    for table in tables:
        name = table["name"]
        if len(name) == 10 and name[4] == '-' and name[7] == '-':
            date_tables.append(table)

    if not date_tables:
        # 如果没有日期格式的表，返回第一个
        return tables[0]

    # 按名称降序排序（最新的日期在前）
    date_tables.sort(key=lambda t: t["name"], reverse=True)
    return date_tables[0]


def get_field_definitions(base_token: str, table_id: str) -> Optional[List[Dict]]:
    """
    获取表的完整字段定义（用于复制表结构）

    Args:
        base_token: Base Token
        table_id: 表ID

    Returns:
        字段定义列表（按源表顺序），失败返回 None
    """
    list_cmd = f'lark-cli base +field-list --base-token {q(base_token)} --table-id {q(table_id)}'
    stdout, stderr = run_lark_command(list_cmd, timeout=30)

    if stderr:
        print(f"  错误: 获取字段列表失败: {stderr}")
        return None

    try:
        result = json.loads(stdout)
        if result.get("ok"):
            fields = result["data"]["fields"]
            # 按源表顺序构建字段定义，保持顺序
            user_fields = []
            for field in fields:
                if field["name"] == "ID":
                    continue  # 跳过 ID 字段
                # 构建创建字段所需的定义
                field_def = {
                    "name": field["name"],
                    "type": field["type"]
                }
                # 如果是 select 类型，包含选项
                if field["type"] == "select" and "options" in field:
                    field_def["options"] = field["options"]
                user_fields.append(field_def)
            return user_fields
        else:
            print(f"  错误: 获取字段列表失败: {result}")
    except Exception as e:
        print(f"  错误: 解析字段列表响应失败: {e}")
        import traceback
        traceback.print_exc()

    return None


def create_table_with_fields(base_token: str, table_name: str, fields: List[Dict]) -> Optional[str]:
    """
    创建表并一次性添加所有字段

    Args:
        base_token: Base Token
        table_name: 表名
        fields: 字段定义列表

    Returns:
        表ID，失败返回 None
    """
    # 确保 Select 选项值使用原始符号
    for field in fields:
        if field.get("type") == "select" and "options" in field:
            for opt in field["options"]:
                opt["name"] = html_entity_to_raw(opt["name"])

    fields_json = json.dumps(fields, ensure_ascii=False)
    create_cmd = f'lark-cli base +table-create --base-token {q(base_token)} --name {q(table_name)} --fields {q(fields_json)}'
    stdout, stderr = run_lark_command(create_cmd)

    if stderr:
        print(f"  警告: 创建表时出错: {stderr}")

    try:
        result = json.loads(stdout)
        if result.get("ok"):
            return result["data"]["table"]["id"]
        else:
            print(f"  错误: 创建表失败: {result}")
    except Exception as e:
        print(f"  错误: 解析创建表响应失败: {e}")

    return None


def copy_table_structure(base_token: str, source_table_id: str, new_table_name: str) -> Optional[str]:
    """
    复制源表的结构创建新表（确保字段顺序一致）

    Args:
        base_token: Base Token
        source_table_id: 源表ID
        new_table_name: 新表名

    Returns:
        新表ID，失败返回 None
    """
    print(f"  读取源表字段定义...")
    fields = get_field_definitions(base_token, source_table_id)
    if fields is None:
        print("  错误: 无法获取源表字段定义")
        return None

    print(f"  读取到 {len(fields)} 个字段: {[f['name'] for f in fields]}")

    # 一次性创建所有字段，确保顺序一致
    print(f"  创建新表 '{new_table_name}' 并一次性添加所有字段...")
    new_table_id = create_table_with_fields(base_token, new_table_name, fields)
    if new_table_id:
        print(f"  成功创建新表，ID: {new_table_id}")

    return new_table_id


def create_table_by_copying_latest(base_token: str, new_table_name: str) -> Tuple[Optional[str], bool]:
    """
    通过复制最新的表结构来创建新表

    Args:
        base_token: Base Token
        new_table_name: 新表名

    Returns:
        (新表ID, 是否是通过复制创建的) 元组
        如果没有找到可复制的表，返回 (None, False)
    """
    print("1. 查找最新的表...")
    latest_table = find_latest_table(base_token)
    if latest_table is None:
        print("  未找到可复制的表")
        return None, False

    print(f"  找到最新表: {latest_table['name']} (ID: {latest_table['id']})")

    # 复制表结构
    new_table_id = copy_table_structure(base_token, latest_table['id'], new_table_name)
    if new_table_id:
        return new_table_id, True

    return None, False


def create_table(base_token: str, table_name: str) -> Optional[str]:
    """
    创建新表

    Args:
        base_token: Base Token
        table_name: 表名

    Returns:
        表ID，失败返回 None
    """
    create_cmd = f'lark-cli base +table-create --base-token {q(base_token)} --name {q(table_name)}'
    stdout, stderr = run_lark_command(create_cmd)

    if stderr:
        print(f"  错误: 创建表失败: {stderr}")
        return None

    try:
        result = json.loads(stdout)
        if result.get("ok"):
            return result["data"]["table"]["id"]
        else:
            print(f"  错误: 创建表失败: {result}")
    except Exception as e:
        print(f"  错误: 解析创建表响应失败: {e}")

    return None


def update_table_name(base_token: str, table_id: str, new_name: str) -> Tuple[bool, str]:
    """Rename a Base table by ID or name."""
    cmd = (
        f"lark-cli base +table-update --base-token {q(base_token)} "
        f"--table-id {q(table_id)} --name {q(new_name)} --format json"
    )
    result, error = run_lark_json(cmd, timeout=90)
    if error:
        return False, error
    return bool(result and result.get("ok")), ""


def data_query(base_token: str, dsl: Dict[str, Any]) -> Tuple[Optional[Dict], str]:
    """Run lark-cli Base data-query with a JSON DSL."""
    cmd = f"lark-cli base +data-query --base-token {q(base_token)} --dsl {q(json.dumps(dsl, ensure_ascii=False))} --format json"
    result, error = run_lark_json(cmd, timeout=120)
    if error:
        return None, error
    return result, ""


def aggregate_change_type_counts(base_token: str, table_id: str, report_date: str) -> Tuple[Optional[Dict[str, int]], str]:
    """
    Best-effort server-side aggregation for report rows.

    The exact data-query DSL is owned by lark-cli. This helper is non-blocking
    for the workflow; callers should fall back to paginated record reads.
    """
    dsl = {
        "table_id": table_id,
        "dimensions": ["异动类型"],
        "measures": [{"field": "商品名称", "function": "count", "alias": "count"}],
        "filter": {
            "logic": "and",
            "conditions": [["报告周期", "==", report_date]],
        },
    }
    result, error = data_query(base_token, dsl)
    if error or not result:
        return None, error
    rows = result.get("data", {}).get("rows") or result.get("data", {}).get("data") or []
    counts: Dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            change_type = row.get("异动类型") or row.get("dimension") or row.get("name")
            count = row.get("count") or row.get("COUNT") or row.get("商品名称")
        elif isinstance(row, list) and len(row) >= 2:
            change_type, count = row[0], row[1]
        else:
            continue
        if isinstance(change_type, list):
            change_type = change_type[0] if change_type else ""
        if change_type:
            try:
                counts[str(change_type)] = int(count)
            except (TypeError, ValueError):
                pass
    return counts, "" if counts else "data-query 返回格式未能解析，已降级为分页读回核验"


def create_field(base_token: str, table_id: str, field: Dict[str, Any]) -> bool:
    """
    创建字段

    Args:
        base_token: Base Token
        table_id: 表ID
        field: 字段定义字典

    Returns:
        是否成功
    """
    # 确保 Select 选项值使用原始符号
    if field.get("type") == "select" and "options" in field:
        for opt in field["options"]:
            opt["name"] = html_entity_to_raw(opt["name"])

    field_json = json.dumps(field, ensure_ascii=False)
    create_cmd = f'lark-cli base +field-create --base-token {q(base_token)} --table-id {q(table_id)} --json {q(field_json)}'
    stdout, stderr = run_lark_command(create_cmd)

    if stderr:
        print(f"  警告: 创建字段 '{field['name']}' 时出错: {stderr}")

    try:
        result = json.loads(stdout)
        return result.get("ok", False)
    except Exception as e:
        print(f"  错误: 解析创建字段响应失败: {e}")
        return False


def get_field_order(base_token: str, table_id: str) -> Optional[List[str]]:
    """
    获取字段顺序

    Args:
        base_token: Base Token
        table_id: 表ID

    Returns:
        字段名列表（跳过ID字段），失败返回 None
    """
    list_cmd = f'lark-cli base +field-list --base-token {q(base_token)} --table-id {q(table_id)}'
    stdout, stderr = run_lark_command(list_cmd, timeout=30)

    if stderr:
        print(f"  错误: 获取字段列表失败: {stderr}")
        return None

    try:
        result = json.loads(stdout)
        if result.get("ok"):
            fields_order = []
            for field in result["data"]["fields"]:
                if field["name"] != "ID":
                    fields_order.append(field["name"])
            return fields_order
        else:
            print(f"  错误: 获取字段列表失败: {result}")
    except Exception as e:
        print(f"  错误: 解析字段列表响应失败: {e}")

    return None


def list_records(base_token: str, table_id: str, limit: int = 200) -> Optional[List[Dict]]:
    """
    读取表中的所有记录（自动翻页）

    Args:
        base_token: Base Token
        table_id: 表ID
        limit: 每页记录数

    Returns:
        记录列表，失败返回 None
    """
    all_records = []
    offset = 0

    while True:
        list_cmd = f'lark-cli base +record-list --base-token {q(base_token)} --table-id {q(table_id)} --offset {offset} --limit {limit} --format json'
        stdout, stderr = run_lark_command(list_cmd, timeout=30)

        if stderr:
            print(f"  错误: 获取记录列表失败: {stderr}")
            return None

        try:
            result = json.loads(stdout)
            if not result.get("ok"):
                print(f"  错误: 获取记录列表失败: {result}")
                return None

            data = result["data"]
            records = data.get("data", [])

            # lark-cli 1.0.48 returns Base records as rows plus a parallel
            # fields list, while older versions returned record dictionaries.
            if records and isinstance(records[0], list):
                fields = data.get("fields", [])
                record_ids = data.get("record_id_list", [])
                normalized_records = []
                for idx, row in enumerate(records):
                    normalized_records.append({
                        "record_id": record_ids[idx] if idx < len(record_ids) else None,
                        "fields": {
                            field: row[i] if i < len(row) else None
                            for i, field in enumerate(fields)
                        }
                    })
                records = normalized_records

            all_records.extend(records)

            if not data.get("has_more", False):
                break

            offset += len(records)
        except Exception as e:
            print(f"  错误: 解析记录列表响应失败: {e}")
            return None

    return all_records


def delete_records(base_token: str, table_id: str, record_ids: List[str]) -> bool:
    """
    批量删除记录

    Args:
        base_token: Base Token
        table_id: 表ID
        record_ids: 要删除的记录ID列表

    Returns:
        是否成功
    """
    if not record_ids:
        return True

    all_ok = True
    for i in range(0, len(record_ids), 100):
        batch = record_ids[i:i + 100]
        record_args = " ".join(f"--record-id {q(record_id)}" for record_id in batch)
        delete_cmd = (
            f"lark-cli base +record-delete --base-token {q(base_token)} "
            f"--table-id {q(table_id)} {record_args} --yes --format json"
        )
        stdout, stderr = run_lark_command(delete_cmd)

        if stderr:
            print(f"  警告: 删除记录时出错: {stderr}")

        try:
            result = json.loads(stdout)
            all_ok = all_ok and result.get("ok", False)
        except Exception as e:
            print(f"  错误: 解析删除记录响应失败: {e}")
            all_ok = False

        time.sleep(0.5)

    return all_ok


def batch_create_records(base_token: str, table_id: str, fields_order: List[str], rows: List[List], batch_size: int = 200) -> Tuple[int, int]:
    """
    批量创建记录（自动分批）

    Args:
        base_token: Base Token
        table_id: 表ID
        fields_order: 字段顺序列表
        rows: 数据行列表
        batch_size: 每批记录数（最多200）

    Returns:
        (成功数, 失败数) 元组
    """
    success_count = 0
    fail_count = 0

    batch_size = min(batch_size, 200)

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]

        batch_json = json.dumps({"fields": fields_order, "rows": batch}, ensure_ascii=False)
        write_cmd = f'lark-cli base +record-batch-create --base-token {q(base_token)} --table-id {q(table_id)} --json {q(batch_json)}'
        stdout, stderr = run_lark_command(write_cmd)

        if stderr:
            print(f"   批次 {i//batch_size + 1} 写入警告: {stderr}")

        try:
            result = json.loads(stdout)
            if result.get("ok"):
                success_count += len(batch)
                print(f"   批次 {i//batch_size + 1} 成功写入 {len(batch)} 条")
            else:
                fail_count += len(batch)
                print(f"   批次 {i//batch_size + 1} 写入失败: {result}")
        except Exception as e:
            fail_count += len(batch)
            print(f"   批次 {i//batch_size + 1} 解析响应失败: {e}")

        time.sleep(0.5)

    return success_count, fail_count


def validate_and_trim_records(base_token: str, table_id: str, date: str) -> Tuple[int, int]:
    """
    验证并裁剪飞书Base中的记录

    校验规则：
    - 新上榜：全部保留
    - 升幅：取异动值 TOP 15
    - 降幅：按异动值升序，取 TOP 10

    Args:
        base_token: Base Token
        table_id: 表ID
        date: 报告周期日期

    Returns:
        (保留记录数, 删除记录数) 元组
    """
    print("1. 读取现有记录...")
    records = list_records(base_token, table_id)
    if records is None:
        print("   读取记录失败")
        return 0, 0

    print(f"   共读取 {len(records)} 条记录")

    # 只裁剪本报告周期，避免跨周期误删。
    date_records = [
        record for record in records
        if record.get("fields", {}).get("报告周期") == date
    ]

    # 按「二级类目 + 三级类目 + 异动类型」分组
    groups = {}
    for record in date_records:
        fields = record["fields"]

        # 获取分类键
        sec_cats = fields.get("二级类目", [])
        sec_cat = sec_cats[0] if sec_cats else ""

        tert_cats = fields.get("三级类目", [])
        tert_cat = tert_cats[0] if tert_cats else ""

        change_types = fields.get("异动类型", [])
        change_type = change_types[0] if change_types else ""

        key = f"{sec_cat}|||{tert_cat}|||{change_type}"

        if key not in groups:
            groups[key] = []
        groups[key].append(record)

    # 分析每组并标记待删除的记录
    to_delete = []
    to_keep = []

    for key, group_records in groups.items():
        sec_cat, tert_cat, change_type = key.split("|||")

        print(f"\n   分组: {sec_cat} / {tert_cat} / {change_type} - {len(group_records)} 条")

        if change_type == "新上榜":
            # 新上榜：全部保留
            to_keep.extend(group_records)
            print(f"     → 全部保留（新上榜）")
        elif change_type == "升幅":
            # 升幅：取异动值 TOP 15
            if len(group_records) > 15:
                # 按异动值降序排序
                sorted_records = sorted(group_records, key=lambda r: r["fields"].get("异动值", 0), reverse=True)
                to_keep.extend(sorted_records[:15])
                to_delete.extend([r["record_id"] for r in sorted_records[15:]])
                print(f"     → 保留 TOP 15，删除 {len(sorted_records[15:])} 条")
            else:
                to_keep.extend(group_records)
                print(f"     → 全部保留（≤15条）")
        elif change_type == "降幅":
            # 降幅：按异动值升序，取 TOP 10
            if len(group_records) > 10:
                # 按异动值升序排序（负数越小代表降幅越大）
                sorted_records = sorted(group_records, key=lambda r: r["fields"].get("异动值", 0))
                to_keep.extend(sorted_records[:10])
                to_delete.extend([r["record_id"] for r in sorted_records[10:]])
                print(f"     → 保留 TOP 10，删除 {len(sorted_records[10:])} 条")
            else:
                to_keep.extend(group_records)
                print(f"     → 全部保留（≤10条）")

    # 执行删除
    if to_delete:
        print(f"\n2. 删除 {len(to_delete)} 条记录...")
        # 分批删除，每批最多 100 条
        for i in range(0, len(to_delete), 100):
            batch = to_delete[i:i + 100]
            delete_records(base_token, table_id, batch)
            time.sleep(0.5)
    else:
        print("\n2. 无需删除记录")

    return len(to_keep), len(to_delete)


def send_message_to_user(user_id: str, text: str, as_bot: bool = True) -> bool:
    """
    发送消息给用户

    Args:
        user_id: 用户 ID
        text: 消息内容（Markdown 格式）
        as_bot: 是否以 bot 身份发送

    Returns:
        是否成功
    """
    as_flag = "--as bot" if as_bot else ""
    send_cmd = f'lark-cli im +messages-send {as_flag} --user-id {q(user_id)} --text {q(text)}'
    stdout, stderr = run_lark_command(send_cmd)

    if stderr:
        print(f"  错误: 发送消息失败: {stderr}")
        return False

    try:
        result = json.loads(stdout)
        return result.get("ok", False)
    except Exception as e:
        print(f"  错误: 解析发送消息响应失败: {e}")
        return False
