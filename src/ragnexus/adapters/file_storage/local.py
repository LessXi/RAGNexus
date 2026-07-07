"""LocalFileStorage — 本地文件系统存储适配器。"""

from pathlib import Path

from ragnexus.config import get_settings


class LocalFileStorage:
    """本地文件系统存储 — 实现 FileStoragePort。

    文件路径: {DOCUMENT_STORAGE_PATH}/{tenant_id}/{doc_id}/{filename}
    目录不存在时自动创建。
    """

    def __init__(self, base_path: str | None = None) -> None:
        """初始化存储适配器。

        Args:
            base_path: 存储根目录。默认从 Settings.DOCUMENT_STORAGE_PATH 读取。
        """
        self._base = Path(base_path or get_settings().DOCUMENT_STORAGE_PATH)

    async def save(
        self, tenant_id: str, doc_id: str, filename: str, content: bytes
    ) -> str:
        """保存二进制文件到本地文件系统。

        Args:
            tenant_id: 租户 ID。
            doc_id: 文档 ID。
            filename: 文件名。
            content: 二进制内容。

        Returns:
            保存后的绝对路径。
        """
        target_dir = self._base / tenant_id / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        file_path.write_bytes(content)
        return str(file_path.absolute())

    async def read(self, path: str) -> bytes:
        """从指定路径读取文件。

        Args:
            path: 文件绝对路径。

        Returns:
            文件二进制内容。
        """
        return Path(path).read_bytes()

    async def delete(self, path: str) -> None:
        """删除指定路径的文件。

        文件不存在时静默忽略，不抛异常。

        Args:
            path: 文件绝对路径。
        """
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
