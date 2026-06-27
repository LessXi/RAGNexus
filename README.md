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
{"code": 10300, "data": null, "message": "资源不存在", "errors": [{"field": "kb_id", "reason": "..."}]}
```

| Code   | HTTP | 说明               |
|--------|------|--------------------|
| 0      | 200  | 成功               |
| 10001  | 422  | 参数错误           |
| 10002  | 422  | 缺少必要参数       |
| 10003  | 422  | 参数格式无效       |
| 10004  | 422  | 参数超出允许范围   |
| 10200  | 401  | 未授权，请登录     |
| 10201  | 403  | 权限不足           |
| 10202  | 401  | 登录已过期         |
| 10300  | 404  | 资源不存在         |
| 10301  | 409  | 资源冲突           |
| 10302  | 409  | 资源已存在         |
| 10400  | 415  | 不支持的文件类型   |
| 10401  | 413  | 文件过大           |
| 10402  | 422  | 文件为空           |
| 10500  | 502  | 上游服务异常       |
| 10501  | 504  | 上游服务超时       |
| 20001  | 504  | 接口请求超时       |
| 20002  | 429  | 接口调用超限       |
| 20003  | 405  | 请求方法错误       |
| 30001  | 500  | 数据库操作失败     |
| 30002  | 503  | 数据库连接失败     |
| 30003  | 504  | 数据库查询超时     |
| 30004  | 409  | 数据已存在         |
| 40000  | 502  | 大模型调用失败     |
| 40001  | 504  | 大模型响应超时     |
| 40002  | 502  | 大模型未返回有效内容 |
| 40003  | 422  | 内容违规           |
| 40004  | 422  | 上下文长度超限     |
| 40005  | 429  | 大模型调用频率超限 |
| 40006  | 503  | 模型不存在或未部署 |
| 50000  | 500  | 服务器异常         |
| 50001  | 500  | 服务配置错误       |
| 50002  | 503  | 系统繁忙，请稍后再试 |

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
