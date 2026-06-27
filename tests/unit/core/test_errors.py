"""RAGNexus 统一错误码系统测试
注：spec 完整清单共 33 条（与本测试一致），spec 头标 40+、step 4 说 34 条，差异需确认。
"""

import pytest

from ragnexus.core.errors import AppError, ErrorCode, raise_error


class TestErrorCode:
    """ErrorCode 枚举成员值校验"""

    # 按区间分类的参数化测试数据
    SUCCESS_CASES = [
        (ErrorCode.SUCCESS, 0, 200, "成功"),
    ]

    PARAM_CASES = [
        (ErrorCode.PARAM_ERROR, 10001, 422, "参数错误"),
        (ErrorCode.PARAM_MISSING, 10002, 422, "缺少必要参数"),
        (ErrorCode.PARAM_INVALID, 10003, 422, "参数格式无效"),
        (ErrorCode.PARAM_RANGE_ERROR, 10004, 422, "参数超出允许范围"),
    ]

    AUTH_CASES = [
        (ErrorCode.UNAUTHORIZED, 10200, 401, "未授权，请登录"),
        (ErrorCode.FORBIDDEN, 10201, 403, "权限不足"),
        (ErrorCode.TOKEN_EXPIRED, 10202, 401, "登录已过期"),
    ]

    RESOURCE_CASES = [
        (ErrorCode.NOT_FOUND, 10300, 404, "资源不存在"),
        (ErrorCode.RESOURCE_CONFLICT, 10301, 409, "资源冲突"),
        (ErrorCode.RESOURCE_EXISTS, 10302, 409, "资源已存在"),
    ]

    FILE_CASES = [
        (ErrorCode.UNSUPPORTED_FORMAT, 10400, 415, "不支持的文件类型"),
        (ErrorCode.FILE_TOO_LARGE, 10401, 413, "文件过大"),
        (ErrorCode.FILE_EMPTY, 10402, 422, "文件为空"),
    ]

    UPSTREAM_CASES = [
        (ErrorCode.UPSTREAM_ERROR, 10500, 502, "上游服务异常"),
        (ErrorCode.UPSTREAM_TIMEOUT, 10501, 504, "上游服务超时"),
    ]

    API_CASES = [
        (ErrorCode.API_TIMEOUT, 20001, 504, "接口请求超时"),
        (ErrorCode.API_RATE_LIMIT, 20002, 429, "接口调用超限"),
        (ErrorCode.API_METHOD_ERROR, 20003, 405, "请求方法错误"),
    ]

    DB_CASES = [
        (ErrorCode.DB_ERROR, 30001, 500, "数据库操作失败"),
        (ErrorCode.DB_CONNECTION_ERROR, 30002, 503, "数据库连接失败"),
        (ErrorCode.DB_QUERY_TIMEOUT, 30003, 504, "数据库查询超时"),
        (ErrorCode.DATA_DUPLICATE, 30004, 409, "数据已存在"),
    ]

    MODEL_CASES = [
        (ErrorCode.MODEL_ERROR, 40000, 502, "大模型调用失败"),
        (ErrorCode.MODEL_TIMEOUT, 40001, 504, "大模型响应超时"),
        (ErrorCode.MODEL_NO_RESPONSE, 40002, 502, "大模型未返回有效内容"),
        (ErrorCode.MODEL_CONTENT_VIOLATION, 40003, 422, "内容违规"),
        (ErrorCode.MODEL_TOKEN_LIMIT, 40004, 422, "上下文长度超限"),
        (ErrorCode.MODEL_RATE_LIMIT, 40005, 429, "大模型调用频率超限"),
        (ErrorCode.MODEL_NOT_AVAILABLE, 40006, 503, "模型不存在或未部署"),
    ]

    SYSTEM_CASES = [
        (ErrorCode.SERVER_ERROR, 50000, 500, "服务器异常"),
        (ErrorCode.CONFIG_ERROR, 50001, 500, "服务配置错误"),
        (ErrorCode.SYSTEM_BUSY, 50002, 503, "系统繁忙，请稍后再试"),
    ]

    ALL_CASES = (
        SUCCESS_CASES
        + PARAM_CASES
        + AUTH_CASES
        + RESOURCE_CASES
        + FILE_CASES
        + UPSTREAM_CASES
        + API_CASES
        + DB_CASES
        + MODEL_CASES
        + SYSTEM_CASES
    )

    @pytest.mark.parametrize("member,expected_code,expected_http,expected_msg", ALL_CASES)
    def test_error_code_values(self, member, expected_code, expected_http, expected_msg):
        """校验每个 ErrorCode 成员的 code、http_status、msg 属性"""
        assert member.code == expected_code, f"{member.name}: code mismatch"
        assert member.http_status == expected_http, f"{member.name}: http_status mismatch"
        assert member.msg == expected_msg, f"{member.name}: msg mismatch"

    def test_total_count(self):
        """确认枚举成员总数 —— 33 条，与 spec 完整清单一致（spec 头标 40+、step 4 说 34 条，留意）"""
        assert len(list(ErrorCode)) == 33


