"""PgKnowledgeBaseRepository — 知识库元数据 CRUD 适配器。

基于 asyncpg 实现 KnowledgeBasePort。
"""

import json
import asyncpg
from nanoid import generate as nanoid_generate

from ragnexus.core.errors import AppError, ErrorCode
from ragnexus.domain.models import DocNode, KBNode, KnowledgeBase, TenantKBTree


class PgKnowledgeBaseRepository:
    """Postgres (asyncpg) 知识库元数据适配器。"""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create(
        self, name: str, name_key: str, tenant_id: str = ""
    ) -> KnowledgeBase:
        """创建知识库。自动重试 nanoid 碰撞，只捕获 name_key 约束冲突。

        Raises:
            AppError(ErrorCode.RESOURCE_CONFLICT): name_key 重复时。
        """
        max_retries = 3
        for attempt in range(max_retries):
            kb_id = "kb_" + nanoid_generate(size=8)
            try:
                row = await self.pool.fetchrow(
                    "INSERT INTO knowledge_bases (id, name, name_key, tenant_id, settings) "
                    "VALUES ($1, $2, $3, $4, $5::jsonb) "
                    "RETURNING id, name, created_at, tenant_id, settings",
                    kb_id,
                    name,
                    name_key,
                    tenant_id,
                    "{}",
                )
                return KnowledgeBase(
                    id=row["id"],
                    name=row["name"],
                    created_at=row["created_at"],
                    tenant_id=row["tenant_id"],
                    settings=row["settings"] or {},
                )
            except asyncpg.UniqueViolationError as e:
                # 检查冲突的约束名，区分 name_key 唯一冲突 vs kb_id 碰撞
                constraint: str = getattr(e, "constraint_name", "") or ""
                if "name_key" in constraint:
                    raise AppError(
                        ErrorCode.RESOURCE_CONFLICT,
                        "知识库名称已存在",
                        errors=[{"field": "name", "reason": f"{name!r} 已存在"}],
                    ) from e
                # pkey/id 约束 → kb_id 碰撞（nanoid 极小概率）→ 重试
                if "pkey" in constraint or "knowledge_bases_pkey" in constraint:
                    if attempt == max_retries - 1:
                        raise AppError(
                            ErrorCode.SERVER_ERROR, "知识库 ID 生成失败，请重试"
                        ) from e
                    continue
                # 无法识别约束名 → 保守当作 name_key 冲突
                raise AppError(
                    ErrorCode.RESOURCE_CONFLICT,
                    "知识库名称已存在",
                    errors=[{"field": "name", "reason": f"{name!r} 已存在"}],
                ) from e

    async def get(self, kb_id: str) -> KnowledgeBase | None:
        """按 ID 获取知识库，不存在返回 None。"""
        row = await self.pool.fetchrow(
            "SELECT id, name, description, tenant_id, created_at, settings FROM knowledge_bases WHERE id=$1",
            kb_id,
        )
        return KnowledgeBase(**dict(row)) if row else None

    async def get_settings(self, kb_id: str) -> dict:
        """获取 KB 的 settings（JSONB 列）。不存在时返回 {}。"""
        row = await self.pool.fetchrow(
            "SELECT settings FROM knowledge_bases WHERE id = $1", kb_id
        )
        if row is None:
            return {}
        return row["settings"] or {}

    async def update_settings(self, kb_id: str, settings: dict) -> None:
        """更新（覆盖）KB 的 settings。"""

        await self.pool.execute(
            "UPDATE knowledge_bases SET settings = $1::jsonb WHERE id = $2",
            json.dumps(settings, ensure_ascii=False),
            kb_id,
        )

    async def update(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        settings: dict | None = None,
    ) -> KnowledgeBase:
        """更新知识库字段。仅更新传入的非 None 字段。

        无任何字段变更时退化为 get() 查询。

        Raises:
            AppError(ErrorCode.NOT_FOUND): 知识库不存在时。
        """
        sets: list[str] = []
        params: list = []
        idx = 1
        if name is not None:
            sets.append(f"name = ${idx}")
            params.append(name)
            idx += 1
        if description is not None:
            sets.append(f"description = ${idx}")
            params.append(description)
            idx += 1
        if settings is not None:
            sets.append(f"settings = ${idx}::jsonb")
            params.append(json.dumps(settings, ensure_ascii=False))
            idx += 1
        if not sets:
            return await self.get(kb_id)  # type: ignore[return-value]
        params.append(kb_id)
        row = await self.pool.fetchrow(
            f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ${idx} "
            "RETURNING id, name, description, tenant_id, created_at, settings",
            *params,
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, f"知识库 {kb_id} 不存在")
        # asyncpg JSONB 返回 str，需 json.loads 反序列化
        kb_settings_raw = row["settings"] or {}
        kb_settings = (
            json.loads(kb_settings_raw)
            if isinstance(kb_settings_raw, str)
            else kb_settings_raw
        )
        return KnowledgeBase(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
            settings=kb_settings,
        )

    async def delete(self, kb_id: str) -> None:
        """删除知识库及其关联数据。

        依赖外键 CASCADE 自动清理 documents 及下游 chunks。
        """
        await self.pool.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)

    async def has_processing_docs(self, kb_id: str) -> bool:
        """检查知识库下是否有处理中的文档（status=2）。

        硬编码 status=2 对应 DocStatus.PROCESSING，避免循环导入。
        """
        result = await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE kb_id = $1 AND status = 2 LIMIT 1",
            kb_id,
        )
        return result is not None

    async def exists(self, kb_id: str) -> bool:
        """检查知识库是否按 ID 存在。"""
        return bool(
            await self.pool.fetchval(
                "SELECT 1 FROM knowledge_bases WHERE id=$1",
                kb_id,
            )
        )

    async def doc_exists(self, doc_id: str) -> bool:
        """检查文档是否按 doc_id 存在。"""
        return bool(
            await self.pool.fetchval(
                "SELECT 1 FROM documents WHERE doc_id=$1",
                doc_id,
            )
        )

    async def list_with_documents(
        self, tenant_id: str, keyword: str | None = None
    ) -> list[TenantKBTree]:
        """获取单租户→KB→文档三级树。

        LEFT JOIN knowledge_bases + documents，按 tenant_id 过滤，keyword 模糊匹配 KB 名称。
        """
        from collections import defaultdict

        kw_pattern = f"%{keyword}%" if keyword else "%%"
        rows = await self.pool.fetch(
            "SELECT kb.tenant_id, kb.id AS kb_id, kb.name, kb.created_at, "
            "d.doc_id, d.filename, d.uploaded_at, d.chunk_count, d.status, d.error_message "
            "FROM knowledge_bases kb "
            "LEFT JOIN documents d ON d.kb_id = kb.id "
            "WHERE kb.tenant_id = $1 AND kb.name ILIKE $2 "
            "ORDER BY kb.tenant_id, kb.created_at DESC, d.uploaded_at DESC",
            tenant_id,
            kw_pattern,
        )

        # 组装: 三层嵌套 group by (tenant_id, kb_id)
        # tenant_map: tenant_id → kb_map
        # kb_map: kb_id → {info, docs: list[DocNode]}
        tenant_map: dict[str, dict[str, dict]] = {}
        kb_order: dict[str, list[str]] = defaultdict(list)  # tenant → [kb_id ordered]

        for row in rows:
            tid = row["tenant_id"]
            kid = row["kb_id"]

            if tid not in tenant_map:
                tenant_map[tid] = {}
            if kid not in tenant_map[tid]:
                tenant_map[tid][kid] = {
                    "name": row["name"],
                    "created_at": row["created_at"].isoformat(),
                    "documents": [],
                    "total_chunks": 0,
                }
                kb_order[tid].append(kid)

            # 文档行可能为 NULL（LEFT JOIN 无匹配）
            if row["doc_id"] is not None:
                kb_info = tenant_map[tid][kid]
                _status_map = {1: "success", 2: "processing", 3: "failed"}
                kb_info["documents"].append(
                    DocNode(
                        doc_id=row["doc_id"],
                        filename=row["filename"],
                        status=_status_map.get(row["status"], "processing"),
                        uploaded_at=row["uploaded_at"].isoformat(),
                        error_message=row.get("error_message"),
                    )
                )
                kb_info["total_chunks"] += row["chunk_count"] or 0

        # 组装为 list[TenantKBTree]
        result: list[TenantKBTree] = []
        for tid in sorted(tenant_map.keys()):
            kb_list: list[KBNode] = []
            for kid in kb_order[tid]:
                info = tenant_map[tid][kid]
                kb_list.append(
                    KBNode(
                        kb_id=kid,
                        name=info["name"],
                        description="",
                        document_count=len(info["documents"]),
                        total_chunks=info["total_chunks"],
                        created_at=info["created_at"],
                        documents=info["documents"],
                    )
                )
            result.append(TenantKBTree(tenant_id=tid, knowledge_bases=kb_list))
        return result
