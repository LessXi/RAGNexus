"""检索鲁棒性集成测试 — 降级策略、异常隔离、多 KB 容错、参数校验.

所有测试使用 mock 对象，无需 Docker 容器。
覆盖 8 个关键鲁棒性场景：
  1. vector 失败 → hybrid 降为 BM25
  2. BM25 失败 → hybrid 降为 vector
  3. embedding 失败 → 异常传播（已知缺口：当前未降级到 BM25）
  4. 双路都失败 → 空结果 + 降级标记
  5. 多库一库失败 → 另一库结果保留，failed_kb_ids 非空
  6. 多库全部失败 → 空结果 + 全量 failed_kb_ids
  7. 空 query → PARAM_ERROR
  8. 超长 query → PARAM_ERROR（尊重 QUERY_MAX_LENGTH）

与现有测试的关系：本文件侧重 execute() 全链路集成，与 test_retrieve_use_case.py
中的 _retrieve_per_kb 单元测试互为补充。
"""

import pytest
from unittest.mock import AsyncMock, patch

from ragnexus.application.retrieve_use_case import RetrieveUseCase
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import PerKbRetrieveResult, SearchHit, RetrieveResult


# ═══════════════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════════════


def _make_hit(
    chunk_id: str,
    kb_id: str = "kb_test",
    doc_id: str = "doc1",
    score: float = 0.9,
    text: str = "",
) -> SearchHit:
    """创建测试用 SearchHit."""
    return SearchHit(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_id=doc_id,
        score=score,
        text=text or f"text_{chunk_id}",
        metadata={},
    )


