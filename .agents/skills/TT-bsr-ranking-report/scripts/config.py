#!/usr/bin/env python3
"""
配置管理模块

支持从环境变量或 .env 文件读取配置
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass


class ConfigError(ValueError):
    """配置错误"""
    pass


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str, name: str) -> str:
    if not value:
        raise ConfigError(f"{name} is required")
    if not IDENTIFIER_RE.fullmatch(value):
        raise ConfigError(f"{name} must be a simple Doris identifier, got {value!r}")
    return value


@dataclass
class DatabaseConfig:
    """数据库配置"""
    host: str
    port: int
    user: str
    password: str
    database: str
    target_table: str
    source_table: str
    stream_load_hosts: str
    stream_load_ports: str

    @classmethod
    def from_env(cls, prefix: str = "DORIS_"):
        """从环境变量加载配置"""
        host = os.environ.get(f"{prefix}HOST", "")
        port = int(os.environ.get(f"{prefix}PORT", "30930"))
        user = os.environ.get(f"{prefix}USER", "")
        password = os.environ.get(f"{prefix}PASSWORD", "")
        database = os.environ.get(f"{prefix}DATABASE", "")
        target_table = os.environ.get(f"{prefix}TARGET_TABLE", "")
        source_table = os.environ.get(f"{prefix}SOURCE_TABLE", "")
        stream_load_hosts = os.environ.get(
            f"{prefix}STREAM_LOAD_HOSTS",
            os.environ.get(f"{prefix}STREAM_LOAD_HOST", "")
        )
        stream_load_ports = os.environ.get(
            f"{prefix}STREAM_LOAD_PORTS",
            os.environ.get(f"{prefix}HTTP_PORTS", os.environ.get(f"{prefix}HTTP_PORT", ""))
        )
        allowed_stream_load_host = os.environ.get(f"{prefix}ALLOWED_STREAM_LOAD_HOST", "")
        allowed_stream_load_port = os.environ.get(f"{prefix}ALLOWED_STREAM_LOAD_PORT", "")

        missing = []
        if not host:
            missing.append(f"{prefix}HOST")
        if not user:
            missing.append(f"{prefix}USER")
        if not password:
            missing.append(f"{prefix}PASSWORD")
        if not database:
            missing.append(f"{prefix}DATABASE")
        if not target_table:
            missing.append(f"{prefix}TARGET_TABLE")
        if not source_table:
            missing.append(f"{prefix}SOURCE_TABLE")
        if not stream_load_hosts:
            missing.append(f"{prefix}STREAM_LOAD_HOSTS")
        if not stream_load_ports:
            missing.append(f"{prefix}STREAM_LOAD_PORTS")
        if missing:
            raise ConfigError(f"Missing required config: {', '.join(missing)}")
        database = validate_identifier(database, f"{prefix}DATABASE")
        target_table = validate_identifier(target_table, f"{prefix}TARGET_TABLE")
        source_table = validate_identifier(source_table, f"{prefix}SOURCE_TABLE")
        if allowed_stream_load_host and stream_load_hosts != allowed_stream_load_host:
            raise ConfigError(
                "Stream Load host not allowed"
            )
        if allowed_stream_load_port and stream_load_ports != allowed_stream_load_port:
            raise ConfigError(
                "Stream Load port not allowed"
            )

        return cls(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            target_table=target_table,
            source_table=source_table,
            stream_load_hosts=stream_load_hosts,
            stream_load_ports=stream_load_ports,
        )

    def connection_targets(self):
        """返回按优先级排列的 Doris 查询地址列表。"""
        return [(self.host, self.port)]


@dataclass
class LarkConfig:
    """飞书配置"""
    base_token: str

    @classmethod
    def from_env(cls):
        """从环境变量加载配置"""
        base_token = os.environ.get("LARK_BASE_TOKEN", "")
        if not base_token:
            raise ConfigError("LARK_BASE_TOKEN is required")
        return cls(base_token=base_token)


def load_env_safe() -> None:
    """
    安全加载 .env 文件

    如果 python-dotenv 不可用或 .env 文件不存在，静默跳过
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    script_path = Path(__file__).resolve()
    skill_env = script_path.parents[1] / ".env"
    project_env = script_path.parents[4] / ".env"
    for env_path in (project_env, skill_env):
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
