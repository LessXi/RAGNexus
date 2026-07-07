import asyncpg

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocStatus
from ragnexus.tenant.plan_presets import PLAN_PRESETS


class QuotaService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def check_kb_count(self, tenant_id: str, plan: str) -> None:
        limit = PLAN_PRESETS[plan]["limits"]["max_kb"]
        count = await self._pool.fetchval(
            "SELECT count(*) FROM knowledge_bases WHERE tenant_id=$1", tenant_id
        )
        if count >= limit:
            raise AppError(ErrorCode.QUOTA_EXCEEDED, f"当前套餐仅支持 {limit} 个知识库")

    async def check_doc_upload(self, kb_id: str, tenant_id: str, plan: str) -> None:
        limits = PLAN_PRESETS[plan]["limits"]
        doc_count = await self._pool.fetchval(
            "SELECT count(*) FROM documents WHERE kb_id=$1", kb_id
        )
        if doc_count >= limits["max_documents_per_kb"]:
            raise AppError(
                ErrorCode.QUOTA_EXCEEDED,
                f"单库最多 {limits['max_documents_per_kb']} 个文档",
            )
        await self.check_processing(tenant_id, plan)

    async def check_processing(self, tenant_id: str, plan: str) -> None:
        limit = PLAN_PRESETS[plan]["limits"]["max_processing_documents"]
        count = await self._pool.fetchval(
            "SELECT count(*) FROM documents d JOIN knowledge_bases kb ON kb.id=d.kb_id "
            "WHERE kb.tenant_id=$1 AND d.status=$2",
            tenant_id,
            DocStatus.PROCESSING.value,
        )
        if count >= limit:
            raise AppError(
                ErrorCode.QUOTA_EXCEEDED, "并发索引文档数已达上限，请稍后再试"
            )