def _make_per_kb_result(
    hits: list[SearchHit] | None = None,
    vec_count: int = 2,
    kw_count: int = 1,
    degraded: bool = False,
    degraded_reason: str | None = None,
) -> PerKbRetrieveResult:
    """创建测试用 PerKbRetrieveResult."""
    return PerKbRetrieveResult(
        hits=hits or [],
        vec_count=vec_count,
        kw_count=kw_count,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


# ═══════════════════════════════════════════════════════════════════════
# Fixtures — 独立于 Docker，全部 mock
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_store():
    """模拟 VectorStorePort."""
    return AsyncMock()


@pytest.fixture
def mock_keyword_store():
    """模拟 KeywordSearchPort."""
    return AsyncMock()


@pytest.fixture
def mock_kb_repo():
    """模拟 KnowledgeBasePort + pool.

    提供 fetch/fetchval 用于名称加载、权限校验、empty_reason 查询。
    """
    m = AsyncMock()
    m.exists.return_value = True

    class _MockKB:
        name = "测试库"
        description = ""
        settings = {}

    m.get.return_value = _MockKB()

    m.pool = AsyncMock()
    m.pool.fetch.return_value = [{"id": "kb1", "name": "测试库"}]
    m.pool.fetchval.return_value = 1

    return m


@pytest.fixture
def mock_embedder():
    """模拟 EmbedderPort — 默认返回两个 10 维向量."""
    m = AsyncMock()
    m.embed.return_value = [[0.1] * 10, [0.2] * 10]
    return m


@pytest.fixture
def mock_log_port():
    """模拟 RetrieveLogPort — fire-and-forget 日志."""
    return AsyncMock()


@pytest.fixture
def mock_reranker():
    """模拟 RerankPort — 默认不启用 rerank（model_name=None）."""
    m = AsyncMock()
    m.model_name = None
    return m


@pytest.fixture
def mock_pipeline():
    """模拟 QueryPipeline — 默认直通，返回原始 query."""
    from ragnexus.domain.ports import QueryProcessResult

    m = AsyncMock()
    m.process.return_value = QueryProcessResult(
        raw_query="test query",
        effective_query="test query",
        search_query="test query",
        needs_rewrite=False,
        strategy="noop",
        rewrite_latency_ms=0,
        degraded=False,
        degraded_reason=None,
        synonym_applied=False,
        synonym_expansions=[],
    )
    return m


@pytest.fixture
def use_case(
    mock_kb_repo,
    mock_embedder,
    mock_store,
    mock_keyword_store,
    mock_log_port,
    mock_reranker,
    mock_pipeline,
):
    """构造 RetrieveUseCase 实例，注入全部 mock 端口."""
    return RetrieveUseCase(
        kb_repo=mock_kb_repo,
        embedder=mock_embedder,
        store=mock_store,
        log_port=mock_log_port,
        reranker=mock_reranker,
        rewriter=None,
        pipeline=mock_pipeline,
        keyword_store=mock_keyword_store,
    )


# ═══════════════════════════════════════════════════════════════════════
# 辅助：通过 patch _retrieve_per_kb 的 execute() 快捷调用
# ═══════════════════════════════════════════════════════════════════════


class _FakePoolFetch:
    """可调用对象，模拟 pool.fetch 两次调用的不同返回值."""

    def __init__(self, kb_name_rows, empty_reason_chunks):
        self._kb_name_rows = kb_name_rows
        self._empty_reason_chunks = empty_reason_chunks
        self._call_count = 0

    async def __call__(self, *args, **kwargs):
        if self._call_count == 0:
            self._call_count += 1
            return self._kb_name_rows
        self._call_count += 1
        return self._empty_reason_chunks


async def _execute_with_mocked_retrieve(
    use_case,
    per_kb_results: list,
    kb_ids: list[str] | None = None,
    query: str = "测试查询",
    tenant_id: str = "t1",
    top_k: int = 5,
    empty_reason_chunks: list[dict] | None = None,
    **extra_kwargs,
) -> RetrieveResult:
    """辅助：mock _retrieve_per_kb 返回指定结果列表，执行 execute() 全链路.

    参数:
        per_kb_results: 每个 KB 的 PerKbRetrieveResult 或 Exception
        kb_ids: KB ID 列表，默认按 per_kb_results 长度生成
        empty_reason_chunks: pool.fetch 第二次调用返回的 chunk 计数，
            默认 [{"kb_id": k, "cnt": 0} for k in kb_ids]（无 chunk 数据）
    """
    if kb_ids is None:
        kb_ids = [f"kb{i}" for i in range(len(per_kb_results))]

    if empty_reason_chunks is None:
        empty_reason_chunks = [{"kb_id": k, "cnt": 0} for k in kb_ids]

    kb_name_rows = [{"id": kid, "name": f"知识库{kid}"} for kid in kb_ids]

    # 默认 fuse 行为：合并所有有效组的 hits
    all_hits: list = []
    for r in per_kb_results:
        if isinstance(r, PerKbRetrieveResult) and r.hits:
            all_hits.extend(r.hits)

    fake_fetch = _FakePoolFetch(kb_name_rows, empty_reason_chunks)

    with (
        patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock),
        patch.object(
            use_case, "_retrieve_per_kb", new_callable=AsyncMock
        ) as mock_retrieve,
        patch.object(use_case._kb_repo.pool, "fetch", new=fake_fetch),
        patch("ragnexus.application.retrieve_use_case.cross_kb_rrf_fuse") as mock_fuse,
    ):
        mock_retrieve.side_effect = list(per_kb_results)
        mock_fuse.return_value = all_hits
        use_case._kb_repo.pool.fetchval.return_value = len(kb_ids)
        use_case._kb_repo.exists.return_value = True

        return await use_case.execute(
            query=query,
            kb_ids=kb_ids,
            tenant_id=tenant_id,
            top_k=top_k,
            **extra_kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════════════


# ── 场景 1: vector 失败 → hybrid 降为 BM25 ────────────────────────────
@pytest.mark.asyncio
async def test_vector_failure_falls_back_to_bm25(use_case):
    """模拟向量检索异常 → 降级为纯 BM25，degraded_kb_ids 包含该 KB.

    验证 execute() 全链路：PerKbRetrieveResult.degraded 正确聚合到
    RetrieveResult.degraded_kb_ids，partial_kb_success=True.
    """
    hits_bm25 = [_make_hit("c1", "kb1", "d1", 0.8, "bm25结果")]

    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            _make_per_kb_result(
                hits=hits_bm25,
                vec_count=0,
                kw_count=3,
                degraded=True,
                degraded_reason="向量检索异常",
            ),
        ],
        kb_ids=["kb1"],
    )

    assert result.total == 1, "降级后仍应有 BM25 结果"
    assert result.hits[0].chunk_id == "c1"
    assert result.vector_count == 0, "向量路失败，vec_count 应为 0"
    assert result.bm25_count == 3
    assert "kb1" in result.degraded_kb_ids
    assert result.partial_kb_success is True
    assert result.failed_kb_ids == []


