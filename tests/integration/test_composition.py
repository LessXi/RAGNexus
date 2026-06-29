"""composition 生命周期集成测试。

测试 build_app() → lifetime → routes → /health → migration warning → shutdown。
所有测试使用真实 FastAPI TestClient + test-db（pg_pool / _apply_schema 来自 conftest.py）。
"""

import pytest
import asyncio
import pytest_asyncio
from fastapi.testclient import TestClient

from ragnexus.composition import build_app
from ragnexus.config import Settings, get_settings
from tests.integration.conftest import TEST_DSN

pytestmark = [pytest.mark.integration]


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def composition_settings(monkeypatch, _apply_schema):
    """注入 test-db DSN 并清除 Settings 缓存，返回 Settings 实例。

    ``get_settings()`` 被 ``@cache`` 装饰——不清理缓存会污染后续测试。
    """
    monkeypatch.setenv("PG_DSN", TEST_DSN)
    monkeypatch.setenv("PG_POOL_MIN", "1")
    monkeypatch.setenv("PG_POOL_MAX", "3")
    monkeypatch.setenv("PG_COMMAND_TIMEOUT", "15")
    # 禁用重排和改写，避免 lifespan 中创建 LLM/Rerank/Rewrite 实例时依赖不可用
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setenv("REWRITE_ENABLED", "false")
    # 嵌入/LLM API key: 寿命不需要真实调用，占位即可
    monkeypatch.setenv("EMBED_API_KEY", "sk-test-placeholder")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-placeholder")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def app(composition_settings, httpx_mock):
    """返回完全装配的 FastAPI 实例。

    httpx_mock 拦截所有 HTTP 调用（embedder/LLM），
    确保 lifespan 启动时不会有真实的网络请求。

    不启动 TestClient——调用者自行决定进入/退出上下文。
    """
    return build_app()


@pytest.fixture
def client(app):
    """返回已进入 lifespan 上下文（启动完成）的 TestClient。

    退出时自动执行 shutdown，关闭连接池和 httpx 客户端。
    """
    with TestClient(app) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════
# 场景 1: build_app() 启动与路由注册
# ═══════════════════════════════════════════════════════════════════


class TestBuildApp:
    """验证 build_app() 正常创建 FastAPI 实例并注册路由。"""

    def test_app_created_successfully(self, app):
        """build_app() 应返回 FastAPI 实例，且无需数据库即可构造。"""
        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_routes_registered(self, client):
        """验证核心路由已注册：health、create_kb、upload_doc、retrieve。

        lifespan 启动后路由可见——通过实际 HTTP 请求验证，而非检查 app.routes。
        """
        # health endpoint 应返回 200（或 503 若 DB 不可达，但至少路由存在）
        resp = client.get("/health")
        assert resp.status_code in (
            200,
            503,
        ), f"/health 路由未注册或异常，status={resp.status_code}"

        # create_kb 应返回 422（缺少必填字段）而非 404
        resp = client.post("/v1/knowledge-bases:create", json={})
        assert (
            resp.status_code != 404
        ), f"/v1/knowledge-bases:create 路由未注册，status={resp.status_code}"

        # upload_doc 应返回 422（缺少 Multipart form）而非 404
        resp = client.post("/v1/documents:upload")
        assert (
            resp.status_code != 404
        ), f"/v1/documents:upload 路由未注册，status={resp.status_code}"

        # retrieve 应返回 422（缺少必填字段）而非 404
        resp = client.post("/v1/rag:retrieve", json={})
        assert (
            resp.status_code != 404
        ), f"/v1/rag:retrieve 路由未注册，status={resp.status_code}"

    def test_lifespan_startup_completes(self, client):
        """TestClient 上下文进入应触发 lifespan 启动且不抛异常。"""
        # client fixture 已进入上下文——无异常即成功
        assert client is not None


