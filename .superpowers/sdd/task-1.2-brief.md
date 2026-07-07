# Task 1.2: config.py 新增 LANGFUSE_* 配置项

## Task Requirements

### 1.2 config.py 新增配置项
- **目标**: Settings 类新增 4 个 LANGFUSE_* 字段
- **文件**: `src/ragnexus/config.py`
- **依赖**: 1.1
- **验证**: `get_settings()` 可读取新字段
- **预估**: 10min


## Global Constraints
- 4 个新字段: LANGFUSE_ENABLED (bool, default False), LANGFUSE_HOST (str, default "http://localhost:3000"), LANGFUSE_PUBLIC_KEY (str, default ""), LANGFUSE_SECRET_KEY (str, default "")
- 使用 pydantic-settings Field(default=...)
- 放在现有 Settings 类的末尾
- 参考现有字段风格（如 LLM_API_KEY 等）

## Acceptance
- `from ragnexus.config import get_settings; s = get_settings(); print(s.LANGFUSE_ENABLED)` → False
- ruff check + pyright 通过
