"""集成测试：混合检索 (Hybrid Retrieval) — ES BM25 + PGVector + RRF 融合。

依赖 docker compose 启动的 ES + PG 服务（localhost:9200, localhost:5432）。
Embedder HTTP 通过 pytest-httpx 模拟，返回确定性嵌入向量。
测试场景:
  1. hybrid/vector/bm25 三种模式对比 — 结果数、排序差异
  2. BM25 heading 字段加权 (heading^3) 验证
  3. RRF 融合去重与排序验证
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from ragnexus.composition import build_app
from ragnexus.config import get_settings

COMPOSE_FILE = Path(__file__).parent.parent.parent / "docker-compose.yml"
PG_DSN = "postgresql://ragnexus:ragnexus@localhost:5432/ragnexus"
ES_URL = "http://localhost:9200"
TEST_DIM = 1024

pytestmark = [pytest.mark.integration]

# ═══════════════════════════════════════════════════════════
# 测试数据：精心设计的 MD 文档（每份含多 heading，产生多 chunk）
# ═══════════════════════════════════════════════════════════

_MD_SINGLE_TOPIC = """\
# 机器学习基础

机器学习是人工智能的一个分支，专注于构建能够从数据中学习的系统。
与传统的基于规则的编程不同，机器学习算法通过分析大量数据来自动发现模式和规律。
现代机器学习涵盖从简单的线性模型到复杂的深度神经网络等多种方法。

## 监督学习

监督学习是最常见的机器学习类型。在监督学习中，算法使用带标签的训练数据来学习从输入到输出的映射关系。
常见算法包括线性回归、逻辑回归、决策树、随机森林和支持向量机。
监督学习的成功应用包括图像分类、语音识别和自然语言处理等任务。

## 无监督学习

无监督学习使用没有标签的数据，算法需要自己发现数据中的隐藏结构。
聚类和降维是无监督学习的两个主要技术。
K-means 聚类、层次聚类和 DBSCAN 是常用的聚类算法。
主成分分析（PCA）和 t-SNE 是常用的降维方法，广泛用于数据可视化和特征提取。

## 强化学习

强化学习通过与环境交互来学习最优策略。智能体在环境中采取行动并接收奖励或惩罚信号。
Q-learning 和策略梯度是强化学习的两大主流方法。
AlphaGo 和自动驾驶是强化学习的代表性应用。
"""

_MD_DIVERSE_TOPICS = """\
# 分布式系统设计

分布式系统是由多个独立计算机组成的系统，这些计算机通过网络相互通信和协调。
分布式系统的核心挑战包括一致性、可用性和分区容错性，这三者构成了著名的 CAP 定理。
设计分布式系统时需要在数据复制、故障检测和负载均衡之间做出权衡。

## 一致性协议

Paxos 和 Raft 是两种广泛使用的分布式一致性协议。
Raft 通过领导者选举、日志复制和安全性保证来实现一致性，相比 Paxos 更易于理解和实现。
在 Raft 中，集群中的每个节点都处于领导者、跟随者或候选者三种状态之一。

## 数据分片

数据分片是将大型数据集分割成更小的、更易管理的部分，分布到多个节点上。
常见策略包括范围分片、哈希分片和一致性哈希。
一致性哈希特别适用于节点频繁变动的分布式缓存系统，如 Redis 集群和 Memcached。

## 故障恢复

分布式系统必须能够处理节点故障。常见策略包括主备切换、多活架构和纠删码。
心跳检测是故障发现的基础机制。当检测到节点故障后，系统需要进行领导者选举和数据重平衡。
"""

_MD_HEADING_RICH = """\
# PostgreSQL 性能优化指南

PostgreSQL 是一个功能强大的开源关系型数据库，支持复杂的查询和事务处理。
它采用了多版本并发控制（MVCC）来保证数据一致性，同时支持丰富的数据类型和扩展机制。
在生产环境中，合理的性能优化可以显著提升数据库的吞吐量和响应时间。

## 索引优化

B-tree 索引是 PostgreSQL 的默认索引类型，适用于等值查询和范围查询。
对于全文搜索场景，GIN 索引可以提供显著的性能提升，支持复杂文本搜索需求。
对于空间数据，GiST 索引是最佳选择，能够加速地理空间查询。
BRIN 索引适用于大规模顺序数据的快速过滤，特别适合时间序列数据。
正确的索引策略可以将查询性能提升数十倍乃至数百倍。

### 部分索引