# ═══════════════════════════════════════════════════════════════════
# 场景 2: /health 端点
# ═══════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """验证 GET /health 返回正确状态码和检查项。"""

    def test_health_returns_200(self, client):
        """/health 在数据库可用时应返回 200。"""
        resp = client.get("/health")
        assert (
            resp.status_code == 200
        ), f"unexpected status: {resp.status_code}, body: {resp.text}"

    def test_health_checks_database_ok(self, client):
        """响应中 checks.database 应为 'ok'。

        注意：代码使用键名 "database" 而非 "db"。
        """
        resp = client.get("/health")
        body = resp.json()
        assert body["status"] == "ok"
        assert body["checks"]["database"] == "ok", f"checks: {body['checks']}"

    def test_health_includes_version_and_uptime(self, client):
        """响应应包含 version、timestamp、uptime_seconds 等元数据。"""
        resp = client.get("/health")
        body = resp.json()
        assert "version" in body
        assert "timestamp" in body
        assert "uptime_seconds" in body
        assert "python_version" in body


# ═══════════════════════════════════════════════════════════════════
# 场景 3: 迁移告警
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def empty_alembic_version(pg_pool):
    """在 test-db 中创建空的 alembic_version 表。

    schema.sql 不创建该表；此 fixture 让 lifespan 中
    ``SELECT count(*) FROM alembic_version`` 返回 0，
    触发 ``_pending == 0`` 分支的 WARNING 日志。

    fixture 结束后清理该表。
    """
    await pg_pool.execute(
        "CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(32) NOT NULL)"
    )
    yield
    await pg_pool.execute("DROP TABLE IF EXISTS alembic_version")


class TestMigrationWarning:
    """验证 lifespan 检测到未迁移时记录 WARNING 日志。"""

    def test_migration_warning_logged(
        self,
        composition_settings,
        empty_alembic_version,
        capsys,
    ):
        """空 alembic_version 表应触发 '数据库迁移未执行' WARNING。

        技术细节：
        - ``setup_logging`` 设置 propagate=False，caplog 无法捕获。
        - 改用 capsys 捕获 stderr（console handler 写入 stderr）。
        """
        app = build_app()
        with TestClient(app):
            pass

        # 读取 stderr 输出（console handler 会输出 WARNING 到 stderr）
        captured = capsys.readouterr()
        assert (
            "数据库迁移未执行" in captured.err
        ), f"未找到迁移警告消息，stderr: {captured.err}"


# ═══════════════════════════════════════════════════════════════════
# 场景 4: 连接池关闭
# ═══════════════════════════════════════════════════════════════════


class TestShutdown:
    """验证 TestClient 退出后连接池正确关闭。"""

    def test_pools_closed_after_context_exit(self, app):
        """TestClient 上下文退出后，app.state 中的连接池应已关闭。"""
        raw_repo_pool = None

        with TestClient(app):
            # lifespan 已启动——检查 app.state 中是否有连接池
            assert hasattr(app.state, "repo_pool"), "app.state 缺少 repo_pool"
            raw_repo_pool = app.state.repo_pool._pool

        # 上下文退出后——连接池应已标记为关闭
        assert (
            raw_repo_pool.is_closing()
        ), "repo_pool 应在 TestClient 退出后处于关闭中状态"
        # store.pool 是 LoggedPool 包装，底层 _pool 也应关闭
        store_pool = app.state.store.pool
        if store_pool is not None:
            pool_backing = getattr(store_pool, "_pool", None)
            if pool_backing is not None:
                assert (
                    pool_backing.is_closing()
                ), "store 连接池应在 TestClient 退出后处于关闭中状态"

    def test_cleanup_tasks_cancelled(self, app):
        """TestClient 退出后，后台清理任务应被取消。"""
        with TestClient(app):
            tasks = getattr(app.state, "_cleanup_tasks", set())

        # 所有任务应已取消
        for t in tasks:
            assert t.cancelled(), f"清理任务未取消: {t}"


# ═══════════════════════════════════════════════════════════════════
# 场景 5: 生命周期错误恢复
# ═══════════════════════════════════════════════════════════════════


