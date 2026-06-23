# RAGNexus

RAG 中台骨架项目，采用六边形架构设计（domain → application → adapters），基于 Python 3.11 + FastAPI + asyncpg + pgvector。

## 快速开始（Docker Compose）

```bash
docker compose up
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
uv pip install -e ".[dev]"
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入实际的配置值
```

### 5. 启动服务

```bash
uv run main.py
```

## 使用示例（curl）

### 创建知识库（KB）

```bash
curl -X POST http://localhost:8000/knowledge-bases \
  -H "Content-Type: application/json" \
  -d '{"name": "我的知识库", "name_key": "my-kb"}'
```

### 上传文档

```bash
curl -X POST http://localhost:8000/knowledge-bases/my-kb/documents \
  -F "file=@example.pdf"
```

### 检索

```bash
curl -X POST http://localhost:8000/knowledge-bases/my-kb/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "你的问题", "top_k": 5}'
```

## 项目结构

```
ragnexus/
├── domain/          # 领域层 — 实体、值对象、仓库接口
├── application/     # 应用层 — 用例编排、DTO
├── adapters/        # 适配器层 — API、持久化、外部服务
├── docs/sql/        # 数据库 Schema
├── pyproject.toml   # 项目配置
└── .env.example     # 环境变量模板
```
