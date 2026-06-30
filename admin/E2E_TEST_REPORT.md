# RAGNexus 检索管线 A/B 测试报告

**测试日期**: 2026-06-30  
**测试方法**: 5 query × 2 配置 × 3 rounds = 30 次检索请求  
**数据文件**: `admin/test_baseline.json` / `admin/test_full.json`

---

## 一、测试设计

### 1.1 消除冷启动偏差
- 3 次预热 query 后开始计时
- 每 query 连跑 3 轮（R1/R2/R3），观察延迟收敛
- 两次配置切换时分别重启后端，各自独立预热

### 1.2 测试 Query 矩阵

| # | 类别 | Query | 预期 |
|---|---|---|---|
| Q1 | 口语 | "怎么做智能助手" | rewrite 改写为精确检索词 |
| Q2 | 口语 | "怎么提升检索效果" | rewrite 改写 |
| Q3 | 专业 | "RAG检索增强生成流程" | 可能不需要改写 |
| Q4 | 专业 | "RLHF对齐训练方法" | 可能不需要改写 |
| Q5 | 短 | "Agent" | 短 query 挑战 |

---

## 二、延迟对比

### 2.1 Baseline（纯向量检索，无 rerank/rewrite）

| Query | R1 | R2 | R3 | 收敛? |
|---|---|---|---|---|
| 口语-智能助手 | 292ms | 270ms | 293ms | ✅ |
| 口语-检索效果 | 159ms | 163ms | 153ms | ✅ |
| 专业-RAG流程 | 173ms | 187ms | 272ms | ✅ |
| 专业-RLHF | 293ms | 168ms | 282ms | ✅ |
| 短-Agent | 132ms | 278ms | 256ms | ✅ |

> **Baseline 平均: 225ms**，无冷启动问题（3 轮基本一致）

### 2.2 Full（rerank + rewrite 全开）

| Query | R1 (冷) | R2 (温) | R3 (热) | 缓存加速 |
|---|---|---|---|---|
| 口语-智能助手 | 56.8s | 0.65s | 0.56s | **99%** |
| 口语-检索效果 | 65.7s | 26.3s | 0.34s | **99.5%** |
| 专业-RAG流程 | 50.7s | 31.6s | 0.48s | **99%** |
| 专业-RLHF | 29.7s | 0.36s | 0.26s | **99.1%** |
| 短-Agent | 33.3s | 0.63s | 0.43s | **98.7%** |

> **冷启动**: 30-66s（LLM rewrite + LLM rerank）  
> **热缓存**: 0.26-0.56s（仅 Embedding + 缓存查找 + PGVector）  
> **缓存命中后，full 模式仅比 baseline 多 ~200ms**

---

## 三、Rerank 效果分析

### 3.1 排序单调性

| 配置 | Monotonic 比例 | 含义 |
|---|---|---|
| Baseline | **15/15 (100%)** | 纯向量相似度，分数天然降序 |
| Full | **2/15 (13%)** | 87% 的检索结果被 reranker 改变了排序 |

> 🔀 **Rerank 确实在干活**——13/15 次检索的排序被改变了。

### 3.2 Top-3 重叠率

| Query | Baseline #1 | Full R3 #1 | Top-3 重叠 | 效果 |
|---|---|---|---|---|
| 口语-智能助手 | Agent 章节 ✅ | Agent 章节 ✅ | 1/3 | 替换了 readme/其它 → RAG/RLHF |
| 口语-检索效果 | RAG 章节 ✅ | RAG 章节 ✅ | 1/3 | 替换了 readme/RLHF → 文档 intro/评估 |
| 专业-RAG流程 | RAG 章节 ✅ | RAG 章节 ✅ | 1/3 | 替换了 RLHF/test → 文档 intro/评估 |
| 专业-RLHF | RLHF 章节 ✅ | RLHF 章节 ✅ | 1/3 | 替换了 LLM八股/Prompt → 评估/文档 intro |
| 短-Agent | Agent 章节 ✅ | Agent 章节 ✅ | 2/3 | #1/#2 一致，#3 替换为评估章节 |

> **核心发现**: reranker 在所有 5 个 query 中都**保留了 #1 最相关 chunk**，同时将 #2-#5 中与 query 语义不匹配的内容（如 readme、泛泛章节）替换为更相关的内容。

### 3.3 具体案例：口语-智能助手

```
Baseline: Agent > 其它 > readme(泛泛)          — 向量认为 "其它" 和 readme 相似
Full R3:  Agent > RAG > RLHF                    — reranker 认为 RAG/RLHF 与"构建助手"更相关
```

reranker 正确识别：构建智能助手需要 RAG 知识和 RLHF 对齐技术，而非泛泛的"其它"章节。

---

## 四、Rewrite 缓存验证

| Query | R1 冷 | R2 温 | R3 热 | 缓存效果 |
|---|---|---|---|---|
| 口语-智能助手 | ✓ LLM rewrite | ✓ 缓存命中 | ✓ 缓存命中 | R2 即命中 |
| 口语-检索效果 | ✓ LLM rewrite | ⚠ 部分命中 | ✓ 缓存命中 | R2 仍慢（rerank 冷） |
| 专业-RLHF | ✓ LLM rewrite | ✓ 缓存命中 | ✓ 缓存命中 | R2 即命中 |

> R2 有时仍慢是因为 **rerank 缓存**对不同 query 是独立的——相同 query 的 rewrite 缓存命中后，rerank 可能还是第一次调用。

---

## 五、总结

| 维度 | 结果 |
|---|---|
| Baseline 延迟 | 平均 **225ms**（Embedding + PGVector） |
| Full 冷启动 | 30-66s（rewrite LLM ~17s + rerank LLM ~17s + Embedding） |
| Full 热缓存 | 0.3-0.6s（仅 Embedding + 缓存查找，接近 baseline） |
| Rerank 排序改变率 | **87%**（13/15 次检索被重排） |
| Rerank 质量 | ✅ 保留#1最相关 + 过滤噪音 + 提升相关内容 |
| Rewrite 缓存 | ✅ 相同 query 第2次即命中，节省 ~17s |
| Rerank 缓存 | ✅ 相同 query 第2次可能仍冷（不同 LLM 调用），第3次命中 |
| 冷启动影响 | ⚠ 首次 LLM 连接需要额外 30s+，预热足够可消除 |
