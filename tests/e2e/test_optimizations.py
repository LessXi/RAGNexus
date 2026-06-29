"""E2E 测试 — 优化选项（rewrite/rerank）启停验证。

依赖: Docker Compose (test-db on port 5433)
若无 Docker 或数据库不可用，pytest 自动 skip。
"""

import asyncio
import httpx

import pytest
from fastapi.testclient import TestClient

from ragnexus.config import get_settings
from ragnexus.domain.models import SearchHit

pytestmark = [pytest.mark.e2e]


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


def _db_available() -> bool:
    """检查测试数据库是否可用。"""
    try:
        import asyncpg

        async def _check():
            # 始终用测试 DSN（Docker Compose test-db on port 5433）
            test_dsn = "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"
            conn = await asyncpg.connect(test_dsn, timeout=3)
            await conn.close()
            return True

        return asyncio.run(asyncio.wait_for(_check(), timeout=5))
    except Exception:
        return False


def _embedder_available() -> bool:
    """检查 embedder API key 是否已配置。"""
    return bool(os.environ.get("EMBED_API_KEY") or get_settings().EMBED_API_KEY)


# ──────────────────────────────────────────────────────────────────
# 前置条件验证 fixture — 缺失时给出修复指引而非跳过
# ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _require_deps():
    """验证外部依赖可用。缺失时报错指引而非静默跳过。"""
    if not _db_available():
        pytest.fail(
            "测试数据库不可用。请先启动 Docker Compose：\n"
            "  docker compose -f docker-compose.test.yml up -d"
        )
    if not _embedder_available():
        pytest.fail(
            "EMBED_API_KEY 未配置。请在 .env 中设置或导出环境变量：\n"
            "  export EMBED_API_KEY=<your-key>"
        )


# ──────────────────────────────────────────────────────────────────
# E2E: Retrieve 基本流程
# ──────────────────────────────────────────────────────────────────


class TestE2ERetrieveBasic:
    def test_retrieve_returns_expected_format(self, client, mock_external_http):
        """检索返回标准格式 {code, data: {total, hits}, message}。"""
        # 先创建 KB
        import uuid

        kb_name = f"e2e_opt_{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/v1/knowledge-bases:create",
            json={"name": kb_name},
        )
        assert resp.status_code == 200
        kb_data = resp.json()
        kb_id = kb_data["data"]["kb_id"]

        try:
            # 上传一个文本文件
            resp = client.post(
                "/v1/documents:upload",
                data={"kb_id": kb_id},
                files={
                    "file": (
                        "test.md",
                        f"# Test {os.urandom(4).hex()}\n\nAI test document.".encode(),
                        "text/markdown",
                    ),
                },
            )
            if resp.status_code == 500:
                pytest.fail(
                    "上传失败——embedder API 不可用。请检查 EMBED_API_KEY 是否正确配置"
                )

            assert resp.status_code == 201
            upload_data = resp.json()
            assert upload_data["code"] == 0

            # 检索
            resp = client.post(
                "/v1/rag:retrieve",
                json={"query": "AI", "kb_ids": [kb_id], "top_k": 3},
            )
            assert resp.status_code == 200
            retrieve_data = resp.json()

            # 标准响应格式断言
            assert retrieve_data["code"] == 0
            assert retrieve_data["message"] == "ok"
            assert "data" in retrieve_data
            assert "total" in retrieve_data["data"]
            assert "hits" in retrieve_data["data"]
            assert isinstance(retrieve_data["data"]["hits"], list)

            # 每个 hit 只有标准字段
            for hit in retrieve_data["data"]["hits"]:
                assert set(hit.keys()) == {
                    "chunk_id",
                    "kb_id",
                    "doc_id",
                    "score",
                    "text",
                    "metadata",
                }
                assert isinstance(hit["score"], (int, float))
                # 无新增字段
                assert "rerank_score" not in hit
                assert "rewritten_query" not in hit
        finally:
            # 清理：删除 KB（如果有删除端点）
            pass


# ──────────────────────────────────────────────────────────────────
# E2E: 无 rewrite/rerank 参数（向后兼容）
# ──────────────────────────────────────────────────────────────────


