"""Tests for domain/errors.py — DomainError hierarchy."""

from ragnexus.domain.errors import (
    ConfigError,
    ConflictError,
    DomainError,
    DuplicateDocumentError,
    EmptyFileError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    UpstreamError,
    ValidationError,
)


def test_error_codes():
    """All 9 subclasses have distinct codes 1000–1600."""
    assert ValidationError.code == 1000
    assert NotFoundError.code == 1100
    assert ConflictError.code == 1200
    assert DuplicateDocumentError.code == 1201
    assert UnsupportedMediaTypeError.code == 1300
    assert PayloadTooLargeError.code == 1301
    assert EmptyFileError.code == 1400
    assert UpstreamError.code == 1500
    assert ConfigError.code == 1600


def test_http_status():
    """Each error has the correct HTTP status."""
    assert ValidationError.http_status == 422
    assert NotFoundError.http_status == 404
    assert ConflictError.http_status == 409
    assert DuplicateDocumentError.http_status == 409
    assert UnsupportedMediaTypeError.http_status == 415
    assert PayloadTooLargeError.http_status == 413
    assert EmptyFileError.http_status == 422
    assert UpstreamError.http_status == 502
    assert ConfigError.http_status == 500


def test_error_fields():
    """DomainError stores message and errors list correctly."""

    err2 = DomainError(message="oops", errors=[{"field": "name", "reason": "required"}])
    assert err2.message == "oops"
    assert err2.errors == [{"field": "name", "reason": "required"}]

    err3 = DomainError(message="just text")
    assert err3.message == "just text"
    assert err3.errors == []

    # Default code and http_status on base class
    assert DomainError.code == 9999
    assert DomainError.http_status == 500


def test_inheritance():
    """Subclass chains are correct."""
    # DuplicateDocumentError inherits from ConflictError
    assert issubclass(DuplicateDocumentError, ConflictError)
    assert issubclass(DuplicateDocumentError, DomainError)
    assert isinstance(DuplicateDocumentError(), ConflictError)
    assert isinstance(DuplicateDocumentError(), DomainError)
    # But not the reverse
    assert not issubclass(ConflictError, DuplicateDocumentError)

    # All error classes are DomainError subclasses
    for exc in [
        ValidationError,
        NotFoundError,
        ConflictError,
        DuplicateDocumentError,
        UnsupportedMediaTypeError,
        PayloadTooLargeError,
        EmptyFileError,
        UpstreamError,
        ConfigError,
    ]:
        assert issubclass(exc, DomainError), f"{exc.__name__} is not a DomainError subclass"


def test_error_instantiation():
    """Each error can be instantiated with or without message."""
    ValidationError()
    ValidationError("自定义验证错误")
    NotFoundError("资源未找到")
    ConflictError("冲突")
    DuplicateDocumentError("文档已存在")
    UnsupportedMediaTypeError()
    PayloadTooLargeError()
    EmptyFileError()
    UpstreamError("上游挂了")
    ConfigError("配置错误")
