# Task 1-1: docker-compose 基础设施配置

## 状态：DONE

## 提交 hash
`aabfe55ff9a8f1b95c4182e552f915f058f4abc0`

## 变更概述
在 `docker-compose.yml` 中完成 4 步修改：

1. **添加 Redis 服务** — `redis:7-alpine`，暴露 6379 端口，含 healthcheck，挂载 `redisdata` 卷
2. **添加 Worker 服务** — Celery worker，连接 Redis broker + PostgreSQL + Elasticsearch
3. **添加 Beat 服务** — Celery beat scheduler，连接 Redis broker
4. **更新 app 服务** — `depends_on` 增加 `redis: service_healthy`
5. **添加 redisdata 卷** — 持久化 Redis 数据

## 验证命令输出

### `docker compose config --services`
```
elasticsearch
db
init-db
redis
app
beat
worker
```

### `docker compose config`
无错误退出（exit code 0）
