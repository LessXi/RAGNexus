# Task 1.4: pyproject.toml 新增 langfuse 依赖

## Task Requirements

### 1.4 pyproject.toml 新增依赖
- **目标**: 添加 `langfuse>=2.0.0,<3.0.0`
- **文件**: `pyproject.toml`
- **依赖**: 无
- **验证**: `pip install -e .` 成功
- **预估**: 5min


## Global Constraints
- 在 [project] dependencies 中添加 `"langfuse>=2.0.0,<3.0.0"`
- 按字母序排列依赖

## Acceptance
- `uv pip install -e .` 成功（安装 langfuse）
- `uv run python -c "import langfuse; print(langfuse.__version__)"` 输出版本号 >= 2.0.0
