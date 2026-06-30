# Task 3.2 报告: LLMRerankProvider 实现

## 状态
✅ 完成

## RED/GREEN 证据

### RED 阶段
- 初始运行 `pytest tests/unit/test_llm_rerank.py -v` 全部 26 个测试 FAIL（ModuleNotFoundError: No module named 'ragnexus.adapters.rerank.llm'）
- 失败原因正确：模块尚未创建

### GREEN 阶段
- `pytest tests/unit/test_llm_rerank.py -v` — 26 passed, 0 failed
- `pytest tests/unit/ -v` — 215 passed, 1 warning（Starlette httpx deprecation，非本项目问题）

### 修复过程中的失败→通过
1. **degradation 返回顺序 bug**：test_degrade_on_llm_exception 期望降级按 vector score 排序返回，实现原先 `return chunks[:top_n]` → 修复为 `return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_n]`（两处降级路径均修复）
2. **partial-hit 测试设计错误**：test_cache_partial_hit_payload_includes_reference_scores 原用 `[0.9]*10` 替代 `[0.1]*10` 但 cosine 同方向 = 1.0，实际是 partial hit 而非 full miss → 修正为用相同 query_vector + 新 c_4 触发真正部分命中，正确断言 `reference_scores` 存在且 `candidates` 仅含 c_4
3. **TTL 测试依赖 wall-clock**：test_cache_tll_expiry 用 `cache_ttl_seconds=0` 但因 `time.time()` 精度问题导致两调时间戳相同（0 > 0 = False）→ 改为 cache_ttl_seconds=300 + 用直接操作 entry.timestamp = time.time() - 600 模拟过期

## 提交哈希
`91c3e7b` — feat(rerank): 实现 LLMRerankProvider

## 变更文件列表
| 文件 | 操作 | 行数 |
|------|------|------|
| `src/ragnexus/adapters/rerank/llm.py` | 新增 | 556 |
| `src/ragnexus/adapters/rerank/__init__.py` | 修改 | +1 导出 |
| `tests/unit/test_llm_rerank.py` | 新增 | ~960 |

## 测试覆盖说明

### 构造器 (2 tests)
- 默认参数存储、自定义参数存储

### rerank 正常流程 (3 tests)
- LLM 调用 → 解析 rankings → 按 rerank_score 排序返回
- score 字段保持向量原始分（重排只改顺序）
- 裁回 top_n

### 缓存逻辑 (4 tests)
- 全命中跳过 LLM
- 部分命中 payload 含 reference_scores 标尺，candidates 仅含未命中 chunk
- 向量不相似走 LLM
- TTL 过期不被命中（直接操作 timestamp）

### 候选截断 (2 tests)
- 超过 max_candidates 截断
- 超过 chunk_max_chars 文本截断

### JSON 解析防御 (4 tests)
- Layer 1: 普通 JSON dict
- Layer 2: Markdown 代码块包裹的 JSON
- Layer 3: 文本中夹杂的 JSON
- Layer 4: 全失败返回空列表

### 降级 (3 tests)
- LLM 抛异常 → 降级返回 vector-score 排序
- JSON 解析全失败 → 降级返回 vector-score 排序
- 空 chunks 不抛异常

### clear_cache (2 tests)
- 清空指定 KB 缓存后重新调用 LLM
- 不存在的 KB 不抛异常

### Payload 构造 (2 tests)
- 全 miss 场景 payload 结构（query/candidates/top_n，title 来自 heading，无 heading 时为空串）
- title=None 回退为空字符串

### 边界情况 (3 tests)
- LLM 漏掉 chunk → 默认 rerank_score=0
- LLM 返回不存在的 chunk_id → 忽略
- rerank_score 超出 [0,1] → clamp

### CacheEntry (1 test)
- 字段正确存储

## 架构要点
- `LLMRerankProvider` 实现了 `RerankPort` 协议（鸭子类型，不显式继承 Protocol）
- 依赖 `LLMProvider` ABC（`chat_json` 接口）
- 自建缓存 `dict[str, list[CacheEntry]]` + `asyncio.Lock`
- 每 KB 上限 100 条目，超限踢最旧，TTL 300 秒
- JSON 解析 4 层防御：dict 直取 → json.loads → markdown 提取 → 正则提取最外层 {...}
- `_parse_rankings_json` 和 `_cosine_similarity` 等内部函数用 `_` 前缀标记为 internal

## 顾虑
1. **mccabe complexity**: `_rerank_impl` 和 `_parse_rankings_json` 的圈复杂度偏高（~23/24），后续可考虑拆分为更小的子函数（如拆出 `_cache_lookup`、`_build_payload`、`_write_cache`）
2. **vector cosine 计算无优化**: 对每个缓存条目逐一计算 cosine，缓存条目多时可能有性能影响（100 条目 × 1024 维尚可，但可考虑加早停或 FAISS）
3. **`time` 非 `time.monotonic`**: 使用 `time.time()` 作 timestamp，系统时钟回拨会提前过期缓存（低风险，TTL=300s 在 clock skew 范围外）
4. **`_parse_rankings_json` 全失败时返回 `[]`**: 这会导致 `_rerank_impl` 中检查 `not rankings_list and not matched_rankings` 触发降级（符合预期，但增加了一次不必要的空列表检查）
