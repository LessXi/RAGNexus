# 批次 2 审查报告

**审查范围**: Tasks 2.1-2.3（Alembic migration + KB adapter settings 方法）
**审查基准**: `docs/superpowers/specs/2026-07-05-query-semantic-optimization-design.md` §KB Settings Schema
**Diff 来源**: `.comet/batch-2-review.diff`
**轮次**: 第 1 轮

---

## Spec Compliance

### ✅ Migration：settings JSONB NOT NULL DEFAULT '{}'，downgrade 可逆

`alembic/versions/0004_kb_settings.py`：

- `postgresql.JSONB` 类型 ✅
- `nullable=False` ✅
- `server_default=sa.text("'{}'::jsonb")` ✅ — 与 spec `knowledge_bases.settings JSONB NOT NULL DEFAULT '{}'` 完全一致
- `downgrade()` 调用 `op.drop_column("knowledge_bases", "settings")`，与 upgrade 对称可逆 ✅
- `revision="0004"`、`down_revision="0003"` 链路正确 ✅

### ✅ get_settings(kb_id: str) -> dict

`src/ragnexus/adapters/knowledge_base/pg.py:79-86`：

- 签名 `async def get_settings(self, kb_id: str) -> dict` 与 spec 一致 ✅
- 查询列明确为 `SELECT settings FROM knowledge_bases WHERE id = $1` ✅
- KB 不存在（`row is None`）时返回 `{}`，与 docstring "不存在时返回 {}" 一致 ✅
- `settings` 列为 NULL 时 `row["settings"] or {}` 兜底返回 `{}` ✅（防御性，虽然 schema 已 NOT NULL）

### ✅ update_settings(kb_id: str, settings: dict) -> None

`src/ragnexus/adapters/knowledge_base/pg.py:88-94`：

- 签名 `async def update_settings(self, kb_id: str, settings: dict) -> None` 与 spec 一致 ✅
- 使用 `json.dumps(settings, ensure_ascii=False)` 序列化后通过 `$1::jsonb` 覆盖写入 ✅
- `ensure_ascii=False` 保留中文 synonyms 原样（spec 示例含中文 "背调"/"薪酬"），避免 `\uXXXX` 转义膨胀 ✅
- 参数化查询（`$1`、`$2`）防 SQL 注入 ✅
- 覆盖语义（`SET settings = ...`）符合 spec "覆盖 settings" 要求 ✅

### ✅ create() INSERT 包含 settings 列，默认 '{}'::jsonb

`src/ragnexus/adapters/knowledge_base/pg.py:30-44`：

- INSERT 语句列为 `(id, name, name_key, tenant_id, settings)`，包含 settings ✅
- VALUES 使用 `$5::jsonb` 显式类型转换，传入 `"{}"` 作为默认空对象 ✅
- RETURNING 子句已扩展为 `id, name, created_at, tenant_id, settings` ✅
- 构造 `KnowledgeBase` 时填充 `settings=row["settings"] or {}` ✅
- 与 spec `DEFAULT '{}'` 语义一致（应用层显式传 '{}' 与 DB server_default 双重保证）✅

---

## Code Quality

### ✅ SQL 注入防护

- 所有新 SQL 均使用 asyncpg 参数化占位符（`$1`、`$2`、`$5::jsonb`），无字符串拼接 ✅
- `update_settings` 的 `json.dumps` 结果通过 `$1::jsonb` 参数化传入，非内插 ✅
- `get_settings`/`create` 的 `kb_id`、`tenant_id` 均走占位符 ✅

### ✅ 类型注解准确

- `get_settings(...) -> dict`、`update_settings(...) -> None` 现代注解 ✅
- KnowledgeBase.settings 字段 `dict = field(default_factory=dict)` 在批次 1 已就位 ✅
- Port 接口 `KnowledgeBasePort.get_settings/update_settings`（`src/ragnexus/domain/ports.py:47-53`）签名匹配 ✅

### ✅ 错误处理合理

- `get_settings` 对 `row is None` 与 `row["settings"] is None` 双路径兜底，无 KeyError 风险 ✅
- `update_settings` 走 asyncpg 原生 `execute`，DB 异常自然冒泡（与文件其余方法如 `exists`/`doc_exists` 一致风格）✅

### ⚠️ 代码风格一致性

- `update_settings` 内部使用 `import json` 内联导入，与文件顶部 module-level import（`import asyncpg`、`from nanoid import ...`）风格不一致 — 见下方发现 2。

---

## 具体发现

### Important — `get()` SELECT 未包含 settings 列，返回的 KnowledgeBase.settings 永远为空字典

**位置**: `src/ragnexus/adapters/knowledge_base/pg.py:71-77`

```python
async def get(self, kb_id: str) -> KnowledgeBase | None:
    """按 ID 获取知识库，不存在返回 None。"""
    row = await self.pool.fetchrow(
        "SELECT id, name, tenant_id, created_at FROM knowledge_bases WHERE id=$1",
        kb_id,
    )
    return KnowledgeBase(**dict(row)) if row else None
```

