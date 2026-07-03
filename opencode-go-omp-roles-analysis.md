# OpenCode Go 模型 × OMP Role 深度匹配分析（最终版）

> 分析日期：2026-07-01 | 数据来源：benchmark 交叉验证 + 全网用户反馈（Reddit/HN/GitHub/V2EX/独立评测）+ OpenCode Go 平台可靠性追踪
> 上一版的主要错误：按 benchmark 分层代替按角色需求匹配，忽略了真实用户反馈和平台可靠性

---

## 一、方法论修正

### 1.1 第一性原理框架

**最终目标**：为 OMP 的 10 个角色找到最优模型。正确方法：

```
对于每个角色 R，定义约束函数：
  f(model) = w1×编程质量 + w2×工具调用可靠性 + w3×速度 + w4×成本 + w5×上下文 + w6×平台稳定性

其中 w1-w6 的权重由角色需求决定，而非由 benchmark 数字决定。
```

### 1.2 数据来源分层

| 层级 | 来源 | 可信度 | 示例 |
|:---:|------|:---:|------|
| L1 | 独立第三方 benchmark（Scale SEAL） | ★★★★★ | GLM-5.2 SWE-bench Pro 62.1% |
| L2 | 多用户交叉验证的实际体验 | ★★★★ | "Flash 超过 6-8 次工具调用开始错误级联" |
| L3 | 单一深度用户长期使用报告 | ★★★ | "Flash 用 500K 上下文完成汇编内核重写" |
| L4 | 厂商自报 benchmark | ★★ | Kimi K2.7 MCPMark 81.1（未独立复现） |
| L5 | 匿名社区帖 | ★ | Reddit "比 DeepSeek Flash 好" |

**本报告优先采用 L1-L3 数据做决策，L4-L5 仅作参考。**

---

## 二、OpenCode Go 平台风险（新增）

**这是比单个模型选择更重要的发现。** 5 个子代理交叉验证了以下平台级问题：

### 2.1 上游账户反复耗尽（致命级）

| 时间 | 受影响模型 | 影响 |
|------|-----------|------|
| 2026-04-26 | Kimi K2.5/K2.6 + GLM-5.1 | 至少两个上游供应商账户同时耗尽 |
| 2026-05-14 | **11/12 模型** | 子代理（Task tool、UltraWork）完全瘫痪 |
| 2026-05-17 | MiMo 系列 | 再次耗尽 |

**结论**：task 角色（依赖子代理）在 OpenCode Go 上**不可靠**。这不是偶发故障，是**反复发生的模式**。

### 2.2 速度严重缩水

| 模型 | OpenCode Go | 官方 API | 倍数 |
|------|:---:|:---:|:---:|
| DeepSeek V4 Flash（thinking 模式） | 71s | 2.4s | **29x** |
| DeepSeek V4 Flash（无 thinking） | 21s | 1.9s | 11x |
| MiniMax M2.5 | "明显变慢" | — | 用户报告 |

### 2.3 量化争议

Reddit r/LocalLLaMA 帖（94% 赞同率，72 赞）指控 OpenCode Go 使用量化版模型（FP16→INT8），导致准确率下降。独立测试显示 MiniMax 质量在 Go 和其他平台上一致，但 GLM-5.1 存在缓存崩溃导致成本飙升。

### 2.4 对角色推荐的直接影响

| 影响 | 受影响的角色 |
|------|------------|
| 子代理大面积不可用 | **task**（致命） |
| 模型速度远慢于官方 | **smol**（速度是首要需求） |
| 上游降价未传递配额 | **default**（17,150/月可能不够） |
| Qwen3.7 成功率仅 60-70% | **advisor** |
| 配额计数器 bug | 所有角色 |

---

## 三、模型全量评估（benchmark + 用户反馈）

### 3.1 Tier 1 旗舰模型

#### GLM-5.2 — SWE-bench Pro 冠军，但 API 不可靠