# ── 场景 2: BM25 失败 → hybrid 降为 vector（回归）─────────────────────
@pytest.mark.asyncio
async def test_bm25_failure_falls_back_to_vector(use_case):
    """模拟 BM25 检索异常 → 降级为纯向量.

    这是原有降级逻辑的回归验证——BM25 不可用时不应影响向量检索结果.
    """
    hits_vec = [_make_hit("c1", "kb1", "d1", 0.95, "向量结果")]

    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            _make_per_kb_result(
                hits=hits_vec,
                vec_count=5,
                kw_count=0,
                degraded=True,
                degraded_reason="BM25 检索异常",
            ),
        ],
        kb_ids=["kb1"],
    )

    assert result.total == 1, "降级后仍应有向量结果"
    assert result.vector_count == 5
    assert result.bm25_count == 0
    assert "kb1" in result.degraded_kb_ids
    assert result.partial_kb_success is True
    assert result.failed_kb_ids == []


# ── 场景 3: embedding 失败 → 异常传播（已知鲁棒性缺口）────────────────
@pytest.mark.asyncio
async def test_embedding_failure_propagates_exception(
    use_case,
    mock_embedder,
):
    """模拟 embedder.embed 抛异常 → 异常直接传播，不静默丢失.

    当前行为：embedding 失败发生在 per-KB 循环之前，无 catch，
    异常直接传播给调用方。这是已知鲁棒性缺口——理想行为是在 hybrid
    模式下降级为纯 BM25 并返回部分结果.
    """
    mock_embedder.embed.side_effect = RuntimeError("Embedding 服务超时")

    with pytest.raises(RuntimeError, match="Embedding 服务超时"):
        with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
            await use_case.execute(
                query="测试查询",
                kb_ids=["kb1"],
                tenant_id="t1",
                top_k=5,
            )


# ── 场景 4: 双路都失败 → 空结果 + 降级标记 ───────────────────────────
@pytest.mark.asyncio
async def test_both_pathways_failure_returns_empty_with_degraded(use_case):
    """模拟向量和 BM25 双路都异常 → 返回空结果，degraded_kb_ids 标记.

    _retrieve_per_kb 内部 catch 两路异常后返回 degraded=True + 空 hits.
    execute() 层将其归入 degraded_kb_ids（而非 failed_kb_ids），因为
    没有抛异常——返回了合法的 PerKbRetrieveResult.
    """
    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            _make_per_kb_result(
                hits=[],
                vec_count=0,
                kw_count=0,
                degraded=True,
                degraded_reason="向量和BM25检索均异常",
            ),
        ],
        kb_ids=["kb1"],
    )

    assert result.total == 0, "双路都失败时应返回空结果"
    assert result.hits == []
    assert result.vector_count == 0
    assert result.bm25_count == 0
    assert "kb1" in result.degraded_kb_ids
    assert result.failed_kb_ids == []
    assert result.partial_kb_success is False


# ── 场景 5: 多库一库失败 → 另一库结果保留 ─────────────────────────────
@pytest.mark.asyncio
async def test_multi_kb_one_fails_other_survives(use_case):
    """模拟 kb2 的 _retrieve_per_kb 抛 RuntimeError → kb1 结果保留.

    failed_kb_ids 包含 kb2，partial_kb_success=True.
    """
    hits_kb1 = [_make_hit("c1", "kb1", "d1", 0.9, "kb1正常结果")]

    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            _make_per_kb_result(hits=hits_kb1, vec_count=2, kw_count=1, degraded=False),
            RuntimeError("KB 连接超时"),
        ],
        kb_ids=["kb1", "kb2"],
    )

    assert result.total == 1, "kb1 结果应保留"
    assert result.hits[0].kb_id == "kb1"
    assert "kb2" in result.failed_kb_ids
    assert "kb1" not in result.failed_kb_ids
    assert result.partial_kb_success is True


