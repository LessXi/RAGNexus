# retrieve-api Specification (Delta)

## MODIFIED Requirements

### Requirement: 检索响应 chunk metadata 包含结构化切块信息

`POST /v1/rag:retrieve` 响应的 `hits[].metadata` SHALL 新增以下字段（来自 chunk 的 metadata）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading_path` | `str` | 标题层级路径，纯文本为空字符串 |
| `chunk_type` | `str` | `section` / `table` / `code` / `list` / `text` |

新增字段 SHALL 向下兼容：使用旧切块器索引的文档，这两个字段为 `null` 或空值。

`_serialize_hit()` SHALL 保留原有行为，新字段随 `h.metadata` 自动透传，无需 JSON 序列化层改动。

#### Scenario: 结构化切块的文档检索

- **GIVEN** 一篇已用结构化切块索引的文档，chunk metadata 含 `heading_path: "平台交易规则 / 退款时效"` 和 `chunk_type: "section"`
- **WHEN** 调用 `POST /v1/rag:retrieve` 检索到该 chunk
- **THEN** 响应 `hits[].metadata.heading_path` 为 `"平台交易规则 / 退款时效"`
- **AND** `hits[].metadata.chunk_type` 为 `"section"`

#### Scenario: 旧切块器索引的文档兼容

- **GIVEN** 一篇用旧切块器索引的文档，chunk metadata 不含 `heading_path` 和 `chunk_type`
- **WHEN** 调用 `POST /v1/rag:retrieve` 检索到该 chunk
- **THEN** 响应不报错
- **AND** `hits[].metadata.heading_path` 为 `null` 或空
- **AND** `hits[].metadata.chunk_type` 为 `null` 或空

#### Scenario: 表格 chunk 检索

- **GIVEN** 一篇含表格的文档，表格 chunk metadata 含 `chunk_type: "table"` 和 `heading_path: "平台交易规则 / 叠加规则"`
- **WHEN** 检索 "满减和优惠券能否叠加"
- **THEN** Top chunk 的 `chunk_type` 为 `"table"`
- **AND** `heading_path` 含正确的章节路径
- **AND** content 含完整表头行

### Requirement: 调试台展示 chunk 元信息

检索调试台页面 `/retrieve` 的 chunk 卡片 SHALL 在 content 折叠区上方展示 `heading_path` 和 `chunk_type`（当两者有值时）。

#### Scenario: 调试台展示章节和类型

- **GIVEN** 检索结果包含一个 `heading_path: "测试知识库 / 第一节"`、`chunk_type: "section"` 的 chunk
- **WHEN** 用户在调试台查看检索结果
- **THEN** 该 chunk 卡片上展示 `所属章节：测试知识库 / 第一节` 和 `块类型：section`

#### Scenario: 无章节信息的 chunk

- **GIVEN** 检索结果包含一个 `heading_path` 为空且无 `chunk_type` 的 chunk（如纯文本文档）
- **WHEN** 用户在调试台查看检索结果
- **THEN** 该 chunk 卡片不展示章节和块类型行，其他信息正常显示
