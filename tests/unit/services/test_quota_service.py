"""QuotaService 单元测试 —— 知识库/文档/并发索引配额检查。"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from ragnexus.services.quota_service import QuotaService
from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus


def _mock_pool(fetchval_return=None):
    """构造一个带 fetchval 的 mock asyncpg.Pool。"""
    pool = MagicMock()
    pool.fetchval = AsyncMock(return_value=fetchval_return)
    return pool


class TestCheckKbCount:
    """check_kb_count: 知识库数量配额检查。"""

    @pytest.mark.asyncio
    async def test_exceeds_limit_raises(self):
        """free 套餐 max_kb=1，已有 1 个则超限。"""
        pool = _mock_pool(1)
        svc = QuotaService(pool)

        with pytest.raises(AppError) as exc_info:
            await svc.check_kb_count("t1", "free")
        assert exc_info.value.code == ErrorCode.QUOTA_EXCEEDED
        assert "知识库" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_within_limit_passes(self):
        """pro 套餐 max_kb=50，已有 5 个，通过。"""
        pool = _mock_pool(5)
        svc = QuotaService(pool)

        # 不应抛异常
        await svc.check_kb_count("t2", "pro")

    @pytest.mark.asyncio
    async def test_uses_tenant_id_in_query(self):
        """验证 SQL 查询使用了正确的 tenant_id。"""
        pool = _mock_pool(0)
        svc = QuotaService(pool)

        await svc.check_kb_count("my-tenant", "standard")
        pool.fetchval.assert_called_once()
        sql = pool.fetchval.call_args[0][0]
        assert "tenant_id=$1" in sql


class TestCheckDocUpload:
    """check_doc_upload: 单库文档数 + 并发处理数检查。"""

    @pytest.mark.asyncio
    async def test_doc_count_exceeded_raises(self):
        """free 套餐 max_documents_per_kb=30，已达 30 则超限。"""
        pool = _mock_pool(30)
        svc = QuotaService(pool)

        with pytest.raises(AppError) as exc_info:
            await svc.check_doc_upload("kb1", "t3", "free")
        assert exc_info.value.code == ErrorCode.QUOTA_EXCEEDED
        assert "文档" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_within_doc_limit_passes(self):
        """文档数未超限时正常通过（并发也未超）。"""
        # fetchval 第一次返回 5 (doc count)，第二次返回 0 (processing count)
        pool = MagicMock()
        pool.fetchval = AsyncMock(side_effect=[5, 0])
        svc = QuotaService(pool)

        await svc.check_doc_upload("kb2", "t4", "standard")

    @pytest.mark.asyncio
    async def test_calls_check_processing(self):
        """check_doc_upload 内调用 check_processing。"""
        pool = MagicMock()
        pool.fetchval = AsyncMock(side_effect=[0, 0])
        svc = QuotaService(pool)

        await svc.check_doc_upload("kb3", "t5", "pro")
        # 确认 fetchval 被调用了两次（一次 doc count，一次 processing count）
        assert pool.fetchval.call_count == 2


class TestCheckProcessing:
    """check_processing: 并发索引文档数检查。"""

    @pytest.mark.asyncio
    async def test_exceeds_limit_raises(self):
        """pro 套餐 max_processing_documents=10，已达 10 则超限。"""
        pool = _mock_pool(10)
        svc = QuotaService(pool)

        with pytest.raises(AppError) as exc_info:
            await svc.check_processing("t6", "pro")
        assert exc_info.value.code == ErrorCode.QUOTA_EXCEEDED
        assert "并发" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_within_limit_passes(self):
        pool = _mock_pool(1)
        svc = QuotaService(pool)
        await svc.check_processing("t7", "standard")

    @pytest.mark.asyncio
    async def test_uses_docstatus_processing_in_query(self):
        """验证 SQL 查询中用了 DocStatus.PROCESSING (值为 2)。"""
        pool = _mock_pool(0)
        svc = QuotaService(pool)

        await svc.check_processing("t8", "free")
        pool.fetchval.assert_called_once()
        sql = pool.fetchval.call_args[0][0]
        assert "d.status=$2" in sql
        # 确认参数用了 DocStatus.PROCESSING.value = 2
        args = pool.fetchval.call_args[0]
        assert args[2] == DocStatus.PROCESSING.value == 2
