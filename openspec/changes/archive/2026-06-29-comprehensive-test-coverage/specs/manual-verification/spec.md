## ADDED Requirements

### Requirement: 手工验收脚本

系统 SHALL 手工验收脚本。

#### Scenario: 一键启动验收环境
- **WHEN** 运行 bash scripts/verify-production.sh
- **THEN** Docker Compose 启动 test-db
- **AND** Alembic upgrade head 执行
- **AND** 全量确定性测试执行
- **AND** 真实 API E2E 测试执行（需 EMBED_API_KEY + LLM_API_KEY）
- **AND** 覆盖率报告生成
- **AND** 打印验收结果摘要

#### Scenario: 验收脚本不进 CI
- **WHEN** CI 环境运行 pytest
- **THEN** verify-production.sh 不被调用
- **AND** 真实 API 测试被 pytest.mark.skipif 跳过

#### Scenario: 验收失败时清理
- **WHEN** 验收过程中任一步骤失败
- **THEN** 脚本打印失败原因
- **AND** Docker Compose 被停止（teardown）
