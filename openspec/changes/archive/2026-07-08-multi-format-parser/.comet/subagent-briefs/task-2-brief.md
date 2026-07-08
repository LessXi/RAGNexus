# Task 2: 配置变更

## Plan Section

来自 `docs/superpowers/plans/2026-07-07-multi-format-parser.md` Task 2。

### 目标

新增 `DOCUMENT_STORAGE_PATH` 和 `DOCUMENT_MAX_SIZE_MB` 配置项，调整 `MAX_FILE_SIZE` 默认值为 20MB。

### 要修改的文件

1. `src/ragnexus/config.py` — 在 CHUNK_OVERLAP 后新增 2 个字段，修改 MAX_FILE_SIZE 默认值
2. `src/ragnexus/composition.py` — upload_doc_uc 构造处（确保使用 cfg.MAX_FILE_SIZE）
3. `src/ragnexus/application/upload_doc_use_case.py` — max_file_size 默认值从 10MB 改为 20MB

### 变更详述

#### config.py (当前 line 45-46)

当前:
```python
    CHUNK_OVERLAP: int = 50
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
```

修改为:
```python
    CHUNK_OVERLAP: int = 50
    DOCUMENT_STORAGE_PATH: str = Field(default="./data/uploads")           # 新增
    DOCUMENT_MAX_SIZE_MB: int = Field(default=20)                          # 新增
    MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20MB（由 DOCUMENT_MAX_SIZE_MB 换算）
```

#### upload_doc_use_case.py (当前 line 47)

当前:
```python
        max_file_size: int = 10 * 1024 * 1024,
```

改为:
```python
        max_file_size: int = 20 * 1024 * 1024,  # 20MB（原 10 * 1024 * 1024）
```

#### composition.py

检查 upload_doc_uc 构造处的 `max_file_size=cfg.MAX_FILE_SIZE` 是否已存在（计划说约 line 474）。如果已存在 `cfg.MAX_FILE_SIZE`，**不需要修改**（MAX_FILE_SIZE 已经是 20MB）。如果写死为 `10 * 1024 * 1024`，改为 `cfg.MAX_FILE_SIZE`。

##### 搜索方式

```bash
grep -n "max_file_size" src/ragnexus/composition.py
```

如果结果是 `max_file_size=cfg.MAX_FILE_SIZE` 则跳过。如果是 `max_file_size=10 * 1024 * 1024` 则修改。

### 测试命令

```bash
pytest tests/unit/application/test_upload_doc.py tests/unit/test_config.py -v
```

如果 `test_config.py` 不存在，至少运行 upload_doc 测试。

### Commit

```bash
git add src/ragnexus/config.py src/ragnexus/composition.py src/ragnexus/application/upload_doc_use_case.py
git commit -m "feat: add DOCUMENT_STORAGE_PATH and DOCUMENT_MAX_SIZE_MB config"
```

## 全局约束
- 零破坏
- 中文注释

## 回报要求

1. **状态**: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
2. **RED 证据**: TDD 模式 — 先写失败测试（如适用），运行命令 + 失败输出摘要
3. **GREEN 证据**: 实现后测试通过
4. **Commit**: 完整 commit hash
5. **变更文件**: 列表
6. **顾虑**: 如有
