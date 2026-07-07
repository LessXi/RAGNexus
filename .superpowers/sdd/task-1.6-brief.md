# Task 1.6: composition.py 注入 langfuse_client 单例

## Task Requirements

### 1.6 composition.py 注入单例
- **目标**: lifespan 中初始化 langfuse_client，注入到需要的地方
- **文件**: `src/ragnexus/composition.py`
- **依赖**: 1.5
- **验证**: 应用启动无 import 错误，LANGFUSE_ENABLED=false 时静默
- **预估**: 15min


## 设计要点
- 在 lifespan 函数中调用 `get_langfuse_client(settings)` 创建单例
- 注入到 `RetrieveRouter` 或通过 `app.state` 暴露
- LANGFUSE_ENABLED=false 时静默（不创建真实 client）
- 应用启动无 import 错误

## Acceptance
- `uv run python -c "from ragnexus.composition import build_app; app = build_app()"` 不报错
- LANGFUSE_ENABLED=false 时启动日志无 Langfuse 相关错误