| 维度 | Benchmark 说 | 用户实际说 |
|------|-------------|-----------|
| SWE-bench Pro | **62.1%** 🥇（Scale SEAL 标准化） | 规划得分 9.0/10（vs Kimi K2.7 的 8.1） |
| 长程自主 | FrontierSWE #3，11h | "reasoning traces 可见但逻辑混乱，自说自话" |
| API 可靠性 | — | **"2 天近乎完全不可用"**（285 次 429 错误，50% 失败率） |
| 速度 | — | "慢，read files 步骤花很长时间" |
| 整体评价 | "good enough but not best-in-class" | 用户："我愿意切换，但成本理由不够" |

**角色适配**：slow/plan（API 不可靠是硬伤，但低频使用可承受风险）

#### Qwen3.7 Max — 推理最强，但最贵

| 维度 | Benchmark 说 | 用户实际说 |
|------|-------------|-----------|
| SWE-bench Pro | 60.6% | 纯文本编码领先 |
| 数学 | GPQA Diamond 92.4%，HMMT 97.1% | — |
| 自主性 | 35h，1000+ tool calls | — |
| 平台稳定性 | — | **成功率仅 60-70%**，Cloudflare 524 超时频繁 |
| 价格 | $2.50/$7.50/1M | 最贵，高频使用不可行 |

**角色适配**：slow 备选（数学推理场景）

#### Kimi K2.7 Code — 工具调用之王，但被平台和设计锁死

| 维度 | Benchmark 说 | 用户实际说 |
|------|-------------|-----------|
| MCPMark | **81.1**（超 Claude Opus 4.8 的 76.4） | 所有 benchmark 为**厂商自报，零独立验证** |
| CoT | 推理 token -30% | **"chain-of-thought 锁定开启，无法关闭"** |
| 可控性 | — | temperature=1.0, top_p=0.95 **固定**；tool_choice 只支持 auto/none |
| 上下文 | 256K | 所有 Tier-1 模型中最小 |
| 工具调用 bug | — | **已知 tool-call 循环 bug**；benchmark 操纵指控 |

**角色适配**：task（工具调用强，但平台子代理不可用 + 强制 CoT + 不可控参数大幅削弱实用性）

#### DeepSeek V4 Pro — 全能平衡王

| 维度 | Benchmark 说 | 用户实际说 |
|------|-------------|-----------|
| LiveCodeBench | 93.5% | — |
| 上下文 | 1M | 真实可用 |
| 缓存 | — | **85%+ 命中率**，大幅降低成本 |
| 多步 agent | — | **"error cascade" 问题**——错误级联导致可靠性下降 |
| 冗长度 | — | **4-5x 更多输出 token**，实际成本高于标价 |
| 速度 | 34 t/s | 慢于同行中位数 55 t/s |

**角色适配**：default（仍是综合最优，但需注意冗长度和 agent 级联问题）

#### MiMo-V2.5-Pro — agent 长跑冠军，但 reliability 堪忧

| 维度 | Benchmark 说 | 用户实际说 |
|------|-------------|-----------|
| SWE-bench Pro | ~62%（with MiMo Code harness） | "strongest open weights agentic coding" — HN |
| 长程自主 | **1,868 次工具调用/11.5h**；301 commits/125 sessions | 构建完整编译器（233/233 tests）和桌面视频编辑器 |
| Token 效率 | **58% 少于 Claude Opus 4.7** | 387M tokens, $70 完成 301 commits |
| 致命 bug | — | **loop-thinking：1,803 次重复/569s 卡死/零输出** |
| 工具调用 bug | — | high-thinking 模式 **tool_use 转换失败**（14 次/会话） |
| 实际上下文 | 声称 1M | **Hybrid SWA 架构：6/7 层只有 128-token 本地窗口** |
| 速度 | — | "fast, responsive"，但比 Flash 慢 |

**角色适配**：task（agent 能力最强但 reliability bugs 严重）、slow 备选

---

