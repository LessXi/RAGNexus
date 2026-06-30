## ADDED Requirements

### Requirement: pytest-cov 配置

系统 SHALL pytest-cov 配置。

#### Scenario: 覆盖率只统计源码
- **WHEN** 运行 pytest --cov
- **THEN** 仅统计 src/ragnexus/ 目录下的代码
- **AND** 不统计 tests/、.venv/、alembic/ 等目录

#### Scenario: 覆盖率报告可读
- **WHEN** 运行 pytest --cov --cov-report=term
- **THEN** 终端输出按文件展示覆盖率百分比
