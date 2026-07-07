# Task 1.3: .env 和 .env.example 补充 LANGFUSE_* 变量

## Task Requirements

### 1.3 .env 和 .env.example 补充变量
- **目标**: 添加 LANGFUSE_* 变量及说明
- **文件**: `.env`, `.env.example`
- **依赖**: 1.2
- **验证**: grep LANGFUSE .env 输出 4 行
- **预估**: 10min


## Global Constraints
- .env 添加 4 行注释 + 变量
- .env.example 同步添加（带注释说明）
- 格式: `LANGFUSE_ENABLED=false` 等
- 缺省值: ENABLED=false, HOST=http://localhost:3000, PUBLIC_KEY=, SECRET_KEY=

## Acceptance
- `grep -c LANGFUSE .env` 输出 >= 4
- `grep -c LANGFUSE .env.example` 输出 >= 4