### 3.2 Tier 2 中坚模型

#### Qwen3.7 Plus — 被严重低估的多模态 agent

| 维度 | 用户实际说 |
|------|-----------|
| Terminal-Bench | **70.3% — 所有评测模型中最高**（超过 Claude Opus 4.6 的 65.4%） |
| BugFix-10 | **10/10 — 超过 Max 的 9/10** |
| 性质 | **不是 Max 的缩水版，是独立的多模态模型** |
| 速度 | 147.5 t/s（3.55x Qwen3.6 Plus） |
| GUI | ScreenSpot Pro 79.0 — 超 GPT-5.4 |
| 社区评分 | 质量 8.4/10, agentic 8.3/10, 速度 8.4/10, 可靠性 8.7/10 |
| 平台问题 | 60-70% 成功率，Cloudflare 超时 |
| 价格 | $0.40/$1.60/1M（6.25x 低于 Max） |

**角色适配**：advisor（异构 + 多模态 + Terminal-Bench 最强）、vision 备选

#### MiniMax M3 — 多模态性价比之王

| 维度 | 用户实际说 |
|------|-----------|
| 多模态 | **原生图像+视频**，1M 上下文 |
| 自主性 | 12h 复现 ICLR 论文，24h CUDA 内核优化 |
| 性价比 | **6.25x 低于 Qwen3.7 Max** |
| 实际体验 | "更自然，更容易跟上"，比 Qwen 更清晰 |
| 弱点 | 纯数学/推理弱于 Qwen3.7 Max |

**角色适配**：vision、designer（多模态唯一可靠选择）

#### MiMo-V2.5（基础版）— 隐藏的性价比炸弹

| 维度 | 用户实际说 |
|------|-----------|
| 性价比 | **Claude Opus 级别智能，$49 完成全部 benchmark**（vs Opus 的 $2,969） |
| 多模态 | **支持图像/视频/音频（Pro 版不支持！）** |
| 质量 | "better follow-through than Gemini" |
| 对比 Flash | "benchmark 和价格都优于 DeepSeek V4 Flash" — Reddit |
| 速度 | "比 Flash 慢，消耗 token 更多" |
| 部署 | "极难部署，采样参数极其敏感" |
| 工具调用 | benchmark 89/100，但 Context & State 仅 60/100 |

**角色适配**：smol（性价比极高 + 多模态 + 比 Flash 更好的质量）、vision 备选

---

### 3.3 Tier 3 工作马

#### DeepSeek V4 Flash — 有界任务的神，无界任务的坑

| 维度 | 用户实际说 |
|------|-----------|
| 结构任务 | **盲测与 Pro 无法区分**（单文件脚手架、测试、配置转换） |
| 系统编程 | 完成汇编内核重写、TypeScript→C++ 移植、io_uring HTTP 服务器 |
| 缓存 | **98.5% 缓存命中率** |
| 致命限制 | **超过 6-8 次工具调用开始错误级联，12 次完全脱轨** |
| 指令遵循 | 长会话中**忘记开头设定的指令** |
| 平台速度 | OpenCode Go 上 **71s vs 官方 2.4s（29x 慢）** |
| 日常成本 | $0.52/晚 |

**角色适配**：smol（仅适用于简单独立子任务，不能用于多步 agent 循环）、tiny、commit

---

### 3.4 前代模型速评

| 模型 | 一句话 | 是否推荐 |
|------|--------|:---:|
| GLM-5.1 | 长程自主强但极慢（44 t/s）、缓存崩溃、编辑工具不兼容 | ❌ |
| Kimi K2.6 | 极度不一致：一边 13h 零干预重构，一边被 Opus 完爆；OSS 部署 87% 失败率 | ❌ |
| MiniMax M2.7 | 速度明显下降，服务过载 | ❌ |
| Qwen3.6 Plus | 前端原型强但生产代码弱，社区失望 | ❌ |

---

## 四、最终角色匹配（含平台风险调整）

