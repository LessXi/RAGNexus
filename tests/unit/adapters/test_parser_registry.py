"""Parser registry 单元测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ragnexus.adapters.parsers.registry import register, get_parser, _parsers
from ragnexus.core.errors import AppError, ErrorCode


@pytest.fixture(autouse=True)
def clear_registry():
    """每个测试前清空 registry。"""
    _parsers.clear()
    yield
    _parsers.clear()


class TestParserRegistry:
    """registry 注册与查找测试。"""

    async def test_register_and_get(self):
        """register 后 get_parser 返回正确 parser。"""
        mock = MagicMock()
        register("docx", mock)
        result = get_parser("report.docx")
        assert result is mock

    async def test_get_unknown_extension(self):
        """未知扩展名抛 UNSUPPORTED_FORMAT。"""
        with pytest.raises(AppError) as exc_info:
            get_parser("file.xyz")
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FORMAT.code

    async def test_no_extension(self):
        """无扩展名的文件抛 UNSUPPORTED_FORMAT。"""
        with pytest.raises(AppError) as exc_info:
            get_parser("no_extension_file")
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FORMAT.code

    async def test_register_with_dot_prefix(self):
        """带 '.' 前缀的扩展名也能正确注册。"""
        mock = MagicMock()
        register(".pdf", mock)
        result = get_parser("doc.pdf")
        assert result is mock
