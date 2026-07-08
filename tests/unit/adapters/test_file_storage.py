"""测试 LocalFileStorage 适配器。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ragnexus.adapters.file_storage import LocalFileStorage


@pytest.fixture
def temp_base() -> str:
    """返回临时目录路径，测试后自动清理。"""
    with TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.asyncio
async def test_save_and_read(temp_base: str) -> None:
    """save 后 read 返回相同内容。"""
    storage = LocalFileStorage(base_path=temp_base)
    content = b"hello world"

    path = await storage.save(
        tenant_id="t1", doc_id="d1", filename="test.txt", content=content
    )
    assert isinstance(path, str)
    assert len(path) > 0

    read_back = await storage.read(path)
    assert read_back == content


@pytest.mark.asyncio
async def test_save_creates_directory(temp_base: str) -> None:
    """save 自动创建嵌套目录结构。"""
    storage = LocalFileStorage(base_path=temp_base)
    content = b"data"

    path = await storage.save(
        tenant_id="acme", doc_id="x123", filename="doc.pdf", content=content
    )
    file_path = Path(path)
    assert file_path.exists()
    assert file_path.parent.name == "x123"
    assert file_path.parent.parent.name == "acme"


@pytest.mark.asyncio
async def test_delete_removes_file(temp_base: str) -> None:
    """delete 后文件被移除。"""
    storage = LocalFileStorage(base_path=temp_base)
    content = b"delete me"

    path = await storage.save(
        tenant_id="t2", doc_id="d2", filename="tmp.txt", content=content
    )
    assert Path(path).exists()

    await storage.delete(path)
    assert not Path(path).exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_no_error(temp_base: str) -> None:
    """删除不存在的文件不抛异常。"""
    storage = LocalFileStorage(base_path=temp_base)
    # 对一个不存在的路径调用 delete，不应抛异常
    await storage.delete("/tmp/nonexistent_file_xyz_123")
    # 如果能执行到这里，测试通过
