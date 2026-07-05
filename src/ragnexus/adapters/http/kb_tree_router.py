"""工厂函数: create_kb_tree_router — GET /v1/knowledge-bases/tree（按租户过滤）。"""

from fastapi import APIRouter, Depends, Query

from ragnexus.application.kb_tree_use_case import GetKnowledgeBaseTreeUseCase
from ragnexus.core.auth import TenantContext


def create_kb_tree_router(
    use_case: GetKnowledgeBaseTreeUseCase, get_current_tenant
) -> APIRouter:
    """返回含 GET /v1/knowledge-bases/tree 端点的 APIRouter。

    use_case 必须提供 ``async def execute(tenant_id: str, keyword: str | None = None) -> list[TenantKBTree]``。
    get_current_tenant 是 make_get_current_tenant 返回的 Depends 可调用对象。
    """

    router = APIRouter()

    @router.get("/v1/knowledge-bases/tree")
    async def get_tree(
        current_tenant: TenantContext = Depends(get_current_tenant),
        keyword: str | None = Query(None, description="模糊匹配 KB 名称"),
    ):
        """获取当前租户的知识库→文档三级树结构。"""
        trees = await use_case.execute(
            tenant_id=current_tenant.tenant_id, keyword=keyword
        )
        return {
            "code": 0,
            "data": [_tree_to_dict(t) for t in trees],
            "message": "ok",
        }

    return router


def _tree_to_dict(tree):
    """递归将 TenantKBTree 转为纯 dict，用于 JSON 序列化。"""
    return {
        "tenant_id": tree.tenant_id,
        "knowledge_bases": [
            {
                "kb_id": kb.kb_id,
                "name": kb.name,
                "description": kb.description,
                "document_count": kb.document_count,
                "total_chunks": kb.total_chunks,
                "created_at": kb.created_at,
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "filename": d.filename,
                        "status": d.status,
                        "uploaded_at": d.uploaded_at,
                        "error_message": d.error_message,
                    }
                    for d in kb.documents
                ],
            }
            for kb in tree.knowledge_bases
        ],
    }
