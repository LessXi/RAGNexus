# Task 5: 文件存储适配器 (LocalFileStorage)

## Plan Section

来自 plan Task 5。

### 目标

创建 `LocalFileStorage` 适配器，实现 `FileStoragePort` 协议。

### 要创建/修改的文件

1. **Create**: `src/ragnexus/adapters/file_storage/__init__.py`
2. **Create**: `src/ragnexus/adapters/file_storage/local.py`
3. **Create**: `tests/unit/adapters/test_file_storage.py`

### 变更详述

#### __init__.py
```python
"""文件存储适配器 — 实现 FileStoragePort。"""
from ragnexus.adapters.file_storage.local import LocalFileStorage

__all__ = ["LocalFileStorage"]
```

#### local.py
```python
"""LocalFileStorage — 本地文件系统存储适配器。"""
from pathlib import Path
from ragnexus.config import get_settings

class LocalFileStorage:
    """本地文件系统存储 — 实现 FileStoragePort。
    文件路径: {DOCUMENT_STORAGE_PATH}/{tenant_id}/{doc_id}/{filename}
    目录不存在时自动创建。
    """
    def __init__(self, base_path: str | None = None) -> None:
        self._base = Path(base_path or get_settings().DOCUMENT_STORAGE_PATH)

    async def save(self, tenant_id: str, doc_id: str, filename: str, content: bytes) -> str:
        target_dir = self._base / tenant_id / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename
        file_path.write_bytes(content)
        return str(file_path.absolute())

    async def read(self, path: str) -> bytes:
        return Path(path).read_bytes()

    async def delete(self, path: str) -> None:
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
```

#### test_file_storage.py
4 个测试：
- `test_save_and_read` — save 后 read 返回相同内容
- `test_save_creates_directory` — 自动创建目录
- `test_delete_removes_file` — 删除后文件不存在
- `test_delete_nonexistent_no_error` — 删除不存在的文件不抛异常

使用 `tempfile.TemporaryDirectory` 作为 base_path fixture。

### 测试命令
```bash
pytest tests/unit/adapters/test_file_storage.py -v
```

### Commit
```bash
git add src/ragnexus/adapters/file_storage/ tests/unit/adapters/test_file_storage.py
git commit -m "feat: add LocalFileStorage adapter implementing FileStoragePort"
```

## 全局约束
- 中文注释
- TDD

## 回报要求
1. DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
2. RED/GREEN 证据
3. Commit hash + changed files + concerns
