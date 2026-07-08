# 对抗性交叉评审 — multi-format-parser

> 评审时间: 2026-07-07 | 评审方法: 逐文档对比 × 交叉验证 × 第一性原理

## 评审范围

| # | 文档 | 位置 |
|---|------|------|
| A | proposal.md | `openspec/changes/multi-format-parser/proposal.md` |
| B | design.md (OpenSpec) | `openspec/changes/multi-format-parser/design.md` |
| C | tasks.md | `openspec/changes/multi-format-parser/tasks.md` |
| D | Superpowers Design Doc | `docs/superpowers/specs/2026-07-07-multi-format-parser-design.md` |
| E | 实施计划 | `docs/superpowers/plans/2026-07-07-multi-format-parser.md` |
| F | brainstorm-summary | `openspec/changes/multi-format-parser/.comet/handoff/brainstorm-summary.md` |
| G | 融合分析 | `docs/superpowers/multi-format-parser-fusion-analysis.md` |

---

## 🔴 CRITICAL — 阻塞性矛盾

### C1. `source_type` 列策略：三分文档三种说法

| 文档 | 说法 |
|------|------|
| A proposal.md L16 | "增加 `source_file_path`、`source_filename`、**`source_type`** 字段" → 新增 3 列 |
| C tasks.md L23 | "ALTER ADD `source_file_path` TEXT、`source_filename` TEXT、**`source_type` TEXT** DEFAULT 'text'" → 新增 3 列 |
| D Design Doc §3.2 L86 | "`source_type` **复用 `content_type`** 字段而非新增列" → 只新增 2 列 |
| E 实施计划 Global Constraints L23 | "`source_type` 复用 `content_type` 字段，**不新增数据库列**" → 只新增 2 列 |
| G 融合分析 §4.5 | "ALTER TABLE documents ADD **`source_type` TEXT** DEFAULT 'text'" → 新增 3 列 |

**结论**: A/C/G 说新增 `source_type` 列，D/E 说复用 `content_type`。这是**阻塞性矛盾**——实施时必然出现 "按哪个做" 的分歧。

**推荐**: 统一为 D/E 的方案（复用 `content_type`），理由：(1) 减少 migration 列数 → 降低风险；(2) `content_type` 在上传时已有 MIME type，自然承载格式语义；(3) 只需 `source_file_path` + `source_filename` 两个新列。需同步修改 A、C、G。

### C2. `mammoth.docx.DocumentReader` 类可能不存在

E 实施计划 Task 6 Step 2 (L661) 使用 `mammoth.docx.DocumentReader`：

```python
with mammoth.docx.DocumentReader(io.BytesIO(content)) as reader:
    document = reader.read()
```

**风险**: mammoth 的公开 API 只有 `mammoth.convert_to_markdown()` 和 `mammoth.extract_raw_text()`。`mammoth.docx.DocumentReader` 是内部实现细节，**不在公开 API 中**，随时可能因版本升级而消失。

D Design Doc §4.2 (L167) 意识到了这个风险并给出了备选方案：
> 回退到 `mammoth.convert_to_markdown()` + 复用 `MarkdownAndTextParser._parse_markdown()`

E 实施计划代码 (L639-648) 也实现了 try/except 回退，但 try 路径**必然失败**（因为 DocumentReader 不存在或签名不对），这意味着**每次解析都会走异常路径再回退**，浪费 CPU 且可能产生不必要错误日志。

**推荐**: 直接使用 mammoth 的公开 API + MarkdownAndTextParser 回退路径作为**主路径**，移除对 `DocumentReader` 的依赖。或者确认 mammoth 版本中确实有此 API 后再保留 AST 路径，否则应标记为 "待验证" 而非默认策略。

### C3. `mammoth` 版本号不统一

| 文档 | 版本 |
|------|------|
| A proposal.md L39 | `mammoth>=1.6.0` |
| C tasks.md L54 | `mammoth>=1.6.0` |
| D Design Doc §11 L405 | `mammoth>=1.8.0` |
| E 实施计划 L15 | `mammoth>=1.8.0` |

两个不同的最低版本。如果最终用 1.6.0 但代码依赖了 1.8.0 的特性（如 DocumentReader），会在安装阶段失败。

**推荐**: 统一为 `mammoth>=1.8.0`（更保守），同步修改 A 和 C。

---

## 🟡 MEDIUM — 设计缺陷与遗漏

### M1. 错误码区间标注错误

C tasks.md L3: "20023，区间 **10400-10499** 文件与媒体"

20023 在 errors.py 的 20000-20999（接口与HTTP）区间，不在 10400-10499（文件与媒体）。D Design Doc §8 正确放置了 20023 在 DOCUMENT_PARSE_FAILED 表格中。

**推荐**: 修正 C tasks.md 的注释为 "20023，区间 20020~20029（反馈/解析）"。

### M2. IndexingService 双路径设计未完全解决

D Design Doc §6.2 (L330-354) 详细讨论了一个设计冲突：
- `_prepare_content` 更新了 `doc.content`，然后 `self._parser.parse(doc.content.encode(), doc.filename)` 会再次 parse
- 对 `.docx` 文件，`MarkdownAndTextParser` 会将文件名当 text 处理（因为不是 `.md`），丢失 sections 结构
- 提出修正方案：`_prepare_and_parse()` 直接返回 ParsedDocument，跳过二次 parse

**但 D 最终伪代码 (L337-353) 只是"修正方案"，未明确是最终方案。E 实施计划 Task 8 (IndexingService) 需要明确采取哪个路径。**

**推荐**: 在 D 中明确标注"最终方案：分路径处理"，在 E 中按此实现。

### M3. `DocumentPort.create()` 签名变更未显式列入任务

