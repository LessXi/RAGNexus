# Task 1.1: docker-compose 新增 langfuse 服务

## Phase Context
Phase 1: Langfuse 基础设施 — 添加 Langfuse 自托管服务到 docker-compose

## Task Requirements

### 1.1 docker-compose 新增 langfuse 服务
- **目标**: 添加 langfuse + langfuse-db service + langfusedata volume
- **文件**: `docker-compose.yml`
- **要点**: NEXTAUTH_URL, NEXTAUTH_SECRET, ENCRYPTION_KEY, 独立 Postgres 库名 langfuse, :3000 端口, healthcheck
- **依赖**: 1.0（无直接依赖，并行）
- **验证**: `docker compose up -d langfuse` → Langfuse UI 可访问
- **预估**: 20min


## Global Constraints
- Langfuse 是**可选旁路**，不加 depends_on（app 不依赖它启动）
- langfuse-db: 独立 Postgres，库名 `langfuse`（不是 ragnexus）
- langfuse: 镜像 `langfuse/langfuse:2`，端口 `:3000`
- 必须配置: NEXTAUTH_URL, NEXTAUTH_SECRET, ENCRYPTION_KEY
- named volume: `langfusedata`
- healthcheck: 需要
- NEXTAUTH_URL: `http://localhost:3000`
- NEXTAUTH_SECRET: 生成随机字符串（至少 32 字符）
- ENCRYPTION_KEY: 生成随机字符串

## Design Decisions (from design doc)
- langfuse 服务在 docker-compose 中定义，但不阻塞 app 启动
- 独立 Postgres 实例避免污染业务数据库
- named volume 确保重启不丢数据

## Acceptance
- `docker compose up -d langfuse` 成功启动
- Langfuse UI 可通过 http://localhost:3000 访问
- `docker compose ps` 显示 langfuse + langfuse-db 为 healthy