### 匹配总表

```
┌──────────┬─────────────────────────┬──────────────────────────────────────┬──────────┐
│ 角色     │ 推荐模型                │ 核心理由                              │ 风险等级  │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ default  │ DeepSeek V4 Pro         │ 1M上下文+93.5% LiveCodeBench+85%缓存  │ 🟡 中    │
│          │ :high                   │ 冗长度和agent级联是已知问题            │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ smol     │ MiMo-V2.5               │ Claude Opus级智能仅$49；多模态；      │ 🟡 中    │
│          │ (不加thinking后缀)      │ benchmark和价格均优于Flash            │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ slow     │ GLM-5.2 :high           │ SWE-bench Pro 62.1%（Scale SEAL）     │ 🔴 高    │
│          │ 备选: MiMo-V2.5-Pro     │ API曾2天不可用；低频使用可承受         │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ plan     │ GLM-5.2 :high           │ 规划9.0/10（vs Kimi 8.1）；          │ 🔴 高    │
│          │                         │ FrontierSWE #3                        │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ task     │ ⚠️ 平台风险 - 降级策略   │ 见下方详细说明                        │ 🔴 极高  │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ advisor  │ Qwen3.7 Plus :medium    │ Terminal-Bench 70.3%最高；异构审查；   │ 🟡 中    │
│          │                         │ 多模态；可靠性8.7/10                  │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ tiny     │ DeepSeek V4 Flash       │ 极简任务，无需agent能力               │ 🟢 低    │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ vision   │ MiniMax M3              │ 原生多模态质量最好                     │ 🟢 低    │
│          │ 备选: MiMo-V2.5         │ 更便宜且也支持图像                     │          │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ designer │ MiniMax M3              │ 唯一可靠多模态选择                     │ 🟢 低    │
├──────────┼─────────────────────────┼──────────────────────────────────────┼──────────┤
│ commit   │ DeepSeek V4 Flash       │ 最便宜                                │ 🟢 低    │
└──────────┴─────────────────────────┴──────────────────────────────────────┴──────────┘
```

### 关键变更 vs 上一版

| 角色 | 上一版 | 最终版 | 变更原因 |
|------|--------|--------|----------|
| **smol** | DeepSeek V4 Flash | **MiMo-V2.5** | Flash 超过 6-8 次工具调用会错误级联；MiMo-V2.5 benchmark 和价格都更好 + 多模态 |
| **slow** | Qwen3.7 Max→GLM-5.2 | **GLM-5.2**（不变） | GLM-5.2 的 Scale SEAL 数据是 L1；Max 在平台成功率仅 60-70% |
| **task** | Kimi K2.7 Code | **⚠️ 降级策略** | 平台子代理反复不可用；Kimi CoT 锁定+参数不可控 |
| **advisor** | Qwen3.7 Plus | **Qwen3.7 Plus**（不变但理由强化） | Terminal-Bench 70.3% 最高+多模态+异构 |

### task 角色降级策略（平台风险应对）

由于 OpenCode Go 上游账户反复耗尽导致子代理不可用，task 角色需要分层降级：

```
正常时：  Kimi K2.7 Code（MCPMark 81.1，但需预留 reasoning_content）
         ↓ 不可用时
降级 1：  MiMo-V2.5-Pro（1,868 次工具调用/11.5h，但需设 repetition_penalty=1.2）
         ↓ 不可用时
降级 2：  DeepSeek V4 Pro（1M 上下文，但超过 6-8 步 agent 循环会错误级联）
         ↓ 不可用时
降级 3：  MiMo-V2.5（基础 agent 能力，超低价格）
```

**Kimi K2.7 Code 使用注意事项**（来自用户反馈）：
- 不能关闭 CoT → 每个 turn 必须保留 reasoning_content
- temperature/top_p 固定不可调 → 输出不可复现
- tool_choice 仅 auto/none → 无法强制调用特定工具
- 已知 tool-call 循环 bug → 3 次连续相同调用后人工介入
- 所有 benchmark 为自报 → 实际体验可能低于预期

