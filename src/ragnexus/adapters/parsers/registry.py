"""Parser 注册表 — 按文件扩展名选择 ParserPort 实现。"""

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.ports import ParserPort

_parsers: dict[str, ParserPort] = {}


def register(ext: str, parser: ParserPort) -> None:
    """注册扩展名对应的 parser。ext 可为 '.docx' 或 'docx'。"""
    _parsers[ext.lstrip(".").lower()] = parser


def get_parser(filename: str) -> ParserPort:
    """按 filename 扩展名查找 parser，未匹配抛 UNSUPPORTED_FORMAT。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _parsers.get(ext)
    if parser is None:
        raise AppError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"不支持的文件类型: .{ext}",
        )
    return parser
