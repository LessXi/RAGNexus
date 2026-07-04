"""工厂函数: create_kb_tree_router — GET /v1/knowledge-bases/tree。"""

from fastapi import APIRouter, Query

from ragnexus.application.kb_tree_use_case import GetKnowledgeBaseTreeUseCase


def create_kb_tree_router(use_case: GetKnowledgeBaseTreeUseCase) -> APIRouter:
    """返回含 GET /v1/knowledge-bases/tree 端点的 APIRouter。

    use_case 必须提供 ``async def execute(keyword: str | None = None) -> list[TenantKBTree]``。
    """

    router = APIRouter()

    @router.get("/v1/knowledge-bases/tree")
    async def get_tree(
        keyword: str | None = Query(None, description="模糊匹配 tenant_id"),
    ):
        """获取租户→知识库→文档的三级树结构。"""
        trees = await use_case.execute(keyword=keyword)
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
                    }
                    for d in kb.documents
                ],
            }
            for kb in tree.knowledge_bases
        ],
    }