部分索引只索引满足特定条件的行，可以减少索引大小和维护开销。
例如，可以在订单表上只为未完成的订单创建索引，而不是为所有订单创建。
使用部分索引时需要注意，查询语句中的条件必须与索引的 WHERE 子句兼容。
部分索引特别适用于包含大量历史数据且查询通常只关注近期数据的场景。

## 查询优化

EXPLAIN ANALYZE 是诊断慢查询的最重要工具，它提供查询执行计划的详细分析。
该命令不仅显示优化器估算的代价，还显示实际执行时间和返回的行数。
通过对比估算代价和实际执行时间，可以发现统计信息是否过时。
PostgreSQL 的查询优化器基于代价模型，会枚举多种执行计划并选择代价最低的方案。
定期运行 ANALYZE 命令更新表统计信息是保持查询性能稳定的关键。

### 连接策略

PostgreSQL 支持三种连接策略：嵌套循环连接、哈希连接和归并连接。
嵌套循环连接适用于小表连接或存在高效索引的情况。
哈希连接适用于两个大表之间没有合适索引的等值连接场景。
归并连接要求两个表已按连接键排序，适用于排序输出或大范围扫描。
优化器会根据表大小、索引可用性和查询条件自动选择最佳策略。

## 连接池管理

PgBouncer 是 PostgreSQL 最流行的连接池中间件，广泛应用于生产环境。
它支持三种池化模式：会话模式、事务模式和语句模式。
事务模式通常是最佳选择，因为它允许在事务之间共享数据库连接。
在生产环境中，合理配置 PgBouncer 可以显著减少连接开销并提高系统吞吐量。
"""


# ═══════════════════════════════════════════════════════════
# Docker Compose 生命周期管理（ES + PG）
# ═══════════════════════════════════════════════════════════

_compose_started = False


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _start_hybrid_compose() -> None:
    global _compose_started
    if _compose_started:
        return
    print("[hybrid conftest] Starting docker compose (ES + PG)...", file=sys.stderr)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
            "elasticsearch",
            "db",
            "init-db",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    _wait_for_es()
    _wait_for_pg()
    _apply_schema_if_needed()
    _compose_started = True
    print("[hybrid conftest] ES + PG ready.", file=sys.stderr)


def _stop_hybrid_compose() -> None:
    global _compose_started
    if not _compose_started:
        return
    print("[hybrid conftest] Stopping docker compose...", file=sys.stderr)
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        capture_output=True,
        text=True,
        check=False,
    )
    _compose_started = False


def _wait_for_es(timeout: int = 60) -> None:
    import urllib.error
    import urllib.request

    url = f"{ES_URL}/_cluster/health"
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                body = resp.read().decode()
                data = json.loads(body)
                status = data.get("status", "")
                if status in ("green", "yellow"):
                    return
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError(f"Elasticsearch 未就绪（{timeout}s 超时）")


def _wait_for_pg(timeout: int = 30) -> None:
    async def _check():
        import asyncpg

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                conn = await asyncpg.connect(PG_DSN, timeout=2)
                await conn.close()
                return
            except Exception:
                await asyncio.sleep(0.5)
        raise RuntimeError(f"PostgreSQL 未就绪（{timeout}s 超时）")

    asyncio.run(_check())


def _apply_schema_if_needed() -> None:
    """检查并应用 schema.sql（如果 chunks 表不存在）。"""
    import asyncpg

    async def _apply():
        conn = await asyncpg.connect(PG_DSN, timeout=5)
        try:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'chunks')"
            )
            if not exists:
                schema_path = COMPOSE_FILE.parent / "docs" / "sql" / "schema.sql"
                if schema_path.exists():
                    sql = schema_path.read_text()
                    await conn.execute(sql)
                    print("[hybrid conftest] Schema applied.", file=sys.stderr)
        finally:
            await conn.close()

    asyncio.run(_apply())


@pytest.fixture(scope="session")
def ensure_hybrid_services():
    """启动 docker compose (ES + PG + init-db)，应用 schema。session 级，仅执行一次。

    不可用时跳过所有集成测试。"""
    if not _docker_available():
        pytest.skip("Docker 不可用，跳过混合检索集成测试")
    _start_hybrid_compose()
    yield
    # teardown 由用户手动管理（docker compose down）


# ═══════════════════════════════════════════════════════════
# Embedder Mock（常量向量，对齐 e2e conftest 模式）
# ═══════════════════════════════════════════════════════════


def _mock_embedder(httpx_mock: HTTPXMock, dim: int = TEST_DIM) -> None:
    """注册 httpx mock，所有 embedding 返回 [0.1]*dim 常量向量。

    所有 chunk 获得相同向量 → 向量搜索按 PG 内部顺序返回，
    BM25 按关键词频率排序，两者自然不同。"""

    async def _embed_callback(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        inputs = body.get("input", [])
        embeddings = [
            {"embedding": [0.1] * dim, "index": i} for i in range(len(inputs))
        ]
        return httpx.Response(
            status_code=200,
            json={"object": "list", "data": embeddings, "model": "test-model"},
        )

    httpx_mock.add_callback(
        _embed_callback,
        method="POST",
        url=re.compile(r".*/embeddings$"),
        is_reusable=True,
    )


# ═══════════════════════════════════════════════════════════
# App & API Client Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def app(httpx_mock: HTTPXMock, ensure_hybrid_services, monkeypatch):
    """构建 FastAPI app，Mock embedder，配置 ES + PG 指向 docker compose 服务。

    每测试独立 app，隔离 retrieve_uc 内部状态（如 retrieval_mode）。"""
    _mock_embedder(httpx_mock)

    monkeypatch.setenv("PG_DSN", PG_DSN)
    monkeypatch.setenv("PG_POOL_MIN", "1")
    monkeypatch.setenv("PG_POOL_MAX", "3")
    monkeypatch.setenv("PG_COMMAND_TIMEOUT", "15")
    monkeypatch.setenv("ES_ENABLED", "true")
    monkeypatch.setenv("ELASTICSEARCH_URL", ES_URL)
    monkeypatch.setenv("ELASTICSEARCH_INDEX", "ragnexus_test_chunks")
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setenv("REWRITE_ENABLED", "false")
    monkeypatch.setenv("CANDIDATE_K", "20")
    monkeypatch.setenv("RRF_K", "60")
    monkeypatch.setenv("EMBED_BASE_URL", "http://mock-embedder/v1")
    monkeypatch.setenv("EMBED_API_KEY", "test-key")
    monkeypatch.setenv("EMBED_DIM", str(TEST_DIM))
    monkeypatch.setenv("LLM_BASE_URL", "http://mock-llm/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")  # 减少测试输出噪音
    get_settings.cache_clear()

    app = build_app()
    return app


@pytest.fixture
def api_client(app):
    """返回 TestClient 包装的 FastAPI app。"""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def test_kb(api_client):
    """创建测试用知识库，返回 kb_id。

    ES 索引使用 kb_id 过滤 — 不同 KB 的测试天然隔离。"""
    resp = api_client.post(
        "/v1/knowledge-bases:create",
        json={"name": f"hybrid-test-{os.urandom(4).hex()}"},
    )
    assert resp.status_code == 200, f"创建 KB 失败: {resp.text}"
    kb_id = resp.json()["data"]["kb_id"]
    return kb_id


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════


def _upload_doc(client, kb_id: str, filename: str, content: str) -> dict:
    """上传 Markdown 文档，返回响应的 data 字段。"""
    resp = client.post(
        "/v1/documents:upload",
        data={"kb_id": kb_id},
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )
    assert resp.status_code == 201, f"上传文档失败 ({resp.status_code}): {resp.text}"
    return resp.json()["data"]


def _retrieve(client, query: str, kb_ids: list[str], top_k: int = 5) -> dict:
    """检索并返回响应的 data 字段（含 total 和 hits）。"""
    resp = client.post(
        "/v1/rag:retrieve",
        json={"query": query, "kb_ids": kb_ids, "top_k": top_k},
    )
    assert resp.status_code == 200, f"检索失败 ({resp.status_code}): {resp.text}"
    return resp.json()["data"]


def _set_retrieval_mode(app, mode: str) -> None:
    """直接修改 retrieve use case 的检索模式（无需重建 app）。"""
    app.state.retrieve_uc._retrieval_mode = mode


# ═══════════════════════════════════════════════════════════
# 场景 1: 混合检索模式对比
# ═══════════════════════════════════════════════════════════


class TestHybridModeComparison:
    """验证 hybrid/vector/bm25 三种模式的检索行为差异。"""

    def test_hybrid_mode_returns_results(self, app, api_client, test_kb):
        """hybrid 模式（默认）应返回非空检索结果。"""
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        data = _retrieve(api_client, "机器学习 监督学习", [test_kb], top_k=5)
        assert (
            data["total"] >= 1
        ), f"hybrid 模式应返回至少 1 个结果，实际 total={data['total']}"

    def test_vector_mode_returns_results(self, app, api_client, test_kb):
        """纯 vector 模式应返回非空检索结果。"""
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        _set_retrieval_mode(app, "vector")
        data = _retrieve(api_client, "机器学习 监督学习", [test_kb], top_k=5)
        assert (
            data["total"] >= 1
        ), f"vector 模式应返回至少 1 个结果，实际 total={data['total']}"

    def test_bm25_mode_returns_results(self, app, api_client, test_kb):
        """纯 bm25 模式应返回非空检索结果。"""
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        _set_retrieval_mode(app, "bm25")
        data = _retrieve(api_client, "机器学习 监督学习", [test_kb], top_k=5)
        assert (
            data["total"] >= 1
        ), f"bm25 模式应返回至少 1 个结果，实际 total={data['total']}"

    def test_hybrid_not_less_than_max_of_vector_and_bm25(
        self, app, api_client, test_kb
    ):
        """hybrid 结果数 ≥ max(vector, bm25) — RRF 融合不丢失结果。

        使用多 heading 文档确保足够的 chunk 数能体现差异。
        """
        _upload_doc(api_client, test_kb, "dist.md", _MD_DIVERSE_TOPICS)

        _set_retrieval_mode(app, "vector")
        vec_data = _retrieve(api_client, "分布式 一致性 分片", [test_kb], top_k=10)
        vec_total = vec_data["total"]

        _set_retrieval_mode(app, "bm25")
        bm25_data = _retrieve(api_client, "分布式 一致性 分片", [test_kb], top_k=10)
        bm25_total = bm25_data["total"]

        _set_retrieval_mode(app, "hybrid")
        hybrid_data = _retrieve(api_client, "分布式 一致性 分片", [test_kb], top_k=10)
        hybrid_total = hybrid_data["total"]

        max_single = max(vec_total, bm25_total)
        assert (
            hybrid_total >= max_single
        ), f"hybrid({hybrid_total}) 应 ≥ max(vector={vec_total}, bm25={bm25_total})={max_single}"

    def test_three_modes_produce_different_rankings(self, app, api_client, test_kb):
        """三种模式的 chunk_id 排序不完全相同 — BM25 和向量检索各有侧重。

        上传多份文档后，向量搜索按 PG 顺序返回（模拟同等相似度），
        BM25 按关键词频率排序，RRF 融合产生第三种排序。
        """
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        _upload_doc(api_client, test_kb, "dist.md", _MD_DIVERSE_TOPICS)
        _upload_doc(api_client, test_kb, "pg.md", _MD_HEADING_RICH)

        _set_retrieval_mode(app, "vector")
        vec_data = _retrieve(api_client, "系统 优化 学习", [test_kb], top_k=10)
        vec_ids = [h["chunk_id"] for h in vec_data["hits"]]

        _set_retrieval_mode(app, "bm25")
        bm25_data = _retrieve(api_client, "系统 优化 学习", [test_kb], top_k=10)
        bm25_ids = [h["chunk_id"] for h in bm25_data["hits"]]

        _set_retrieval_mode(app, "hybrid")
        hybrid_data = _retrieve(api_client, "系统 优化 学习", [test_kb], top_k=10)
        hybrid_ids = [h["chunk_id"] for h in hybrid_data["hits"]]

        # 三种排序不应完全相同（BM25 关键词加权改变排序）
        all_same = vec_ids == bm25_ids == hybrid_ids
        assert not all_same, (
            f"三种模式排序不应完全相同 → "
            f"vector({len(vec_ids)}), bm25({len(bm25_ids)}), hybrid({len(hybrid_ids)})"
        )


# ═══════════════════════════════════════════════════════════
# 场景 2: BM25 字段加权验证
# ═══════════════════════════════════════════════════════════


class TestBM25FieldBoosting:
    """验证 heading^3 字段加权使 heading 匹配的 chunk 排在前面。

    _MD_HEADING_RICH 文档结构:
      # PostgreSQL 性能优化指南     → heading 含 "PostgreSQL 性能优化"
      ## 索引优化                    → heading 含 "索引优化"
      ### 部分索引
      ## 查询优化                    → heading 含 "查询优化"
      ### 连接策略
      ## 连接池管理                  → heading 含 "连接池管理"
    """

    def test_heading_keyword_ranks_higher_in_bm25(self, app, api_client, test_kb):
        """BM25 模式下，仅在 heading 中出现的关键词匹配应排在前面。

        搜索 "连接池管理" — 该词仅作为 heading 出现在最后一个 section，
        heading 加权 3x 使其 BM25 分数显著高于仅在正文中提到 "连接" 的 chunk。
        """
        _upload_doc(api_client, test_kb, "pg-perf.md", _MD_HEADING_RICH)
        _set_retrieval_mode(app, "bm25")

        data = _retrieve(api_client, "连接池管理", [test_kb], top_k=5)
        hits = data["hits"]

        assert len(hits) >= 1, f"应至少返回 1 个结果，实际 {len(hits)}"

        # 第一个结果应包含 "连接池管理"（heading 匹配加权最高）
        first_text = hits[0]["text"]
        first_heading = hits[0].get("metadata", {}).get("heading")
        assert "连接池管理" in first_text or first_heading == "连接池管理", (
            f"排名第一的结果应包含 heading 匹配的内容，"
            f"实际 heading={first_heading}, text 前 80 字符={first_text[:80]}"
        )

        # 第一名的分数应显著 > 0（heading 加权贡献）
        assert hits[0]["score"] > 0, f"第一个结果分数 {hits[0]['score']} 应 > 0"

    def test_body_only_keyword_still_retrievable(self, app, api_client, test_kb):
        """仅在正文中出现的关键词仍可被 BM25 检索到。

        搜索 "统计信息" — 仅出现在查询优化 section 的正文中（不在任何 heading 中）。
        """
        _upload_doc(api_client, test_kb, "pg-perf.md", _MD_HEADING_RICH)
        _set_retrieval_mode(app, "bm25")

        data = _retrieve(api_client, "统计信息", [test_kb], top_k=5)
        hits = data["hits"]

        assert (
            len(hits) >= 1
        ), f"应至少返回 1 个包含 '统计信息' 的结果，实际 {len(hits)}"

        # 至少有一个结果包含该词
        matched = any("统计信息" in h["text"] for h in hits)
        assert matched, "应存在包含 '统计信息' 的检索结果"

    def test_heading_vs_body_same_keyword_score_ordering(
        self, app, api_client, test_kb
    ):
        """同一关键词同时出现在 heading 和正文中时，heading 所在 chunk 应排名更高。

        搜索 "查询优化" — 它作为 ## heading 出现在某个 chunk 的 heading 字段，
        也出现在正文中。heading 字段加权 3x 应使其所在 chunk 排在前面。
        """
        _upload_doc(api_client, test_kb, "pg-perf.md", _MD_HEADING_RICH)
        _set_retrieval_mode(app, "bm25")

        data = _retrieve(api_client, "查询优化", [test_kb], top_k=5)
        hits = data["hits"]

        assert len(hits) >= 2, f"至少应有 2 个结果，实际 {len(hits)}"

        # 检查 heading 是否为 "查询优化" 的 chunk 在结果中的位置
        heading_indices: list[int] = []
        for i, h in enumerate(hits):
            if h.get("metadata", {}).get("heading") == "查询优化":
                heading_indices.append(i)

        assert heading_indices, "应存在 heading 为 '查询优化' 的结果"

        # heading 匹配的 chunk 应排在前 2 名（加权生效）
        assert heading_indices[0] <= 1, (
            f"heading 为 '查询优化' 的 chunk 应在前 2 名，"
            f"实际排名: {heading_indices}"
        )


# ═══════════════════════════════════════════════════════════
# 场景 3: RRF 融合验证
# ═══════════════════════════════════════════════════════════


class TestRRFFusionIntegration:
    """验证 RRF 融合后结果的去重和排序正确性。"""

    def test_no_duplicate_chunk_ids_in_hybrid(self, app, api_client, test_kb):
        """hybrid 模式结果中不应有重复的 chunk_id — RRF 按 chunk_id 去重。"""
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        _set_retrieval_mode(app, "hybrid")

        data = _retrieve(api_client, "监督学习 无监督学习", [test_kb], top_k=10)
        chunk_ids = [h["chunk_id"] for h in data["hits"]]
        assert len(chunk_ids) == len(
            set(chunk_ids)
        ), f"hybrid 结果中不应有重复 chunk_id: {chunk_ids}"

    def test_rrf_scores_are_positive(self, app, api_client, test_kb):
        """RRF 融合后的分数应为正数。"""
        _upload_doc(api_client, test_kb, "dist.md", _MD_DIVERSE_TOPICS)
        _set_retrieval_mode(app, "hybrid")

        data = _retrieve(api_client, "分布式系统", [test_kb], top_k=5)
        for hit in data["hits"]:
            assert (
                hit["score"] > 0
            ), f"RRF 分数应为正: chunk_id={hit['chunk_id']} score={hit['score']}"

    def test_hybrid_includes_both_source_chunks(self, app, api_client, test_kb):
        """hybrid 结果应尽可能包含两路召回的独有 chunk。

        向量召回和 BM25 召回可能返回不同的 chunk 子集。
        RRF 融合后，两路的独有 chunk 都有机会出现在最终结果中。
        """
        _upload_doc(api_client, test_kb, "pg-perf.md", _MD_HEADING_RICH)

        _set_retrieval_mode(app, "vector")
        vec_data = _retrieve(api_client, "索引连接", [test_kb], top_k=10)
        vec_ids = {h["chunk_id"] for h in vec_data["hits"]}

        _set_retrieval_mode(app, "bm25")
        bm25_data = _retrieve(api_client, "索引连接", [test_kb], top_k=10)
        bm25_ids = {h["chunk_id"] for h in bm25_data["hits"]}

        _set_retrieval_mode(app, "hybrid")
        hybrid_data = _retrieve(api_client, "索引连接", [test_kb], top_k=10)
        hybrid_ids = {h["chunk_id"] for h in hybrid_data["hits"]}

        # hybrid 至少包含两路的交集
        intersection = vec_ids & bm25_ids
        if intersection:
            assert intersection.issubset(
                hybrid_ids
            ), f"hybrid 结果应包含两路交集，缺失: {intersection - hybrid_ids}"

        # 如果两路有差异，hybrid 应包含部分独有 chunk
        union = vec_ids | bm25_ids
        common = hybrid_ids & union
        assert common, "hybrid 结果应与至少一路有交集"

    def test_multiple_docs_hybrid_retrieval(self, app, api_client, test_kb):
        """上传多份不同主题的文档，hybrid 检索返回跨文档的相关结果。"""
        _upload_doc(api_client, test_kb, "ml.md", _MD_SINGLE_TOPIC)
        _upload_doc(api_client, test_kb, "dist.md", _MD_DIVERSE_TOPICS)
        _upload_doc(api_client, test_kb, "pg.md", _MD_HEADING_RICH)

        _set_retrieval_mode(app, "hybrid")

        # 检索 ML/db 交集关键词
        data = _retrieve(api_client, "系统 学习 优化", [test_kb], top_k=10)
        assert data["total"] >= 1, "跨文档检索应有结果"

        # 去重验证：不同文档的 chunk_id 前缀不同（doc_XXX:N）
        chunk_ids = [h["chunk_id"] for h in data["hits"]]
        assert len(chunk_ids) == len(
            set(chunk_ids)
        ), f"跨文档检索不应有重复 chunk_id: {chunk_ids}"

        # 结果应按 RRF 分数降序排列
        scores = [h["score"] for h in data["hits"]]
        for i in range(len(scores) - 1):
            assert (
                scores[i] >= scores[i + 1]
            ), f"结果 # {i} 的分数 {scores[i]} 应 ≥ 结果 # {i + 1} 的分数 {scores[i + 1]}"

    def test_rrf_with_non_overlapping_sources(self, app, api_client, test_kb):
        """两路召回完全不重叠时，RRF 融合仍正常工作。

        使用极窄的关键词搜索，BM25 和向量可能返回完全不同的 chunk 集合。
        """
        _upload_doc(api_client, test_kb, "pg-perf.md", _MD_HEADING_RICH)

        # "PgBouncer" 是只在 ## 连接池管理 中出现的专有名词
        _set_retrieval_mode(app, "vector")
        vec_data = _retrieve(api_client, "PgBouncer 池化", [test_kb], top_k=10)

        _set_retrieval_mode(app, "bm25")
        bm25_data = _retrieve(api_client, "PgBouncer 池化", [test_kb], top_k=10)

        _set_retrieval_mode(app, "hybrid")
        hybrid_data = _retrieve(api_client, "PgBouncer 池化", [test_kb], top_k=10)

        # hybrid 至少应返回结果（无论两路是否重叠）
        assert hybrid_data["total"] >= 1, "hybrid 至少应有 1 个结果"

        # hybrid 结果数 ≥ max(vector, bm25) — 即使两路不重叠，RRF 也不丢失
        max_single = max(vec_data["total"], bm25_data["total"])
        assert hybrid_data["total"] >= max_single, (
            f"hybrid({hybrid_data['total']}) 应 ≥ "
            f"max(vector={vec_data['total']}, bm25={bm25_data['total']})"
            f"={max_single}"
        )