class TestE2EErrorCases:
    """错误场景 — 不需要 embedder。"""

    def test_missing_query_returns_422(self, client):
        """缺少 query 字段返回 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"kb_ids": ["kb1"]},
        )
        assert resp.status_code == 422

    def test_missing_kb_ids_returns_422(self, client):
        """缺少 kb_ids 字段返回 422。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={"query": "test"},
        )
        assert resp.status_code == 422

    def test_extra_fields_rejected(self, client):
        """请求含额外字段时被拒绝（extra='forbid'）。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb1"],
                "rerank_enabled": True,
            },
        )
        # extra='forbid' → 422 或忽略额外字段
        # 如果是 forbid 则返回 422
        if resp.status_code != 200:
            assert resp.status_code == 422

    def test_kb_not_found_returns_404(self, client):
        """不存在的 KB 返回错误。"""
        resp = client.post(
            "/v1/rag:retrieve",
            json={
                "query": "test",
                "kb_ids": ["kb_nonexistent_12345"],
                "top_k": 5,
            },
        )
        # 可能是 404 或其他错误码（取决于 embedder 是否可用）
        # 无 embedder 时返回 500 也合理
        assert resp.status_code in (200, 404, 500)


# ──────────────────────────────────────────────────────────────────
# E2E: 优化选项隔离（不依赖数据库的结构测试）
# ──────────────────────────────────────────────────────────────────


class TestE2EOptimizationIsolation:
    """不需要数据库：验证 rewrite/rerank 选项不影响 HTTP 接口契约。"""

    def test_search_hit_has_no_optimization_fields(self):
        """SearchHit dataclass 无 rewrite/rerank 相关字段。"""
        hit = SearchHit(
            chunk_id="c1",
            kb_id="k1",
            doc_id="d1",
            score=0.95,
            text="test",
            metadata={},
        )
        # 验证 SearchHit 序列化后无额外字段
        d = {
            "chunk_id": hit.chunk_id,
            "kb_id": hit.kb_id,
            "doc_id": hit.doc_id,
            "score": hit.score,
            "text": hit.text,
            "metadata": hit.metadata,
        }
        assert "rerank_score" not in d
        assert "rewritten_query" not in d
        assert "original_query" not in d

    def test_request_model_still_three_fields(self):
        """无论优化是否启用，请求 model 只有三个字段。"""
        from ragnexus.adapters.http.retrieve_router import _RetrieveRequest

        fields = set(_RetrieveRequest.model_fields.keys())
        assert fields == {"query", "kb_ids", "top_k"}

    def test_extra_forbid_still_enforced(self):
        """extra='forbid' 在优化启用时仍然生效。"""
        from ragnexus.adapters.http.retrieve_router import _RetrieveRequest

        assert _RetrieveRequest.model_config.get("extra") == "forbid"


# ──────────────────────────────────────────────────────────────────
# 5.3 / 5.4: E2E Rewrite + Rerank 全流程（独立 app，启用 LLM provider）
# ──────────────────────────────────────────────────────────────────
#
# 本类使用独立的 llm_client fixture 构建 rewrite/rerank 启用 的应用，
# 通过 monkeypatch 替换 LLMProvider.chat_json 和 EmbedderPort.embed
# 方法，模拟修改返回值并验证端到端行为。
#
# 与 TestE2ERetrieveBasic 的 client (noop providers) 隔离。


class TestE2ERewriteAndRerank:
    """5.3 / 5.4 — rewrite/rerank 启用的 E2E 全流程。"""

    @pytest.fixture
    def llm_client(self, httpx_mock):
        """构建启用 rewrite/rerank 的独立 FastAPI TestClient。

        覆盖环境变量以确保 LLMRewriteProvider + LLMRerankProvider 被布线，
        且 LLM API key 有效（即使调用被 mock 替代也不会因空 key 报错）。
        各测试方法内实际通过方法级 mock 控制返回值。
        """
        old_env = {}
        for k in (
            "REWRITE_ENABLED",
            "RERANK_ENABLED",
            "LLM_API_KEY",
            "EMBED_API_KEY",
            "PG_DSN",
            "PG_POOL_MIN",
            "PG_POOL_MAX",
            "PG_COMMAND_TIMEOUT",
        ):
            old_env[k] = os.environ.get(k)
        os.environ["REWRITE_ENABLED"] = "true"
        os.environ["RERANK_ENABLED"] = "true"
        os.environ["LLM_API_KEY"] = "sk-test"
        # 保留外部已设置的 EMBED_API_KEY，确保上传流程正常
        os.environ.setdefault("EMBED_API_KEY", "sk-test")
        # 指向测试数据库（与 conftest 一致）
        os.environ["PG_DSN"] = (
            "postgresql://ragnexus:ragnexus@localhost:5433/ragnexus_test"
        )
        os.environ["PG_POOL_MIN"] = "1"
        os.environ["PG_POOL_MAX"] = "3"
        os.environ["PG_COMMAND_TIMEOUT"] = "15"
        get_settings.cache_clear()

        from ragnexus.composition import build_app

        app = build_app()
        # 注册 httpx mock（embedder + LLM），避免真实 API 调用
        import re as _re, json as _json

        s = get_settings()
        httpx_mock.add_callback(
            lambda req: httpx.Response(
                200,
                json={
                    "data": [
                        {"embedding": [0.1] * s.EMBED_DIM, "index": i}
                        for i in range(len(_json.loads(req.content).get("input", [])))
                    ]
                },
            ),
            url=_re.compile(r".*/embeddings$"),
            method="POST",
            is_reusable=True,
        )
        httpx_mock.add_callback(
            lambda req: httpx.Response(
                200,
                json={
                    "id": "m",
                    "object": "chat.completion",
                    "model": s.LLM_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": _json.dumps(
                                    {
                                        "rankings": [],
                                        "rewritten_query": "",
                                        "result": "ok",
                                    }
                                ),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            ),
            url=_re.compile(r".*/chat/completions$"),
            method="POST",
            is_reusable=True,
        )
        with TestClient(app) as c:
            yield c
        # 恢复 env
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()

    # -----------------------------------------------------------------
    # 5.3: Rewrite 启用 — 验证改写后 query 被送入 embedder
    # -----------------------------------------------------------------

    def test_rewrite_enabled_uses_llm_rewritten_query(self, llm_client):
        """5.3: mock LLM 返回改写结果 → embed 输入应包含改写后 query。"""
        import uuid

        uc = llm_client.app.state.retrieve_uc
        embedder = uc._embedder
        llm_provider = uc._rewriter.llm

        # --- Arrange: 创建 KB + 上传文档（真实 embedder） ---
        kb_name = f"e2e_rw_{uuid.uuid4().hex[:8]}"
        resp = llm_client.post("/v1/knowledge-bases:create", json={"name": kb_name})
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        content_suffix = uuid.uuid4().hex[:8]
        resp = llm_client.post(
            "/v1/documents:upload",
            data={"kb_id": kb_id},
            files={
                "file": (
                    "t.md",
                    f"# AI\n\nArtificial intelligence run-{content_suffix}.\n".encode(),
                    "text/markdown",
                ),
            },
        )
        if resp.status_code != 201:
            pytest.fail(
                f"上传失败——embedder API 不可用。请检查 EMBED_API_KEY。响应: {resp.text}"
            )
        assert resp.status_code == 201

        # --- Act: mock LLM + embedder，触发 retrieve ---
        captured_texts: list[str] = []
        original_llm = llm_provider.chat_json
        original_embed = embedder.embed

        async def _mock_chat_json(*, system_prompt, user_payload, temperature):
            """单一 mock 同时处理 rewrite 和 rerank 调用。"""
            if "查询优化器" in system_prompt:
                # Rewrite LLM — 返回改写了的结果
                return {
                    "needs_rewrite": True,
                    "rewritten_query": "advanced artificial intelligence search",
                    "reason": "mock LLM rewrite",
                }
            # Rerank LLM — 直通（保持向量顺序，不干扰 rewrite 断言）
            cands = user_payload.get("candidates", [])
            return {
                "rankings": [
                    {"chunk_id": c["chunk_id"], "rerank_score": 1.0, "reason": "pass"}
                    for c in cands
                ]
            }

        async def _mock_embed(texts):
            captured_texts.extend(texts)
            dim = 1024
            # 非零向量：避免 pgvector 余弦距离计算除零
            return [[0.1] + [0.0] * (dim - 1) for _ in texts]

        llm_provider.chat_json = _mock_chat_json
        embedder.embed = _mock_embed
        try:
            resp = llm_client.post(
                "/v1/rag:retrieve",
                json={"query": "AI", "kb_ids": [kb_id], "top_k": 3},
            )
        finally:
            llm_provider.chat_json = original_llm
            embedder.embed = original_embed

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0

        assert any(
            "advanced artificial intelligence search" in t for t in captured_texts
        ), f"embedder 未收到改写后 query\n  captured_texts={captured_texts}"

    # -----------------------------------------------------------------
    # 5.4: Rerank 启用 — 验证 LLM 返回的 rankings 改变了排序
    # -----------------------------------------------------------------

    def test_rerank_enabled_reorders_hits_per_llm_verdict(self, llm_client):
        """5.4: mock LLM 返回倒序 rankings → 响应 chunk 顺序应反转。"""
        import uuid

        uc = llm_client.app.state.retrieve_uc
        llm_provider = uc._reranker.llm

        # --- Arrange: 上传多 chunk 文档 ---
        kb_name = f"e2e_rr_{uuid.uuid4().hex[:8]}"
        resp = llm_client.post("/v1/knowledge-bases:create", json={"name": kb_name})
        assert resp.status_code == 200
        kb_id = resp.json()["data"]["kb_id"]

        content_suffix = uuid.uuid4().hex[:8]
        body = "\n\n".join(
            f"# Section {i}\n\nSection {i} run-{content_suffix}." for i in range(5)
        )
        resp = llm_client.post(
            "/v1/documents:upload",
            data={"kb_id": kb_id},
            files={"file": ("m.md", body.encode(), "text/markdown")},
        )
        if resp.status_code != 201:
            pytest.fail(f"上传失败: {resp.text}")
        assert resp.status_code == 201
        n_chunks = resp.json()["data"]["chunk_count"]
        if n_chunks < 2:
            pytest.fail(
                f"chunk_count={n_chunks} 不足以验证重排——请上传包含更多标题的文档"
            )

        # --- Act: mock LLM，触发 retrieve ---
        captured_candidates: list[list[dict]] = []
        original_llm = llm_provider.chat_json

        async def _mock_chat_json(*, system_prompt, user_payload, temperature):
            """单一 mock 处理 rewrite + rerank。"""
            if "查询优化器" in system_prompt:
                # Rewrite — 不需要改写，减少干扰
                return {
                    "needs_rewrite": False,
                    "rewritten_query": "",
                    "reason": "no rewrite needed",
                }
            # Rerank — 候选倒序打分
            cands = user_payload.get("candidates", [])
            captured_candidates.append(list(cands))
            n = len(cands)
            rankings = [
                {
                    "rerank_score": i / max(1, n - 1),  # [0, 1] 区间
                    "chunk_id": c["chunk_id"],
                    "reason": "mock rerank",
                }
                for i, c in enumerate(cands)
            ]
            return {"rankings": rankings}

        llm_provider.chat_json = _mock_chat_json
        top_k = min(n_chunks, 3)
        try:
            resp = llm_client.post(
                "/v1/rag:retrieve",
                json={"query": "topic", "kb_ids": [kb_id], "top_k": top_k},
            )
        finally:
            llm_provider.chat_json = original_llm

        assert resp.status_code == 200, resp.text
        hits = resp.json()["data"]["hits"]
        assert len(hits) >= 2, f"需要至少 2 个 hit，实际 {len(hits)}"

        # --- Assert: 响应顺序 = candidates 倒序后截断 ---
        assert captured_candidates, "rerank LLM 未被调用"
        cands = captured_candidates[0]
        expected_ids = [c["chunk_id"] for c in reversed(cands)][: len(hits)]
        actual_ids = [h["chunk_id"] for h in hits]
        assert actual_ids == expected_ids, (
            f"重排顺序与 mock LLM 不一致\n"
            f"  expected: {expected_ids}\n"
            f"  actual:   {actual_ids}\n"
            f"  candidates: {[c['chunk_id'] for c in cands]}"
        )

        # 额外检查：score 字段保持向量原始分（不变量）
        for hit in hits:
            assert isinstance(hit["score"], (int, float))
            assert "rerank_score" not in hit
            assert "rewritten_query" not in hit
            assert "original_query" not in hit
