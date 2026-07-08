# synonym-expansion

词表扩展：基于知识库级可配置词表，确定性追加扩展词到检索句。

## ADDED Requirements

### Requirement: 词表配置存储

The system SHALL implement this requirement.

`knowledge_bases.settings` JSONB 字段新增 `synonyms` 键，格式：

```json
{
  "synonyms": [
    {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
    {"terms": ["薪酬", "薪资", "工资"], "expand": ["职级", "薪酬定级", "定级标准"]}
  ]
}
```

#### Scenario: KB 有词表
- **GIVEN** KB_A.settings.synonyms 包含 2 组同义词
- **WHEN** 查询 KB_A 的 settings
- **THEN** 返回 2 组 synonyms

#### Scenario: KB 无词表
- **GIVEN** KB_B.settings 为 `{}` 或 `synonyms` 为空数组
- **WHEN** 词表扩展执行
- **THEN** `synonym_applied` = false, 无扩展词

### Requirement: 词表精确子串匹配

The system SHALL implement this requirement.

`SynonymExpander.expand(effective_query, synonyms)` → `(search_query, synonym_applied, expansions)`。中文精确子串匹配，英文忽略大小写。

#### Scenario: 单组命中
- **GIVEN** `synonyms = [{"terms": ["背调"], "expand": ["背景调查"]}]`
- **WHEN** `effective_query = "背调要问啥"`
- **THEN** `synonym_applied` = true
- **AND** `synonym_expansions` = ["背景调查"]
- **AND** `search_query` = "背调要问啥 背景调查"

#### Scenario: 多组同时命中，扩展词去重
- **GIVEN** 组1: `{"terms": ["背调"], "expand": ["背景调查", "清单"]}`, 组2: `{"terms": ["工资"], "expand": ["薪酬", "清单"]}`
- **WHEN** `effective_query = "背调和工资怎么谈"`
- **THEN** `synonym_expansions` 去重后 = ["背景调查", "清单", "薪酬"]

#### Scenario: 未命中
- **GIVEN** `synonyms = [{"terms": ["背调"], "expand": ["背景调查"]}]`
- **WHEN** `effective_query = "面试官行为规范"`
- **THEN** `synonym_applied` = false, `search_query` = `effective_query`

#### Scenario: 英文 term 忽略大小写
- **GIVEN** `synonyms = [{"terms": ["API"], "expand": ["接口"]}]`
- **WHEN** `effective_query = "api 文档在哪里"`
- **THEN** `synonym_applied` = true, `search_query` 含 "接口"

#### Scenario: synonyms 格式错误时容错
- **GIVEN** synonyms 为 `[{"terms": "背调"}]`（不是数组）
- **WHEN** 词表扩展执行
- **THEN** `synonym_applied` = false, 不抛异常

### Requirement: 跨库词表隔离

The system SHALL implement this requirement.

词表仅对当前 KB 生效，不跨库。

#### Scenario: KB_A 词表不影响 KB_B
- **GIVEN** KB_A 有 "背调" 扩展词, KB_B settings 为 `{}`
- **WHEN** 对 KB_B 检索 query="背调要问啥"
- **THEN** `synonym_applied` = false

## ADDED Requirements

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
