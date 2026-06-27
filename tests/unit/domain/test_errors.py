"""Tests for domain/errors.py — 验证从 core.errors 重新导出 AppError + ErrorCode。"""

from ragnexus.core.errors import AppError, ErrorCode, raise_error

# ============================================================================
# 错误码值断言
# ============================================================================


def test_error_codes():
    """验证迁移映射表中各 ErrorCode 的 code 值。"""
    assert ErrorCode.PARAM_ERROR.code == 10001
    assert ErrorCode.NOT_FOUND.code == 10300
    assert ErrorCode.RESOURCE_CONFLICT.code == 10301
    assert ErrorCode.RESOURCE_EXISTS.code == 10302
    assert ErrorCode.UNSUPPORTED_FORMAT.code == 10400
    assert ErrorCode.FILE_TOO_LARGE.code == 10401
    assert ErrorCode.FILE_EMPTY.code == 10402
    assert ErrorCode.UPSTREAM_ERROR.code == 10500
    assert ErrorCode.CONFIG_ERROR.code == 50001


# ============================================================================
# HTTP 状态码断言
# ============================================================================


def test_http_status():
    """验证各 ErrorCode 的 http_status 值。"""
    assert ErrorCode.PARAM_ERROR.http_status == 422
    assert ErrorCode.NOT_FOUND.http_status == 404
    assert ErrorCode.RESOURCE_CONFLICT.http_status == 409
    assert ErrorCode.RESOURCE_EXISTS.http_status == 409
    assert ErrorCode.UNSUPPORTED_FORMAT.http_status == 415
    assert ErrorCode.FILE_TOO_LARGE.http_status == 413
    assert ErrorCode.FILE_EMPTY.http_status == 422
    assert ErrorCode.UPSTREAM_ERROR.http_status == 502
    assert ErrorCode.CONFIG_ERROR.http_status == 500


# ============================================================================
# AppError 字段行为
# ============================================================================


def test_error_fields():
    """AppError 正确存储 message 和 errors 列表。"""
    err = AppError(
        ErrorCode.PARAM_ERROR,
        message="oops",
        errors=[{"field": "name", "reason": "required"}],
    )
    assert err.message == "oops"
    assert err.errors == [{"field": "name", "reason": "required"}]

    err2 = AppError(ErrorCode.PARAM_ERROR, message="just text")
    assert err2.message == "just text"
    assert err2.errors == []

    # 默认消息取自 ErrorCode.msg
    err3 = AppError(ErrorCode.NOT_FOUND)
    assert err3.code == 10300
    assert err3.http_status == 404
    assert err3.message == "资源不存在"


# ============================================================================
# AppError 是 Exception 的子类
# ============================================================================


def test_inheritance():
    """AppError 是 Exception 的子类，不是旧 DomainError 的子类。"""
    assert issubclass(AppError, Exception)
    assert isinstance(AppError(ErrorCode.PARAM_ERROR), Exception)

    # 所有错误码都可以被 pytest.raises(AppError) 捕获
    for code in [
        ErrorCode.PARAM_ERROR,
        ErrorCode.NOT_FOUND,
        ErrorCode.RESOURCE_CONFLICT,
        ErrorCode.RESOURCE_EXISTS,
        ErrorCode.UNSUPPORTED_FORMAT,
        ErrorCode.FILE_TOO_LARGE,
        ErrorCode.FILE_EMPTY,
        ErrorCode.UPSTREAM_ERROR,
        ErrorCode.CONFIG_ERROR,
    ]:
        err = AppError(code)
        assert isinstance(err, AppError), f"{code.name} 创建的实例应为 AppError"


# ============================================================================
# 实例化测试
# ============================================================================


def test_error_instantiation():
    """每种错误码都可实例化，有无自定义消息均可。"""
    AppError(ErrorCode.PARAM_ERROR)
    AppError(ErrorCode.PARAM_ERROR, "自定义验证错误")
    AppError(ErrorCode.NOT_FOUND, "资源未找到")
    AppError(ErrorCode.RESOURCE_CONFLICT, "冲突")
    AppError(ErrorCode.RESOURCE_EXISTS, "文档已存在")
    AppError(ErrorCode.UNSUPPORTED_FORMAT)
    AppError(ErrorCode.FILE_TOO_LARGE)
    AppError(ErrorCode.FILE_EMPTY)
    AppError(ErrorCode.UPSTREAM_ERROR, "上游挂了")
    AppError(ErrorCode.CONFIG_ERROR, "配置错误")


# ============================================================================
# raise_error 快捷函数
# ============================================================================


def test_raise_error():
    """raise_error 抛出 AppError。"""
    import pytest

    with pytest.raises(AppError) as exc_info:
        raise_error(ErrorCode.CONFIG_ERROR, "配置不匹配")
    assert exc_info.value.code == 50001
    assert exc_info.value.http_status == 500
    assert exc_info.value.message == "配置不匹配"


# ============================================================================
# 从 domain.errors 重新导出验证（兼容旧 import 路径）
# ============================================================================


def test_re_export_from_domain_errors():
    """domain/errors.py 重新导出 AppError、ErrorCode、raise_error。"""
    from ragnexus.domain.errors import AppError as DomainAppError
    from ragnexus.domain.errors import ErrorCode as DomainErrorCode
    from ragnexus.domain.errors import raise_error as domain_raise_error

    assert DomainAppError is AppError
    assert DomainErrorCode is ErrorCode
    assert domain_raise_error is raise_error
