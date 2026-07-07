# Task 1.0: 确认 Alembic 初始化

## Phase Context
Phase 1: Langfuse 基础设施 (7 任务, ~2.5h)

## Task Requirements

### 1.0 确认 Alembic 初始化
- **目标**: 确保 `alembic` 已 init，`migrations/` 目录可用
- **文件**: `alembic.ini`, `migrations/env.py`
- **依赖**: 无
- **验证**: `alembic current` 不报错
- **预估**: 15min


## Global Constraints

- 语言: 中文注释/docstring，技术术语保持英文
- TDD: 先写失败测试，再写实现
- 迁移编号: 使用 0008（最新已有 migration 是 0007_tenant_plan.py）
- 代码质量: ruff check + pyright 通过
- 提交规范: 每个 task 一次提交，commit message 体现设计意图

## Files to Touch
- `alembic.ini` (检查)
- `migrations/env.py` (检查)
- 可能需要在工作树中运行 `alembic init` 补全（若缺失）

## Acceptance
- `uv run alembic current` 不报错
- `migrations/versions/` 目录存在且可写入
