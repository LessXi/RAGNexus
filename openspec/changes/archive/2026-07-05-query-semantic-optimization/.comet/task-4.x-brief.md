# 阶段 4 综合实施 Brief — SynonymExpander

## 任务范围

Tasks 4.1-4.4：新增 `adapters/rewrite/synonym_expander.py` + 单元测试

## 规格

### SynonymExpander 类

```python
class SynonymExpander:
    """词表扩展器 — 基于 KB settings.synonyms 对有效查询追加扩展词。

    规则（按设计文档 §词表扩展规则）：
    - 遍历 effective_query 对每组 synonyms.terms 做中文精确子串匹配
    - 英文 casefold 匹配
    - 命中组的 expand 词去重后追加到 query 末尾
    - 多组同时命中时 expand 去重合并
    - 格式异常的 synonyms 静默跳过，不抛异常
    """

    def expand(
        self, effective_query: str, synonyms: list[dict] | None
    ) -> tuple[str, bool, list[str]]:
        """扩展查询。

        返回: (search_query, synonym_applied, expansions)
        - search_query: 追加扩展词后的查询
        - synonym_applied: 是否有词表命中
        - expansions: 实际追加的扩展词列表
        """
```

### synonyms 格式

```json
[
  {"terms": ["背调"], "expand": ["背景调查", "标准问题清单"]},
  {"terms": ["薪酬", "薪资", "工资"], "expand": ["职级", "薪酬定级"]}
]
```

### 实现逻辑

```python
def expand(self, effective_query: str, synonyms: list[dict] | None) -> tuple[str, bool, list[str]]:
    if not synonyms:
        return effective_query, False, []

    all_expansions: list[str] = []
    query_lower = effective_query.lower()

    for group in synonyms:
        try:
            terms = group.get("terms", [])
            expand_words = group.get("expand", [])
            if not isinstance(terms, list) or not isinstance(expand_words, list):
                continue
        except Exception:
            continue

        # 检查是否命中
        hit = False
        for term in terms:
            if not isinstance(term, str):
                continue
            if term.lower() in query_lower:
                hit = True
                break

        if hit:
            for word in expand_words:
                if isinstance(word, str) and word not in all_expansions:
                    all_expansions.append(word)

    if not all_expansions:
        return effective_query, False, []

    # 去重后追加
    search_query = effective_query + " " + " ".join(all_expansions)
    return search_query, True, all_expansions
```

### 测试场景 (task 4.4)

1. 单组命中: query 含"背调" → 追加"背景调查 标准问题清单"
2. 多组命中+去重: query 含"背调"和"薪酬" → 去重合并
3. 未命中: query 不含任何 terms
4. 英文大小写: casefold 匹配
5. 空词表: synonyms=[] → 返回原 query
6. 格式错误容错: 畸形 synonyms 结构不抛异常
7. 跨组扩展词去重: 两组 expand 含相同词 → 只追加一次

## 约束

- 文件: `src/ragnexus/adapters/rewrite/synonym_expander.py`
- 测试: `tests/unit/test_synonym_expander.py`
- 中文 docstring
- 不依赖外部服务，纯字符串处理
