# Task 1.2 — 异步索引生命周期：添加 celery + redis 依赖

## 状态：完成 ✓

## 变更内容
在 `pyproject.toml` 的 `dependencies` 列表中，`elasticsearch[async]` 之后新增：
```toml
"celery[redis]>=5.4.0,<6.0",
"redis>=5.0.0,<6.0",
```

## 提交信息
- **commit hash**: `4185b19`
- **message**: `feat(infra): pyproject.toml 增加 celery[redis] + redis 依赖`

## 验证输出

```bash
$ uv sync
Installed 15 packages:
  + amqp==5.3.1
  + billiard==4.2.4
  + celery==5.6.3
  + redis==5.3.1
  ...

$ uv run python -c "import celery; print(celery.__version__)"
5.6.3

$ uv run python -c "import redis; print(redis.__version__)"
5.3.1
```

## 结论
- `uv sync` 成功安装所有依赖（含新增的 celery 5.6.3、redis 5.3.1 及其传递依赖）
- `import celery` / `import redis` 均成功，输出版本号
- 已提交至 `feature/20260705/async-indexing-lifecycle` 分支
