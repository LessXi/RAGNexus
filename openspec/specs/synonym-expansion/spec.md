# synonym-expansion Specification

## Purpose
TBD - created by archiving change query-semantic-optimization. Update Purpose after archive.
## Requirements
### Requirement: KB settings CRUD

The system SHALL implement this requirement.

`KnowledgeBasePort` 新增两个方法：

```python
async def get_settings(self, kb_id: str) -> dict: ...
async def update_settings(self, kb_id: str, settings: dict) -> None: ...
```

`KnowledgeBase` 模型新增 `settings: dict` 字段（默认 `{}`）。`PgKnowledgeBaseRepository.create()` 中 settings 默认 `{}`。

#### Scenario: KB 创建时 settings 默认空
- **GIVEN** 新建 KB 不传 settings
- **WHEN** KB 创建完成
- **THEN** `kb.settings` = `{}`

#### Scenario: update_settings 整文件覆盖
- **GIVEN** KB_A.settings = `{"synonyms": [...]}`
- **WHEN** `update_settings(kb_id, {"synonyms": [新词表]})`
- **THEN** KB_A.settings = `{"synonyms": [新词表]}`，旧的被完全替换

#### Scenario: get_settings 对不存在 KB 返回错误
- **GIVEN** kb_id 不存在
- **WHEN** 调用 `get_settings(kb_id)`
- **THEN** 抛出异常（与现有 `get()` 行为一致）