class TestLifespanErrorRecovery:
    """验证 lifespan 启动失败时资源清理正确。"""

    def test_connect_apperror_closes_raw_pool(
        self,
        app,
        monkeypatch,
    ):
        """PgVectorStore.connect() 抛 AppError → _raw_store_pool 应被关闭。

        _raw_store_pool 由 ``asyncpg.create_pool`` 创建于 connect()
        之前——finally 块应在异常传播后将其关闭。
        """
        import asyncpg

        from ragnexus.core.errors import AppError, ErrorCode

        # 记录所有通过 asyncpg.create_pool 创建的连接池
        created_pools: list[asyncpg.Pool] = []
        original_create_pool = asyncpg.create_pool

        async def tracking_create_pool(*args, **kwargs):
            pool = await original_create_pool(*args, **kwargs)
            created_pools.append(pool)
            return pool

        monkeypatch.setattr(asyncpg, "create_pool", tracking_create_pool)

        # 让 PgVectorStore.connect() 抛出 AppError
        async def mock_connect(self_inst, external_pool=None):
            raise AppError(ErrorCode.DB_CONNECTION_ERROR, "模拟连接失败")

        monkeypatch.setattr(
            "ragnexus.composition.PgVectorStore.connect",
            mock_connect,
        )

        # lifespan 启动失败，但 finally 应清理已创建的资源
        with pytest.raises(Exception):
            with TestClient(app):
                pass

        # lifespan 中 connect() 前创建了 _raw_store_pool
        assert len(created_pools) >= 1, "lifespan 未创建连接池"
        # 验证 finally 块关闭了所有已创建的连接池
        for i, pool in enumerate(created_pools):
            assert pool.is_closing(), f"第 {i} 个连接池未关闭——finally 块未正确清理"

    def test_shutdown_resources_order(self):
        """验证 _shutdown_resources 清理顺序：llm → embedder → repo → store → log。

        _shutdown_resources 是受保护函数，从 lifespan finally 调用。
        使用 mock 注入验证嵌套 try/finally 的调用顺序正确。
        """
        from unittest.mock import AsyncMock, MagicMock

        from ragnexus.composition import _shutdown_resources

        order: list[str] = []

        llm = MagicMock(spec=["close"])
        llm.close = AsyncMock(side_effect=lambda: order.append("llm"))
        emb = MagicMock(spec=["close"])
        emb.close = AsyncMock(side_effect=lambda: order.append("embedder"))
        repo = MagicMock(spec=["close"])
        repo.close = AsyncMock(side_effect=lambda: order.append("repo"))
        store = MagicMock(spec=["close"])
        store.close = AsyncMock(side_effect=lambda: order.append("store"))
        log = MagicMock(spec=["stop"])
        log.stop = MagicMock(side_effect=lambda: order.append("log"))

        asyncio.run(
            _shutdown_resources(
                llm_provider=llm,
                embedder=emb,
                _raw_repo_pool=repo,
                _raw_store_pool=store,
                log_listener=log,
            )
        )

        assert order == [
            "llm",
            "embedder",
            "repo",
            "store",
            "log",
        ], f"清理顺序错误，期望 [llm, embedder, repo, store, log]，实际 {order}"

    def test_shutdown_resources_partial_none(self):
        """_shutdown_resources 支持部分资源为 None（启动阶段异常路径）。

        当 connect 抛异常时，embedder/llm_provider/repo_pool 均未创建，
        但 store_pool 和 log_listener 需要清理。
        """
        from unittest.mock import AsyncMock, MagicMock

        from ragnexus.composition import _shutdown_resources

        order: list[str] = []

        store = MagicMock(spec=["close"])
        store.close = AsyncMock(side_effect=lambda: order.append("store"))
        log = MagicMock(spec=["stop"])
        log.stop = MagicMock(side_effect=lambda: order.append("log"))

        asyncio.run(
            _shutdown_resources(
                llm_provider=None,
                embedder=None,
                _raw_repo_pool=None,
                _raw_store_pool=store,
                log_listener=log,
            )
        )

        assert order == [
            "store",
            "log",
        ], f"部分清理顺序错误，期望 [store, log]，实际 {order}"