class TestAppError:
    """AppError 异常类测试"""

    def test_is_exception_subclass(self):
        """AppError 是 Exception 子类"""
        assert issubclass(AppError, Exception)

    def test_construct_with_default_message(self):
        """使用 ErrorCode 构造 AppError，message 默认取 ErrorCode.msg"""
        err = AppError(ErrorCode.NOT_FOUND)
        assert err.code == 10300
        assert err.http_status == 404
        assert err.message == "资源不存在"

    def test_construct_with_custom_message(self):
        """传入自定义 message 覆盖默认值"""
        err = AppError(ErrorCode.PARAM_ERROR, message="用户名不能为空")
        assert err.code == 10001
        assert err.http_status == 422
        assert err.message == "用户名不能为空"

    def test_construct_with_errors_list(self):
        """AppError 支持 errors 列表（字段级错误详情）"""
        details = [{"field": "email", "reason": "格式不正确"}]
        err = AppError(ErrorCode.PARAM_INVALID, errors=details)
        assert err.errors == details

    def test_errors_default_empty_list(self):
        """不传 errors 时默认为空列表"""
        err = AppError(ErrorCode.SERVER_ERROR)
        assert err.errors == []

    def test_http_status_from_enum(self):
        """http_status 来自 ErrorCode 成员值"""
        err = AppError(ErrorCode.FORBIDDEN)
        assert err.http_status == 403

    def test_code_from_enum(self):
        """code 来自 ErrorCode 成员值"""
        err = AppError(ErrorCode.DB_CONNECTION_ERROR)
        assert err.code == 30002

    def test_success_code(self):
        """SUCCESS 错误码（0, 200）"""
        err = AppError(ErrorCode.SUCCESS)
        assert err.code == 0
        assert err.http_status == 200
        assert err.message == "成功"


class TestRaiseError:
    """raise_error() 快捷函数测试"""

    def test_raise_error_raises_app_error(self):
        """raise_error 抛出 AppError"""
        with pytest.raises(AppError) as exc_info:
            raise_error(ErrorCode.UNAUTHORIZED)
        assert exc_info.value.code == 10200
        assert exc_info.value.http_status == 401

    def test_raise_error_with_custom_message(self):
        """raise_error 支持自定义 message"""
        with pytest.raises(AppError) as exc_info:
            raise_error(ErrorCode.FORBIDDEN, message="您没有此资源的访问权限")
        assert exc_info.value.message == "您没有此资源的访问权限"

    def test_raise_error_with_errors_list(self):
        """raise_error 支持 errors 列表"""
        with pytest.raises(AppError) as exc_info:
            raise_error(ErrorCode.PARAM_ERROR, errors=[{"field": "name", "reason": "必填"}])
        assert exc_info.value.errors == [{"field": "name", "reason": "必填"}]
