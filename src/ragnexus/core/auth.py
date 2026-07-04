"""鉴权核心——TenantContext 上下文 + 纯函数（SHA-256 哈希、Bearer 令牌解析）。

本模块提供无副作用的纯函数，不依赖数据库或外部服务。
Depends 工厂函数见同文件后续追加（Task 1.5b）。
"""

import hashlib
from dataclasses import dataclass


@dataclass
class TenantContext:
    """鉴权通过后的租户上下文，注入到每个请求中。

    字段：
    - tenant_id: 租户唯一标识
    - tenant_name: 租户展示名
    - key_id: 本次鉴权使用的 API Key UUID
    - key_prefix: Key 前缀（如 "rk_a1b2"），日志辨认用
    """

    tenant_id: str
    tenant_name: str
    key_id: str
    key_prefix: str


def hash_key(raw_key: str) -> str:
    """对原始 API Key 做 SHA-256 哈希，返回十六进制字符串。"""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def extract_token(header: str | None) -> str | None:
    """从 Authorization: Bearer xxx 中提取 token。

    返回 None 的情况：
    - header 为 None 或空
    - 格式不是 "Bearer <token>"（两个空格分隔的单词，第一个小写为 bearer）
    """
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]
