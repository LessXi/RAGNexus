# Task 2 Report: 配置变更

## 状态: DONE

## RED 证据（基线）

```
pytest tests/unit/test_config.py tests/unit/application/test_upload_doc.py -v
11 passed in 0.33s
```

## GREEN 证据（实现后）

```
pytest tests/unit/test_config.py tests/unit/application/test_upload_doc.py -v
11 passed in 0.36s
```

## Commit

```
bc792c4 (4 files +18 -6)
"feat: add DOCUMENT_STORAGE_PATH and DOCUMENT_MAX_SIZE_MB config"
```

## 变更文件

| 文件 | 变更 |
|------|------|
| `src/ragnexus/config.py` | 在 CHUNK_OVERLAP 后新增 `DOCUMENT_STORAGE_PATH`（`"./data/uploads"`）和 `DOCUMENT_MAX_SIZE_MB`（20）；`MAX_FILE_SIZE` 改为 `20 * 1024 * 1024` |
| `src/ragnexus/application/upload_doc_use_case.py` | `max_file_size` 默认值从 `10 * 1024 * 1024` 改为 `20 * 1024 * 1024` |
| `src/ragnexus/composition.py` | **无需修改** — 已使用 `cfg.MAX_FILE_SIZE` |
| `tests/unit/test_config.py` | 新增 `DOCUMENT_STORAGE_PATH`/`DOCUMENT_MAX_SIZE_MB` 断言；`MAX_FILE_SIZE` 断言改为 20MB；新增 `monkeypatch.delenv` 隔离环境变量干扰 |
| `tests/unit/application/test_upload_doc.py` | `test_file_too_large` 文件大小从 `10 * 1024 * 1024 + 1` 改为 `20 * 1024 * 1024 + 1` |

## 顾虑

- **预提交钩子缺失 pre_commit 模块**：`pre-commit` 未安装，需 `uv pip install pre-commit && pre-commit install` 修复（非本任务范围）
- **环境变量干扰**：系统 env `MAX_FILE_SIZE=10485760`（10MB）会覆盖代码默认值，已通过 `monkeypatch.delenv` 隔离