当前 `DocumentPort.create()` 签名：
```python
async def create(self, *, doc_id, kb_id, filename, file_hash, file_size, content_type, content) -> Document:
```

新增 `source_file_path` 和 `source_filename` 参数后，签名变为：
```python
async def create(self, *, ..., source_file_path=None, source_filename=None) -> Document:
```

C tasks.md L23-25 (4.2) 说 "更新 PgDocumentRepository：create 和 get 支持新字段"，但没有显式列出 `DocumentPort` 协议也需要更新。E 实施计划 Task 4 Step 1 正确包含了这个变更，但 C tasks.md 应该更明确。

**推荐**: 在 C tasks.md 4.2 中增加 "更新 `DocumentPort.create()` 协议签名"。

### M4. `DocumentPort` 缺少 `update_content` 方法

D Design Doc §6.1 (L314) 调用了 `self._doc_repo.update_content(doc_id, content=parsed.raw_text)`，但当前 `DocumentPort` 协议和 `PgDocumentRepository` 都没有这个方法。现有的 `update_status` 只支持 status/error_message/chunk_count。

**推荐**: 在 C tasks.md 和 E 实施计划中增加 "新增 `DocumentPort.update_content()` 方法" 任务。

### M5. reparse 任务的完整性

D Design Doc §7 (L358-362) 描述了 reparse 逻辑：清除 content → 重新 `_prepare_content` → 重新 index。

但 E 实施计划 Task 11 (reparse) 需要确认：
- "清除 content" 需要一个新的 `update_content(doc_id, content='')` 方法（见 M4）
- "重新 `_prepare_content`" 需要 IndexingService 能区分 "首次解析" 和 "reparse"——两者路径相同但触发条件不同

### M6. PDF 大页面处理

如果单页 PDF 文本超过 `max_chars=1500`，`heading_aware_split` 会将其切为多个子块，所有子块的 heading 都相同（"第 N 页"），丢失页面内部的语义结构。

**风险级别**: 低。这是已知限制（D Design Doc §4.3 说明按页分节），但在 C 和 E 中未作为边界条件记录。

**推荐**: 在测试边界条件中增加 "大页面 PDF → 多 chunk 均含相同 heading" 的验收场景。

---

## 🟢 LOW — 小问题与改进建议

### L1. proposal.md 说 3 列 migration，实际只需 2 列

见 C1。如果采用复用 content_type 方案，proposal.md L16 需要从 "3 列" 改为 "2 列"。

### L2. 缺少 JSON upload 路由的显式任务

C tasks.md §5 有 "新增 POST /v1/documents:upload-text 路由"，但 §6 "索引流水线编排" 中没有 "更新 composition.py 注册新路由" 的显式任务。虽然 6.3 提到 "组装新的 upload use case 和 document router"，但注册路由是额外的步骤。

E 实施计划 Task 9 和 10 覆盖了这一点。

### L3. brainstorm-summary 与 Design Doc 一致性

F brainstorm-summary 说 "mammoth AST API → sections 直接产出"，但 D Design Doc 和 E 实施计划的实现使用了 try/except 回退。F 应更准确反映最终方案。

### L4. 融合分析中 `source_type` 已是旧方案

G 融合分析 §4.5 建议 "ALTER TABLE documents ADD source_type TEXT DEFAULT 'text'"——这是在 D Design Doc 采用"复用 content_type" 之前写的。G 作为分析文档不需要修改，但需注意其建议已被 D 覆盖。

### L5. 实施计划 Task 1 Step 5 (L98-122) 测试覆盖不足

只测试了 `ParsedDocument` 的默认值和 `Document` 的新字段为 None。缺少：
- `source_type="docx"` 时 sections 非空的场景
- `metadata` 包含 parser 信息时的序列化/反序列化
- `Document.source_file_path` 非空时的完整构造测试

---

## 📊 交叉验证矩阵

| 检查项 | A | B | C | D | E | 结论 |
|--------|---|---|---|---|---|------|
| 目标 (Why) | ✅ | - | - | ✅ | ✅ | 一致 |
| 非目标 | - | ✅ | - | ✅ | ✅ | 一致 |
| source_type 列 | ❌ 3列 | - | ❌ 3列 | ✅ 复用 | ✅ 复用 | **矛盾** |
| mammoth 版本 | ❌ 1.6 | - | ❌ 1.6 | ✅ 1.8 | ✅ 1.8 | **矛盾** |
| DocxParser 主路径 | - | - | - | ⚠️ AST | ❌ 不存在API | **高风险** |
| DocumentPort.update_content | - | - | - | ✅ 需要 | ❌ 未列任务 | **遗漏** |
| 错误码区间 | - | - | ❌ 错误区间 | ✅ | ✅ | **标注错误** |
| DB migration 列数 | 3 | - | 3 | 2 | 2 | **矛盾** |
| reparse 完整性 | - | - | ⚠️ | ✅ | ⚠️ | **待验证** |
| PDF 大页面 | - | - | - | ⚠️ 已知限 | - | **低风险** |

---

## 🔧 修复优先级

| 优先级 | 问题 | 需修复的文档 |
|--------|------|-------------|
| 🔴 P0 | C1: source_type 列策略统一 | A, C, G |
| 🔴 P0 | C2: DocxParser 移除对 DocumentReader 的依赖 | D, E |
| 🔴 P0 | C3: mammoth 版本统一为 1.8.0 | A, C |
| 🟡 P1 | M1: 错误码区间标注修正 | C |
| 🟡 P1 | M2: IndexingService 双路径最终方案确认 | D |
| 🟡 P1 | M3: DocumentPort.create() 签名变更显式列明 | C |
| 🟡 P1 | M4: 新增 DocumentPort.update_content() 方法 | C, E |
| 🟢 P2 | L1-L5: 小问题 | A, C, F |
