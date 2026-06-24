"""Domain errors — pure exception hierarchy, no framework dependencies."""


class DomainError(Exception):
    code: int = 9999
    http_status: int = 500
    message: str = ""

    def __init__(self, message: str | None = None, errors: list[dict] | None = None):
        super().__init__(message or self.message)
        self.message_text = message
        self.errors = errors or []


class ValidationError(DomainError):
    code, http_status, message = 1000, 422, "参数错误"


class NotFoundError(DomainError):
    code, http_status, message = 1100, 404, "资源不存在"


class ConflictError(DomainError):
    code, http_status, message = 1200, 409, "资源冲突"


class DuplicateDocumentError(ConflictError):
    code, http_status, message = 1201, 409, "文档已存在"


class UnsupportedMediaTypeError(DomainError):
    code, http_status, message = 1300, 415, "不支持的文件类型"


class PayloadTooLargeError(DomainError):
    code, http_status, message = 1301, 413, "文件过大"


class EmptyFileError(DomainError):
    code, http_status, message = 1400, 422, "文件为空"


class UpstreamError(DomainError):
    code, http_status, message = 1500, 502, "上游服务异常"


class VectorStoreError(UpstreamError):
    code, http_status, message = 1501, 502, "向量库失败"


class ConfigError(DomainError):
    code, http_status, message = 1600, 500, "配置不匹配"
