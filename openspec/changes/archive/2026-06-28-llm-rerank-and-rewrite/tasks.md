## 1. 基础设施层

- [x] 1.1 config.py 新增 `LLM_*` + `RERANK_*` + `REWRITE_*` 配置字段
- [x] 1.2 .env.example 新增 `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`/`LLM_REQUEST_TIMEOUT`/`LLM_CONNECT_TIMEOUT`/`LLM_MAX_CONCURRENCY`/`LLM_MAX_RETRIES`/`LLM_RETRY_BACKOFF_BASE` + `RERANK_ENABLED`/`RERANK_CANDIDATE_MULTIPLIER`/`RERANK_MIN_CANDIDATES`/`RERANK_MAX_CANDIDATES`/`RERANK_CHUNK_MAX_CHARS`/`RERANK_TEMPERATURE` + `REWRITE_ENABLED`（约 16 行）
- [x] 1.3 创建 `adapters/llm/base.py` — `LLMProvider` ABC（`chat_json` 抽象方法）
- [x] 1.4 创建 `adapters/llm/openai_compatible.py` — `OpenAICompatibleLLMProvider`（httpx 惰性初始化、Semaphore、指数退避重试）
- [x] 1.5 实现 `_call_api` 方法和 `log_model_call` 桥接

## 2. 领域层 — Rerank

- [x] 2.1 `domain/ports.py` 新增 `RerankPort` Protocol（`rerank` + `clear_cache` 方法签名）

## 3. 重排实现

- [x] 3.1 创建 `adapters/rerank/noop.py` — `NoopRerankProvider`（直通）
- [x] 3.2 创建 `adapters/rerank/llm.py` — `LLMRerankProvider`（含：缓存逻辑、LLM 调用、候选截断、JSON 4 层防御、降级、BIZ_EVENT 日志）

## 4. 链路集成 — Rerank

- [x] 4.1 `RetrieveUseCase` 注入 `RerankPort` + `candidate_multiplier` + `min_candidates`
- [x] 4.2 `RetrieveUseCase.execute()` 插入 rerank 步骤（向量召回后、返回前）
- [x] 4.3 `composition.py` 装配 `LLMProvider` + `RerankProvider` 并注入 use case
- [x] 4.4 composition.py 包装 upload_doc 调用成功后清空 rerank 缓存

## 5. 领域层 + 实现 — Rewrite

- [x] 5.1 `domain/ports.py` 新增 `RewritePort` Protocol + `RewriteResult` dataclass
- [x] 5.2 创建 `adapters/rewrite/noop.py` — `NoopRewriteProvider`（直通）
- [x] 5.3 创建 `adapters/rewrite/llm.py` — `LLMRewriteProvider`（含：缓存逻辑、一次 LLM 判断+改写、5 层防御、降级、reason 仅日志、BIZ_EVENT 日志）

## 6. 链路集成 — Rewrite

- [x] 6.1 `RetrieveUseCase` 注入 `RewritePort`
- [x] 6.2 `RetrieveUseCase.execute()` 插入 rewrite 步骤（embed 之前）
- [x] 6.3 `composition.py` 装配 `RewriteProvider` 并注入 use case
- [x] 6.4 composition.py 包装 upload_doc 调用后清空 rewrite 缓存

## 7. 测试

- [x] 7.1 单元测试：LLMProvider（mock httpx 响应、超时、JSON 解析）
- [x] 7.2 单元测试：LLMRerankProvider（正常重排、缓存命中/部分命中、LLM 降级）
- [x] 7.3 单元测试：LLMRewriteProvider（需要改写、不需要改写、LLM 降级）
- [x] 7.4 单元测试：NoopRerankProvider / NoopRewriteProvider 直通行为
- [x] 7.5 集成测试：RetrieveUseCase 全链路（Rewrite + Rerank 组合）
- [x] 7.6 验证测试：HTTP 请求/响应 schema 完全不变（断言请求无新增字段、响应格式与第一期一致）
- [x] 7.7 E2E 测试：POST /v1/rag:retrieve 启用/禁用各优化