**问题**：`get()` 的 SELECT 列表为 `id, name, tenant_id, created_at`，未包含 `settings`。由于 `KnowledgeBase` dataclass 的 `settings` 字段使用 `field(default_factory=dict)` 默认值，`dict(row)` 中无 `settings` key 时将回退到默认 `{}`。

**触发条件**：通过 `get()` 读取已存在 KB（其 DB settings 为非空 JSONB）后访问 `kb.settings`。

**影响**：
- 本批次 patch 在 `create()` 路径正确填充 `settings`（`row["settings"] or {}`），但 `get()` 路径未同步，导致两条读取路径行为不一致：`create()` 返回带真实 settings 的 `KnowledgeBase`，而 `get()` 返回的 `KnowledgeBase.settings` 永远为 `{}`。
- 任何下游用例若经 `get()` 取 KB 后依赖 `kb.settings` 做词表扩展/重写提示注入（retrieve_use_case 的 `kb_context` 语义），将始终拿到空配置，使 spec §KB Settings Schema 的 synonyms/rewrite_hint 在该路径下静默失效。
- 即使在本 batch diff 中 `get()` 的代码行未带 `-`/`+` 标记（属上下文未改动行），本 patch 让 `settings` 成为 `KnowledgeBase` 的一等字段、并在 `create()` 端完成填充，却未在 `get()` 端完成对称适配，属于 patch 引入的不一致性（半完成迁移）。

**修复**：

```python
async def get(self, kb_id: str) -> KnowledgeBase | None:
    """按 ID 获取知识库，不存在返回 None。"""
    row = await self.pool.fetchrow(
        "SELECT id, name, tenant_id, created_at, settings FROM knowledge_bases WHERE id=$1",
        kb_id,
    )
    return KnowledgeBase(**dict(row)) if row else None
```

注意：`KnowledgeBase.__init__` 接受 kwargs，`dict(row)` 需包含 `settings` key，否则回退默认 `{}`；显式加入 SELECT 后真实值会被填充。

**优先级**: Important
**是否阻塞**: 行为正确性阻塞——`get()` 路径下 settings 失效，违反 spec §KB Settings Schema 的可读取性预期。建议本批次内修复。

---

### Minor — `update_settings` 内联 `import json`，违反文件 module-level import 风格

**位置**: `src/ragnexus/adapters/knowledge_base/pg.py:90`

```python
async def update_settings(self, kb_id: str, settings: dict) -> None:
    """更新（覆盖）KB 的 settings。"""
    import json
    ...
```

**问题**：文件顶部已有 module-level imports（`import asyncpg`、`from nanoid import generate as nanoid_generate`、`from ragnexus.core.errors import ...`），`update_settings` 内的 `import json` 与既有风格不一致，且每次调用触发 import 查找（虽 Python 缓存，仍属反模式）。

**修复**：将 `import json` 提升至文件顶部 import 区。

```python
import asyncpg
import json
from nanoid import generate as nanoid_generate
```

**优先级**: Minor
**是否阻塞**: 否。功能正确，仅为风格一致性问题。

---

### Minor — `update_settings` 未处理 KB 不存在的静默成功

**位置**: `src/ragnexus/adapters/knowledge_base/pg.py:88-94`

**问题**：当 `kb_id` 不存在时，`UPDATE ... WHERE id = $2` 影响 0 行，asyncpg `execute` 不报错，方法静默返回 `None`。下游调用者无法区分"成功覆盖"与"KB 不存在"。

**影响**：当前 spec 未明确要求 update_settings 对不存在 KB 抛错，且无 caller 在本批次 diff 内消费该返回值，属观察项。

**优先级**: Minor
**是否阻塞**: 否。若后续 use case 需要区分语义，可改为检查 `result() == "UPDATE 0"` 后抛 `AppError(ErrorCode.RESOURCE_NOT_FOUND)`。

---

## 判定: NEEDS_FIX

批次 2 的 spec compliance 四项（migration / get_settings / update_settings / create）全部 ✅ 通过，migration 可逆、签名正确、JSONB 默认值与 spec 完全一致、SQL 注入防护到位。

但存在一项 **Important** 级缺陷：`get()` SELECT 未包含 settings 列，导致经 `get()` 路径返回的 `KnowledgeBase.settings` 永远为空，与本批次在 `create()` 端引入的 settings 填充行为不对称，使 spec §KB Settings Schema 在该读取路径下静默失效。建议在本批次内修复（仅需在 SELECT 列表追加 `settings` 一列）。

两项 Minor（inline import 风格、update_settings 静默成功）不阻塞推进，可作为后续清理项。

**最终判定**: NEEDS_FIX（因 Important 项需修复后再次确认）。
