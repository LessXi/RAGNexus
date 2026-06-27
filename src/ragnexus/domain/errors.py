"""向后兼容 — 从 core.errors 重新导出。

DomainError 作为 AppError 别名保留，旧代码可继续使用。
"""

from ragnexus.core.errors import AppError, ErrorCode, raise_error

DomainError = AppError  # 向后兼容别名

__all__ = ["AppError", "DomainError", "ErrorCode", "raise_error"]
