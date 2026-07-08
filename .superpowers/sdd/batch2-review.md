# Batch 2 审查报告: Tasks 1.4+1.5+1.7+1.8

**审查范围**: diff `76ad1a4..296cd1c`，对应 4 个任务的实现。

---

## 一、Spec Compliance

### Task 1.4 — SearchHit kb_name ✅

| 要求 | 状态 | 说明 |
|------|------|------|
| `SearchHit` 新增 `kb_name: str = ""` 字段 | ✅ | `models.py:61`，默认 `""` 保证向后兼容 |
| 字段顺序：`chunk_id, kb_id, doc_id, score, text, metadata, kb_name` | ✅ | 追加在末尾 |
| 旧代码 `SearchHit(...)` 无需修改 | ✅ | 默认值自动兜底 |
| schema 不变性测试更新 | ✅ | `test_http_schema_invariance.py` 已更新 |

**新增测试**: `test_kb_name_defaults_to_empty_string`、`test_kb_name_explicit_none_not_allowed`、`test_kb_name_explicit_value`（`test_fusion.py`）

### Task 1.5 — kb_name 预加载 ✅

| 要求 | 状态 | 说明 |
|------|------|------|
| 批量 SQL 预加载 `kb_id → name` | ✅ | `retrieve_use_case.py:253-256`，`WHERE id = ANY($1)` 单次查询 |
| 在跨库 RRF 融合后、rerank 前填充 | ✅ | L252: `# 3d.5 批量预加载 kb_name`，位于 `cross_kb_rrf_fuse` 之后 |
| 回退：DB 无记录 → `kb_id[:8]` | ✅ | L258: `kb_names_map.get(hit.kb_id, hit.kb_id[:8])` |
| 空 `kb_ids` → 不崩溃 | ✅ | `pool.fetch` 收到空数组返回空列表 |

**新增测试**: `test_kb_name_populated`（正常填充）、`test_kb_name_fallback`（回退路径）

### Task 1.7 — 多库词表合并 🔴

| 要求 | 状态 | 说明 |
|------|------|------|
| 遍历所有 KB 加载 settings | ✅ | L125-127 |
| JSONB → `json.loads()` | ✅ | L131-134 |
| JSON 解析失败 → 记录 warning + 跳过 | ✅ | L136-141 |
| 合并所有 KB 的 synonyms | ✅ | L142: `all_synonyms.extend(...)` |
| 传给 QueryPipeline | ✅ | L182 |

> **🔴 Critical: 去重过滤使用错误的键名（见三、Issue C-1）**

### Task 1.8 — 多库改写上下文 🟡

| 要求 | 状态 | 说明 |
|------|------|------|
| 遍历所有 KB 构建 context 列表 | ✅ | L112-121 |
| KB 加载失败 → 跳过 | ✅ | L115: `if kb:` |
| 空列表 → 安全传递 | ✅ | LLM 端 `if kb_contexts:` 短路 |
| `RewritePort.rewrite()` 签名更新 | ✅ | `ports.py`, `llm.py`, `noop.py`, `pipeline.py` 全部同步 |
| `rewrite_hint` 继续传递 | ❌ | **已静默删除**（见三、Issue I-1） |

---

## 二、Strengths

1. **测试覆盖充分**: 每项改动都有对应测试（共 4 个新测试 + 4 个已有测试适配），覆盖正常路径和边界条件。
2. **向后兼容设计**: `kb_name` 默认 `""`，旧构造代码零修改。
3. **优雅降级**: per-KB 异常不阻塞，JSON 解析失败不抛异常，`rewrite_hint` 缺失不崩溃。
4. **注释风格一致**: 所有新增代码使用中文注释，与项目其他部分风格统一。
5. **`pool.fetch` 批量查询**: kb_name 预加载用 `WHERE id = ANY($1)` 单次查询，避免 N+1。

---

## 三、Issues

### 🔴 Critical

#### C-1: Synonym 键名格式不匹配 — 词表扩展完全失效

**文件**: `src/ragnexus/application/retrieve_use_case.py:145-147`

```python
# 当前代码（错误）
valid = [s for s in all_synonyms if "term" in s]       # ← 应为 "terms"
if valid:
    synonyms = list({s["term"]: s for s in valid}.values())  # ← 应为 s["terms"]
```

**证据**:

- `composition.py:210` 生成 `{"terms": ["术语1","术语2"], "expand": ["扩展词1","扩展词2"]}`
- `synonym_expander.py:43-44` 读取 `group.get("terms", [])` 和 `group.get("expand", [])`
- 两个生产组件一致使用 **复数**键名 `"terms"` / `"expand"`
- 新代码的 `"term" in s` 过滤对所有生产数据返回 `False`，`valid` 恒为空，`synonyms` 恒为 `None`

**影响**: 多库场景下，所有 KB 的 synonyms 经合并后被静默丢弃，**词表扩展功能完全失效**。Pipeline 收到的 `synonyms=None`，expander 不做任何扩展。

**根因**: Task 1.7 brief 中的伪代码使用了错误的键名 `"term"`（单数），实现者未对照 `synonym_expander.py` 和 `composition.py` 的实际格式交叉验证。测试使用相同的错误格式，形成"测试-实现"互相欺骗的闭环。

**修复方向**: 将 `"term"` 改为 `"terms"`，去重键也需调整为 `frozenset(s["terms"])` 或 `tuple(sorted(s["terms"]))`。同时需要修复 `test_retrieve.py:test_scenario_12_7` 和 `test_retrieve_use_case.py:test_multi_kb_synonyms_merged` 中的测试数据为 `{"terms": [...], "expand": [...]}` 格式。

---

### 🟡 Important

#### I-1: `rewrite_hint` 静默删除 — LLM 改写质量退化

