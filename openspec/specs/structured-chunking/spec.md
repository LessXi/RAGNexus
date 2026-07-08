# structured-chunking Specification

## Purpose
TBD - created by archiving change structured-markdown-chunking. Update Purpose after archive.
## Requirements
### Requirement: Markdown 文档按标题层级结构化切块

系统 SHALL 在上传 `.md` 文档时，按 `#` / `##` 标题边界分节切块，不在标题行中间截断，不在小节中间截断。

`###` 及更深层级标题的内容 SHALL 归入其所属的最近 `##` 或 `#` 节的 chunk 中，不单独成块。

#### Scenario: 含二级标题的文档正确分节

- **GIVEN** 一篇 Markdown 文档含 `# 测试知识库`、`## 第一节` 及其内容、`## 第二节` 及其内容
- **WHEN** 系统对该文档执行索引
- **THEN** 至少生成 2 个 chunk，分别对应「第一节」和「第二节」
- **AND** chunk 不在 `## 第` 这样的标题行中间截断
- **AND**「第一节」的 chunk 的 `heading_path` 为 `"测试知识库 / 第一节"`
- **AND**「第二节」的 chunk 的 `heading_path` 为 `"测试知识库 / 第二节"`

#### Scenario: 三级标题归入上级节

- **GIVEN** 文档「第一节」下含 `### 1.1 子内容` 段落
- **WHEN** 系统对该文档执行索引
- **THEN** `### 1.1 子内容` 下的段落出现在「第一节」的 chunk 中
- **AND** 不存在仅含三级标题内容的独立 chunk

#### Scenario: 无标题文档回退

- **GIVEN** 一篇不含 `#` 或 `##` 的 `.md` 文档
- **WHEN** 系统对该文档执行索引
- **THEN** 整篇视为一节，按段落优先或字符窗口切块
- **AND** 行为接近旧 `fixed_size_split` 效果

### Requirement: 表格识别与专项切块

系统 SHALL 识别 Markdown 表格（`| ... |` 行）并将其作为独立 chunk 类型处理。

**小表**（整表字符数不超过 `CHUNK_MAX_CHARS`）SHALL 作为一个完整 chunk，`chunk_type` 为 `table`，content 含完整表头和全部数据行。

**大表**（超过 `CHUNK_MAX_CHARS`）SHALL 保留表头，按每组最多 `TABLE_MAX_ROWS_PER_CHUNK` 条数据行分组成多个 chunk，每个 chunk 的 content 顶部重复表头行，`table_part` 字段从 1 开始递增。

表格与前后段落 SHALL 分开成块，不强行拼合。

#### Scenario: 小表整块存储

- **GIVEN** 一篇 Markdown 文档含一个 3 行数据的小表格
- **WHEN** 系统对该文档执行索引
- **THEN** 该表格作为一个完整 chunk，`chunk_type` 为 `table`
- **AND** content 含完整表头行和全部 3 行数据
- **AND** 不存在表格数据行被截断为半行的 chunk

#### Scenario: 大表分组存储含表头

- **GIVEN** 一篇 Markdown 文档含一个 25 行数据的大表格
- **WHEN** 系统对该文档执行索引，`TABLE_MAX_ROWS_PER_CHUNK` 为 10
- **THEN** 表格被分为 3 个 chunk
- **AND** 每个 chunk 的 content 顶部重复表头行
- **AND** `table_part` 字段从 1 递增到 3
- **AND** 每个 chunk 的 content 不超过 `CHUNK_MAX_CHARS`

### Requirement: chunk metadata 增强

系统 SHALL 为每个 chunk 的 metadata 新增以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `heading_path` | `str` | 标题层级路径，格式 `一级标题 / 二级标题`，纯文本文档为空字符串 |
| `chunk_type` | `str` | 块类型：`section`、`table`、`code`、`list`，纯文本为 `text` |
| `table_part` | `int` | 大表分组序号，仅表格 chunk 有值，从 1 开始 |

同时 SHALL 保留 `heading` 和 `heading_level` 字段以向后兼容。

#### Scenario: heading_path 格式正确

- **GIVEN** chunk 所属节的标题栈为 `["# 平台交易规则", "## 退款时效"]`
- **WHEN** chunk metadata 写入 `heading_path`
- **THEN** `heading_path` 值为 `"平台交易规则 / 退款时效"`
- **AND** 不含 markdown 标记符 `#`

#### Scenario: 纯文本文档 metadata

- **GIVEN** 一篇 `.txt` 纯文本文档
- **WHEN** 系统对该文档执行索引
- **THEN** 所有 chunk 的 `heading_path` 为空字符串
- **AND** 所有 chunk 的 `chunk_type` 为 `text`
- **AND** 索引仍成功完成，不报错

### Requirement: 独立分隔线过滤

独立一行的 `---` SHALL 被过滤，不出现在任何 chunk 的 content 中。

#### Scenario: 分隔线不出现在 chunk 正文

- **GIVEN** 文档在「第一节」和「第二节」之间含独立 `---` 行
- **WHEN** 系统对该文档执行索引
- **THEN** 无任何 chunk 的 content 只含或包含孤立的 `---`
- **AND** 分隔线两侧的内容正常分入各自 chunk