# ── 场景 6: 多库全部失败 → 空结果 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_multi_kb_all_fail_returns_empty(use_case):
    """模拟所有 KB 的 _retrieve_per_kb 都抛异常 → 空结果.

    failed_kb_ids 包含全部 KB ID，partial_kb_success=True.
    """
    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            RuntimeError("kb1 故障"),
            RuntimeError("kb2 故障"),
            RuntimeError("kb3 故障"),
        ],
        kb_ids=["kb1", "kb2", "kb3"],
    )

    assert result.total == 0, "全部 KB 失败时应返回空结果"
    assert result.hits == []
    assert result.vector_count == 0
    assert result.bm25_count == 0
    assert set(result.failed_kb_ids) == {"kb1", "kb2", "kb3"}
    assert result.partial_kb_success is True
    assert result.empty_reason is None


# ── 场景 6b: 多库全部降级（无异常但有 degraded KB 全空）─────────────
@pytest.mark.asyncio
async def test_multi_kb_all_degraded_empty(use_case):
    """模拟所有 KB 返回 degraded + 空 hits → 空结果.

    所有 KB 在 degraded_kb_ids 中，partial_kb_success=False.
    """
    result = await _execute_with_mocked_retrieve(
        use_case,
        per_kb_results=[
            _make_per_kb_result(
                hits=[],
                vec_count=0,
                kw_count=0,
                degraded=True,
                degraded_reason="向量和BM25检索均异常",
            ),
            _make_per_kb_result(
                hits=[],
                vec_count=0,
                kw_count=0,
                degraded=True,
                degraded_reason="向量检索异常",
            ),
        ],
        kb_ids=["kb1", "kb2"],
    )

    assert result.total == 0
    assert result.hits == []
    assert set(result.degraded_kb_ids) == {"kb1", "kb2"}
    assert result.failed_kb_ids == []
    assert result.partial_kb_success is False


# ── 场景 7: 空 query → PARAM_ERROR ────────────────────────────────────
@pytest.mark.asyncio
async def test_empty_query_raises_param_error(use_case):
    """空字符串 query → AppError(PARAM_ERROR)."""
    with pytest.raises(AppError) as exc_info:
        with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
            await use_case.execute(
                query="   ",  # strip 后为空
                kb_ids=["kb1"],
                tenant_id="t1",
                top_k=5,
            )

    assert exc_info.value.code == ErrorCode.PARAM_ERROR.code
    assert "不能为空" in exc_info.value.message


# ── 场景 8: 超长 query → PARAM_ERROR ─────────────────────────────────
@pytest.mark.asyncio
async def test_oversized_query_raises_param_error(use_case):
    """超长 query → AppError(PARAM_ERROR)，默认限制 2000 字符."""
    long_query = "x" * 2001

    with pytest.raises(AppError) as exc_info:
        with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
            await use_case.execute(
                query=long_query,
                kb_ids=["kb1"],
                tenant_id="t1",
                top_k=5,
            )

    assert exc_info.value.code == ErrorCode.PARAM_ERROR.code
    assert "长度" in exc_info.value.message


@pytest.mark.asyncio
async def test_oversized_query_respects_env_max_length(
    use_case,
    monkeypatch,
):
    """QUERY_MAX_LENGTH=50 时，51 字符 query 触发 PARAM_ERROR."""
    monkeypatch.setenv("QUERY_MAX_LENGTH", "50")
    long_query = "x" * 51

    with pytest.raises(AppError) as exc_info:
        with patch.object(use_case, "validate_kb_ownership", new_callable=AsyncMock):
            await use_case.execute(
                query=long_query,
                kb_ids=["kb1"],
                tenant_id="t1",
                top_k=5,
            )

    assert exc_info.value.code == ErrorCode.PARAM_ERROR.code
    assert "50" in exc_info.value.message