---

## 五、完整配置方案

```yaml
# ~/.omp/agent/config.yml
modelRoles:
  default: opencode-go/deepseek-v4-pro:high
  smol: opencode-go/mimo-v2.5
  slow: opencode-go/glm-5.2:high
  plan: opencode-go/glm-5.2:high
  task: opencode-go/kimi-k2.7-code:medium
  advisor: opencode-go/qwen3.7-plus:medium
  tiny: opencode-go/deepseek-v4-flash
  vision: opencode-go/minimax-m3
  designer: opencode-go/minimax-m3
  commit: opencode-go/deepseek-v4-flash

cycleOrder:
  - smol
  - default
  - slow

defaultThinkingLevel: medium
thinkingBudgets:
  minimal: 1024
  low: 2048
  medium: 8192
  high: 16384
  xhigh: 32768

# 配额 + 子代理不可用双重降级
retry:
  modelFallback: true
  fallbackChains:
    opencode-go/deepseek-v4-pro:
      - opencode-go/mimo-v2.5-pro
      - opencode-go/qwen3.7-plus
    opencode-go/kimi-k2.7-code:
      - opencode-go/mimo-v2.5-pro
      - opencode-go/deepseek-v4-pro
      - opencode-go/mimo-v2.5
```

---

## 六、配额与风险矩阵

### 6.1 配额预估（$60/月）

| 模型 | 角色 | 月请求 | 风险 |
|------|------|:---:|------|
| DeepSeek V4 Flash | tiny/commit | 158,150 | 🟢 |
| Qwen3.7 Plus | advisor | 21,600 | 🟢 |
| DeepSeek V4 Pro | default | 17,150 | 🟡 冗长度导致实际消耗更高 |
| MiMo-V2.5 | smol | 150,400 | 🟢 |
| MiniMax M3 | vision/designer | 16,000 | 🟢 |
| Kimi K2.7 Code | task | 9,250 | 🔴 平台不可用风险 > 配额风险 |
| Qwen3.7 Max | slow 备选 | 4,770 | 🟢（低频） |
| GLM-5.2 | slow/plan | 4,300 | 🔴 API 可靠性风险 > 配额风险 |

### 6.2 风险拓扑

| 风险 | 概率 | 影响 | 缓解 |
|------|:---:|------|------|
| 子代理大面积不可用 | **高**（4-5月重复3次） | task 角色瘫痪 | fallbackChains + 手动切换 |
| GLM-5.2 API 不可用 | 中 | slow/plan 不可用 | 备选 Qwen3.7 Max / MiMo-V2.5-Pro |
| 速度严重缩水 | 中（特定模型） | smol 失去速度优势 | MiMo-V2.5 本身不快，影响可控 |
| 配额计数器 bug | 低 | 假超限阻断 | 控制台手动检查 |
| 量化质量下降 | 低（仅部分模型） | 输出质量降低 | 未普遍证实 |

---

## 七、一句话总结

**OpenCode Go 对 OMP 的适用性分两层**：

1. **作为轻中度日常编码辅助**：$10/月覆盖全部 10 个角色性价比极高。DeepSeek V4 Pro + MiMo-V2.5 + GLM-5.2 + Qwen3.7 Plus + MiniMax M3 的组合覆盖了从海量扇出到深度推理的全部需求。

2. **作为重度/自动化 agent 平台**：**不适合**。上游账户反复耗尽导致子代理瘫痪、速度缩水、配额不透明、无客服——这些是架构性问题而非偶发 bug。如果你的工作流依赖大量 task 子代理并行，应当考虑直接使用各厂商 API 而非通过 OpenCode Go 中转。

**最终推荐**：OpenCode Go 适合作为 OMP 的「日常主力 + 降级备选」，但不适合作为「唯一依赖」。对于 task 角色，做好随时手动降级的心理准备。