**文件**: `src/ragnexus/application/retrieve_use_case.py:116-121`、`src/ragnexus/adapters/rewrite/llm.py:210-220`

**变更前** (`llm.py`):
```python
if hint := kb_context.get("rewrite_hint"):
    parts.append(f"领域说明: {hint}")
```

**变更后**: `kb_contexts` 的每个元素仅含 `name` 和 `description`，**无 `rewrite_hint`**。LLM 端也不再有 `领域说明` 逻辑。

**影响**: 已配置 `settings.rewrite_hint` 的知识库（如领域特定术语提示）在查询改写时将不再受益于该提示，改写质量可能下降。

**背景**: 多 KB 场景下 `rewrite_hint` 如何传递确实不明确（每个 KB 可能有独立的 hint），但直接删除而非标记为 TODO 或降级为列表是过度简化。

**修复方向**: 将 `rewrite_hint` 纳入 `kb_contexts` 的每个元素：
```python
ctx = {"name": kb.name, "description": ...}
settings = ...
if hint := settings.get("rewrite_hint"):
    ctx["rewrite_hint"] = hint
```
LLM 端格式化为 `- {name}: {desc} [领域: {hint}]`。

---

#### I-2: `_kb_repo.get()` 重复调用 — 2N 次 DB 查询

**文件**: `src/ragnexus/application/retrieve_use_case.py:113-114, 126`

两个独立的 `for kb_id in kb_ids` 循环各自调用 `await self._kb_repo.get(kb_id)`：

- L113-114: `kb_contexts` 构建（N 次）
- L126: `all_synonyms` 收集（N 次）

**影响**: 对于 5 个 KB，需要 10 次 `get()` 调用而非 5 次。每次 `get()` 可能是独立的 DB 查询。

**修复方向**: 合并为单次遍历：
```python
kb_contexts = []
all_synonyms = []
for kb_id in kb_ids:
    kb = await self._kb_repo.get(kb_id)
    if kb:
        kb_contexts.append({"name": kb.name, "description": ...})
        # 同时处理 settings/synonyms...
```

---

#### I-3: `exists()` + `get()` 双重 DB 验证

**文件**: `src/ragnexus/application/retrieve_use_case.py:106-107, 113-114`

步骤 2 已调用 `self._kb_repo.exists(kb_id)` 验证每个 KB 存在（N 次），步骤 3.5 再次调用 `self._kb_repo.get(kb_id)`（N 次）。如果 `get()` 内部做了 DB 查询，这是重复工作。

> **注意**: 这是 Batch 2 之前已有的模式 — 旧代码同样先 `exists` 再 `get`。Batch 2 未引入此问题，但在新增 `kb_contexts` 和 `all_synonyms` 两个独立循环后恶化了影响。

---

### 🟢 Minor

#### M-1: 测试名称与内容不匹配

**文件**: `tests/unit/domain/test_fusion.py:1180-1192`

```python
def test_kb_name_explicit_none_not_allowed(self):
    """kb_name 的类型是 str，传 None 会报错（类型安全）。"""
    hit = SearchHit(...)  # ← 未传 kb_name，完全没测 None
    assert isinstance(hit.kb_name, str)
    assert hit.kb_name == ""
```

测试名暗示验证 `kb_name=None` 时的行为，但实际测试的是默认值 `""`，与 `test_kb_name_defaults_to_empty_string` 重复。

**建议**: 删除此重复测试，或改为真正测试 `kb_name=None` 的行为（当前 dataclass 会因类型不匹配被 pyright/mypy 标记）。

#### M-2: `getattr(kb, "settings", {})` 多余保护

**文件**: `src/ragnexus/application/retrieve_use_case.py:129`

`KnowledgeBase` 是 dataclass，`settings` 字段有 `field(default_factory=dict)`。正常构造的实例 `kb.settings` 不会是 `None` 也不需要 `getattr`。`or {}` 也多余。

**建议**: 直接用 `kb.settings`。

#### M-3: `test_fusion.py` 中包含不相关的格式化改动

**文件**: `tests/unit/domain/test_fusion.py` (L1097-1102, L1124-1141)

`test_cross_kb_fuse_ten_elements` 中的断言格式化调整和 `test_cross_kb_fuse_preserves_text_and_metadata` 中的参数换行与 Batch 2 功能无关。

---

## 四、Assessment

| 维度 | 评级 | 说明 |
|------|------|------|
| **Spec Compliance** | ⚠️ 部分 | T1.4/1.5 完全合规；T1.7 因 synonym 键名错误实质失效；T1.8 丢失 `rewrite_hint` |
| **Code Quality** | 🟡 | 命名清晰、错误处理良好，但存在重复查询和副本间不一致 |
| **Test Coverage** | 🟡 | 测试数量充足，但 T1.7 测试使用的格式不匹配生产数据，形成虚假绿灯 |
| **Backward Compat** | ✅ | `kb_name` 默认值、API 签名更新全部向下兼容 |

### 总体判断

**不可直接合入**。🔴 C-1（synonym 格式不匹配）是需要修复的阻断性问题。修复后会有一个连带发现：去重逻辑需要调整为适合列表键（`frozenset`/`tuple`）的形式。

🟡 I-1（`rewrite_hint` 丢失）和 I-2（重复查询）建议在修复 C-1 时一并处理，因为三者涉及同一代码区域的遍历逻辑。

### 修复优先级

1. **🔴 C-1**: 修复 synonym 键名 + 测试数据格式 → 5-10 分钟
2. **🟡 I-2**: 合并两次 `get()` 循环 → 5 分钟（可与 C-1 同一次改动）
3. **🟡 I-1**: 恢复 `rewrite_hint` 传递 → 10 分钟
4. **🟢 M-2**: `getattr` → 直接属性访问 → 1 分钟
