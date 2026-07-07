# Task 1.5: 新增 observability 模块

## Task Requirements

### 1.5 新增 observability 模块
- **目标**: 创建 `langfuse_client.py`（RetrieveObservability + get_langfuse_client() + 静默逻辑）
- **文件**: `src/ragnexus/observability/__init__.py`, `langfuse_client.py`
- **要点**: LANGFUSE_ENABLED=false → 所有方法 noop；trace 创建 try/catch + warning；httpx trust_env=False
- **依赖**: 1.2, 1.4
- **验证**: 单元测试覆盖开关逻辑
- **预估**: 45min


## 设计要点 (from design doc)

### langfuse_client.py 结构
```python
class RetrieveObservability:
    def __init__(self, enabled: bool, client: Langfuse | None):
        self._enabled = enabled
        self._client = client

    def create_trace(self, name: str, metadata: dict) -> TraceContext | None:
        """创建 Langfuse trace。disabled 时返回 None"""
        ...

    def create_span(self, trace: TraceContext, name: str, input_data: dict) -> SpanContext | None:
        ...

    def end_span(self, span: SpanContext, output_data: dict):
        ...

    def end_trace(self, trace: TraceContext):
        ...

class TraceContext:  # 轻量封装
    trace_id: str
    _langfuse_trace: Any

class SpanContext:
    _langfuse_span: Any

def get_langfuse_client(settings) -> RetrieveObservability:
    if not settings.LANGFUSE_ENABLED:
        return RetrieveObservability(enabled=False, client=None)
    client = Langfuse(
        host=settings.LANGFUSE_HOST,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        httpx_client_kwargs={"trust_env": False}
    )
    return RetrieveObservability(enabled=True, client=client)
```

### 关键行为
- LANGFUSE_ENABLED=false → 所有方法 noop，零开销
- trace 创建用 try/catch + warning（不抛异常）
- httpx trust_env=False（避免代理干扰）
- `__init__.py` 只导出公开接口

## Acceptance
- 单元测试覆盖: enabled=false 时 noop, enabled=true 时 mock Langfuse 验证 trace/span 调用
- ruff check + pyright 通过

## TDD
- RED: 写测试 `test_observability_disabled_noop` → 验证 disabled 时 create_trace 返回 None
- RED: 写测试 `test_observability_enabled_creates_trace` → mock Langfuse, 验证 trace 创建
- GREEN: 实现代码使测试通过
