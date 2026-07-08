# Task 4 Report: PgDocumentRepository 扩展

## 状态: DONE

## RED 证据
新增 3 个测试在实现前全部 FAIL:
1. `TestCreateWithSourceFields::test_create_with_source_fields` — TypeError: `create()` got unexpected keyword argument `source_file_path`
2. `TestGetReturnsSourceFields::test_get_returns_source_fields` — AssertionError: `source_file_path` is `None`
3. `TestUpdateContent::test_update_content` — AttributeError: no attribute `update_content`

11 个现有测试全部 PASS（无回归）。

## GREEN 证据
实现后 `pytest tests/unit/adapters/test_document_repo.py -v`:
- 14 passed (11 原有 + 3 新增), 0 failed
- 全量 unit 测试: 537 passed, 3 个预存在失败（与本次变更无关: feedback_router 验证逻辑、error_code 计数）

## Commit
`adf1de4bd7269db8729cb9ff016878cf341a87b3`

## 变更文件
1. `src/ragnexus/domain/ports.py` — `DocumentPort.create` 签名新增 `source_file_path: str | None = None` / `source_filename: str | None = None`；新增 `update_content(doc_id, content) -> None` 协议方法
2. `src/ragnexus/adapters/document/pg.py` — `create()` 接受新参数并写入 INSERT；`get()` / `get_by_kb()` SELECT 新增两列并在 Document 构造中传递；新增 `update_content()` 执行 UPDATE SET content/updated_at
3. `tests/unit/adapters/test_document_repo.py` — 新增 `TestCreateWithSourceFields`、`TestGetReturnsSourceFields`、`TestUpdateContent`；现有 mock rows 补充 `source_file_path=None, source_filename=None`

## 顾虑
无。所有变更严格按照 brief，零破坏验证通过。
