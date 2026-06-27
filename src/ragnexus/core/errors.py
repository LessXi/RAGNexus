"""RAGNexus 统一错误码系统

提供 ErrorCode 枚举、AppError 异常类和 raise_error 快捷函数。
"""

from __future__ import annotations

from enum import IntEnum

# ============================================================================
# ErrorCode 枚举 —— 33 个成员，按业务区间分类
# ============================================================================


class ErrorCode(IntEnum):
    """统一错误码枚举，每个成员为 (code, http_status, msg) 三元组。

    区间分类：
    - 0: 成功
    - 10001~10199: 参数校验
    - 10200~10299: 认证与鉴权
    - 10300~10399: 资源操作
    - 10400~10499: 文件与媒体
    - 10500~10599: 上游服务
    - 20000~20999: 接口与HTTP
    - 30000~30999: 数据库与存储
    - 40000~40999: 模型调用
    - 50000~50999: 系统与服务
    """

    # 成功
    SUCCESS = (0, 200, "成功")

    # 参数校验 (10001~10199)
    PARAM_ERROR = (10001, 422, "参数错误")
    PARAM_MISSING = (10002, 422, "缺少必要参数")
    PARAM_INVALID = (10003, 422, "参数格式无效")
    PARAM_RANGE_ERROR = (10004, 422, "参数超出允许范围")

    # 认证与鉴权 (10200~10299)
    UNAUTHORIZED = (10200, 401, "未授权，请登录")
    FORBIDDEN = (10201, 403, "权限不足")
    TOKEN_EXPIRED = (10202, 401, "登录已过期")

    # 资源操作 (10300~10399)
    NOT_FOUND = (10300, 404, "资源不存在")
    RESOURCE_CONFLICT = (10301, 409, "资源冲突")
    RESOURCE_EXISTS = (10302, 409, "资源已存在")

    # 文件与媒体 (10400~10499)
    UNSUPPORTED_FORMAT = (10400, 415, "不支持的文件类型")
    FILE_TOO_LARGE = (10401, 413, "文件过大")
    FILE_EMPTY = (10402, 422, "文件为空")

    # 上游服务 (10500~10599)
    UPSTREAM_ERROR = (10500, 502, "上游服务异常")
    UPSTREAM_TIMEOUT = (10501, 504, "上游服务超时")

    # 接口与HTTP (20000~20999)
    API_TIMEOUT = (20001, 504, "接口请求超时")
    API_RATE_LIMIT = (20002, 429, "接口调用超限")
    API_METHOD_ERROR = (20003, 405, "请求方法错误")

    # 数据库与存储 (30000~30999)
    DB_ERROR = (30001, 500, "数据库操作失败")
    DB_CONNECTION_ERROR = (30002, 503, "数据库连接失败")
    DB_QUERY_TIMEOUT = (30003, 504, "数据库查询超时")
    DATA_DUPLICATE = (30004, 409, "数据已存在")

    # 模型调用 (40000~40999)
    MODEL_ERROR = (40000, 502, "大模型调用失败")
    MODEL_TIMEOUT = (40001, 504, "大模型响应超时")
    MODEL_NO_RESPONSE = (40002, 502, "大模型未返回有效内容")
    MODEL_CONTENT_VIOLATION = (40003, 422, "内容违规")
    MODEL_TOKEN_LIMIT = (40004, 422, "上下文长度超限")
    MODEL_RATE_LIMIT = (40005, 429, "大模型调用频率超限")
    MODEL_NOT_AVAILABLE = (40006, 503, "模型不存在或未部署")

    # 系统与服务 (50000~50999)
    SERVER_ERROR = (50000, 500, "服务器异常")
    CONFIG_ERROR = (50001, 500, "服务配置错误")
    SYSTEM_BUSY = (50002, 503, "系统繁忙，请稍后再试")

    def __new__(cls, code: int, http_status: int, msg: str) -> ErrorCode:  # noqa: PYI034
        obj = int.__new__(cls, code)
        obj._value_ = code
        object.__setattr__(obj, "_http_status", http_status)
        object.__setattr__(obj, "_msg", msg)
        return obj

    @property
    def code(self) -> int:
        """业务错误码"""
        return int(self._value_)  # type: ignore[return-value]

    @property
    def http_status(self) -> int:
        """对应的 HTTP 状态码"""
        return self._http_status  # type: ignore[no-any-return]

    @property
    def msg(self) -> str:
        """默认错误消息"""
        return self._msg  # type: ignore[no-any-return]


# ============================================================================
# AppError 异常类
# ============================================================================


class AppError(Exception):
    """RAGNexus 统一应用异常。

    Attributes:
        code: 业务错误码（来自 ErrorCode）
        http_status: HTTP 状态码（来自 ErrorCode）
        message: 错误消息（可自定义，默认取 ErrorCode.msg）
        errors: 字段级错误详情列表
    """

    code: int
    http_status: int
    message: str
    errors: list[dict]

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        errors: list[dict] | None = None,
    ) -> None:
        super().__init__(message if message is not None else code.msg)
        self.code = code.code
        self.http_status = code.http_status
        self.message = message if message is not None else code.msg
        self.errors = errors if errors is not None else []


# ============================================================================
# 快捷函数
# ============================================================================


def raise_error(
    code: ErrorCode,
    message: str | None = None,
    errors: list[dict] | None = None,
) -> None:
    """构造并抛出 AppError。

    参数与 AppError.__init__ 一致。
    """
    raise AppError(code, message, errors)
