# 阶段 5 综合实施 Brief — QueryPipeline

## 任务范围

Tasks 5.1-5.3：新增 `adapters/rewrite/pipeline.py` + 单元测试

## 规格

### QueryPipeline 类

```python
class QueryPipeline:
    """查询处理流水线 — 串联改写+词表扩展，输出三阶段结果。

    raw_query → rewrite() → effective_query → expand() → search_query
    """

    def __init__(self, rewriter: RewritePort, expander: SynonymExpander):
        self.rewriter = rewriter
        self.expander = expander

    async def process(
        self,
        raw_query: str,
        kb_context: dict | None = None,
        synonyms: list[dict] | None = None,
        enabled: bool = True,
    ) -> QueryProcessResult:
```

### process() 逻辑

```
enabled=false:
  → 返回 noop QueryProcessResult:
    raw=effective=search=raw_query
    needs_rewrite=False, strategy="noop"
    rewrite_latency_ms=0, degraded=False
    synonym_applied=False, synonym_expansions=[]

enabled=true:
  1. 调 rewriter.rewrite(query=raw_query, kb_ids=..., kb_context=kb_context)
     → 获取 QueryProcessResult（改写字段已填）
  2. 若 synonyms 有值:
     → 调 expander.expand(result.effective_query, synonyms)
     → 覆盖 result.search_query, result.synonym_applied, result.synonym_expansions
  3. 返回完整结果

rewrite() 抛异常:
  → 捕获，构造 degraded QueryProcessResult:
    raw=effective=search=raw_query
    needs_rewrite=False, strategy="rewrite"
    rewrite_latency_ms=0, degraded=True, degraded_reason=str(exc)
    synonym_applied=False, synonym_expansions=[]
```

### kb_ids 处理

多 KB 时取 `kb_ids[0]` 对应的 KB 上下文（name、description、settings）。
但 pipeline.process() 接收的是已组装好的 kb_context（由 use_case 层组装），不需要在 pipeline 内部再查 KB。

### 测试场景 (task 5.3)

1. 改写+扩展同开: enabled=true, rewrite 成功, synonyms 有命中 → effective≠raw, search≠effective
2. 仅改写: enabled=true, synonyms=None → effective≠raw, search==effective
3. enabled=false: → strategy="noop", 三阶段相同
4. rewrite 异常降级: rewrite() 抛异常 → degraded=True, effective==raw
5. rewrite 内部降级透传: rewrite 返回 degraded=True → pipeline 透传 degraded 状态

## 约束

- 文件: `src/ragnexus/adapters/rewrite/pipeline.py`
- 测试: `tests/unit/test_pipeline.py`
- 使用 async/await（rewriter.rewrite() 是异步的）
- 需要 mock RewritePort 和 SynonymExpander 进行测试
