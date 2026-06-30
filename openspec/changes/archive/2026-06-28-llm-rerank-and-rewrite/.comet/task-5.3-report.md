# Task 5.3: LLMRewriteProvider 实现报告

## 状态: ✅ 完成

## 提交
- Commit: `5316fe2` (branch: `feature/20260628/llm-rerank-and-rewrite`)
- 文件: `src/ragnexus/adapters/rewrite/llm.py` (+537), `__init__.py` (更新), `tests/unit/test_llm_rewrite.py` (+476)

## 实现概要

### LLMRewriteProvider (`src/ragnexus/adapters/rewrite/llm.py`)
- **构造参数**: `llm: LLMProvider`, `embedder: EmbedderPort`, `cache_similarity_threshold=0.95`, `cache_max_entries=100`, `cache_ttl_seconds=300`, `temperature=0.0`
- **公开属性**: `llm`, `embedder`, `cache_similarity_threshold`, `cache_max_entries`, `cache_ttl_seconds`, `temperature`
- **内部状态**: `_cache: dict[str, list[CacheEntry]]`, `_lock: asyncio.Lock`
- **实现 RewritePort Protocol** (duck typing，不显式继承)

### 核心流程
```
rewrite(query, kb_ids)
  ├── 遍历 kb_ids 查缓存 → 命中返回
  ├── LLMProvider.chat_json() → 一次调用完成判断+改写
  ├── _parse_rewrite_json() → 5 层防御解析
  ├── Layer 5 内容检查 (空/相同/超长)
  ├── >200 字 → _refine_if_needed() 二次精炼
  ├── 写入缓存 (每个 kb_id)
  └── BIZ_EVENT 日志
```

### JSON 5 层防御 (`_parse_rewrite_json`)
| 层级 | 操作 | 失败处理 |
|-----|------|---------|
| 0 | API 层 `response_format: json_object` | — |
| 1 | 已是 dict → 直接用; str → `json.loads` | → Layer 2 |
| 2 | 正则提取 ` ```json ... ``` ` | → Layer 3 |
| 3 | 正则提取最外层 `{...}` | → 降级 |
| 4 | Schema 校验: needs_rewrite 存在 + bool; needs_rewrite=true 时 rewritten_query 非空 | → 降级 |
| 5 | 内容合理性: 空 → 降级; 相同 → 降级; >200 字 → 二次精炼 | → 降级 |

### 降级策略
- `rewrite()` 外层 try/except → 永不抛异常
- LLM 调用失败 → 降级
- JSON 解析失败 → 降级
- 二次精炼失败 → 降级
- Embedder 失败 → 跳过缓存，继续 LLM 路径
- 降级返回 `RewriteResult(original, original, False, reason)`

### 缓存
- 向量余弦相似度 ≥ 0.95 命中
- `dict[str, list[CacheEntry]]` + `asyncio.Lock`
- 每 KB 上限 100 条，TTL 300 秒
- `clear_cache(kb_id)` 清空指定 KB
- Embedder 失败时静默跳过缓存

### 参考模式
- 缓存、余弦相似度、Lock 模式对标 `LLMRerankProvider`
- 属性命名统一公开风格 (`self.llm` 而非 `self._llm`)
- BIZ_EVENT 日志格式与 Rerank 一致

## 测试
- **19 个测试全部通过** (`tests/unit/test_llm_rewrite.py`)
- 测试场景: 构造器、正常改写、不改写、缓存命中、KB 隔离、5 层防御、降级、clear_cache、reason 仅日志、二次精炼、永抛异常
- 使用 `FakeLLMProvider(LLMProvider)` 和 `FakeEmbedder` 模拟依赖

## 检查清单
- [x] ruff: All checks passed!
- [x] pyright: 0 errors, 0 warnings
- [x] pytest: 19 passed
- [x] RewritePort Protocol 未修改
- [x] LLMProvider 未修改
- [x] Rerank 代码未修改
- [x] 中文 docstring
- [x] reason 字段仅日志使用
- [x] 降级责任在内部
- [x] 独立 commit
