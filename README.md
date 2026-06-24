# RAGNexus

RAG 中台骨架项目，采用六边形架构设计（domain → application → adapters），基于 Python 3.11 + FastAPI + asyncpg + pgvector。

## 快速开始（Docker Compose）

```bash
docker compose up -d db app
```

服务将在 `http://localhost:8000` 启动。

## 手动安装

### 1. 安装 pgvector

请参考 [pgvector 官方文档](https://github.com/pgvector/pgvector#installation) 安装并配置 PostgreSQL 扩展。

### 2. 初始化数据库

```bash
psql -U your_user -d your_db -f docs/sql/schema.sql
```

### 3. 安装 Python 依赖

```bash
uv sync
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际的配置值（EMBED_API_KEY 必填）
```

### 5. 启动服务

```bash
uv run python main.py
```

## 使用示例（curl）

### 创建知识库（KB）

```bash
curl -X POST http://localhost:8000/v1/knowledge-bases:create \
  -H "Content-Type: application/json" \
  -d '{"name": "我的知识库"}'
```

响应：

```json
{"code": 0, "data": {"kb_id": "kb_AbCdEfGh", "name": "我的知识库", "created_at": "..."}, "message": "ok"}
```

### 上传文档（仅 .md / .txt）

```bash
curl -X POST http://localhost:8000/v1/documents:upload \
  -F "kb_id=kb_AbCdEfGh" \
  -F "file=@example.md"
```

响应：

```json
{"code": 0, "data": {"doc_id": "doc_3a7f9c2e8b1d4567", "kb_id": "kb_AbCdEfGh", "chunk_count": 5}, "message": "ok"}
```

### 检索

```bash
curl -X POST http://localhost:8000/v1/rag:retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "你的问题", "kb_ids": ["kb_AbCdEfGh"], "top_k": 5}'
```

响应：

```json
{"code": 0, "data": {"total": 3, "hits": [{"chunk_id": "...", "score": 0.95, "text": "...", "metadata": {...}}]}, "message": "ok"}
```

## 错误响应格式

所有错误返回统一结构：

```json
{"code": 1100, "data": null, "message": "资源不存在", "errors": [{"field": "kb_id", "reason": "..."}]}
```

| Code | HTTP | 说明 |
|------|------|------|
| 1000 | 422 | 参数错误 |
| 1100 | 404 | 资源不存在 |
| 1200 | 409 | 资源冲突 |
| 1201 | 409 | 文档已存在 |
| 1300 | 415 | 不支持的文件类型 |
| 1301 | 413 | 文件过大 |
| 1400 | 422 | 文件为空 |
| 1500 | 502 | 上游服务异常 |
| 1600 | 500 | 配置不匹配 |

## 项目结构

```
ragnexus/
├── domain/              # 领域层 — 实体、错误、chunking 策略、端口协议
│   ├── models.py
│   ├── errors.py
│   ├── chunking.py
│   └── ports.py
├── application/         # 应用层 — 用例编排
│   ├── create_kb_use_case.py
│   ├── upload_doc_use_case.py
│   └── retrieve_use_case.py
├── adapters/            # 适配器层 — HTTP、存储、嵌入、解析
│   ├── http/
│   ├── vector_store/
│   ├── knowledge_base/
│   ├── embedder/
│   ├── retrieve_log/
│   └── parsers/
├── composition.py       # DI 容器 + FastAPI lifespan
├── config.py            # pydantic-settings 配置
├── main.py              # 入口
├── docs/sql/            # 数据库 Schema
├── pyproject.toml       # 项目配置
└── .env.example         # 环境变量模板
```
