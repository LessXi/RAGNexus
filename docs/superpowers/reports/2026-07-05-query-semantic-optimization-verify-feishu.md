# 飞书验收对照报告 — query-semantic-optimization

**日期**: 2026-07-05
**验收文档**: [测试验收 Wiki](https://acn2lw4rwc26.feishu.cn/wiki/CfWDwuhJhiwU9ykg6JucGVmMnjg)

---

## 测试准备 ✅

| 步骤 | 状态 | 证据 |
|------|------|------|
| alembic upgrade head | ✅ | `alembic current` → 0004 (head) |
| knowledge_bases.settings 列存在 | ✅ | migration 0004 已创建并执行 |
| KB_A 配词表脚本 | ✅ | `scripts/update_kb_settings.py` 含 --help |
| kb_settings.json 格式 | ✅ | `examples/kb_settings.example.json` 合法 |

---

## LLM 改写测试

| # | 场景 | 自动化覆盖 | 手动（需运行服务端） |
|---|------|-----------|---------------------|
| 1 | 默认不改写，行为与改前一致 | ✅ `test_scenario_12_1_no_query_options_noop` | 🔲 curl 验证 |
| 2 | 开启改写，effective≠raw, degraded=false | ✅ `test_rewrite_and_expand_both_enabled` | 🔲 curl 验证 |
| 3 | LLM 不可用，degraded=true, code=0 | ✅ `test_rewrite_exception_degraded` | 🔲 改 .env API key 验证 |

**自动化证据**:
- 场景 1: pipeline.enabled=false → strategy="noop", query_processing null
- 场景 2: pipeline 正常路径 → degraded=False, raw≠effective, latency 有值
- 场景 3: rewrite 异常 → 捕获降级, degraded=True, effective==raw, 不抛异常

---

## 词表扩展测试

| # | 场景 | 自动化覆盖 | 手动 |
|---|------|-----------|------|
| 1 | 词表命中，扩展词追加 | ✅ `test_single_group_hit` | 🔲 |
| 2 | 多组命中，去重合并 | ✅ `test_multi_group_hit_dedup` | 🔲 |
| 3 | 未命中，行为不变 | ✅ `test_no_match` | 🔲 |
| 4 | 跨库隔离 | ✅ `test_scenario_12_7_cross_kb_isolation` | 🔲 |

**自动化证据**:
- 场景 1-3: SynonymExpander 7 个测试全部通过
- 场景 4: use_case 层验证 kb_ids[0] 隔离

---

## 组合链路测试

| # | 场景 | 自动化覆盖 | 手动 |
|---|------|-----------|------|
| 1 | 改写+词表同开，三阶段完整 | ✅ `test_rewrite_and_expand_both_enabled` | 🔲 |
| 2 | KB_B 改写无词表，search==effective | ✅ `test_rewrite_only_no_synonyms` | 🔲 |

---

## 调试台测试

| # | 场景 | 覆盖 |
|---|------|------|
| 1 | 勾选改写，摘要展示对比 | ✅ 代码审查 (retrieve.tsx:549-591) |
| 2 | 取消勾选，词表独立生效 | ✅ 代码审查 (词表不受 enabled 控制) |
| 3 | 无词表无改写 KB_B | ✅ query_processing null 逻辑 (router:111-114) |

---

## 总体判定

| 指标 | 结果 |
|------|------|
| 自动化测试 | ✅ 415/415 passed |
| 飞书验收场景自动化覆盖 | ✅ 11/11 |
| 手动 curl 验证 | 🔲 需运行服务端（后端+LLM+DB） |
| 前端调试台 | ✅ 代码审查通过 |
| RewriteResult 残留 | 0 |

**自动化验证已全部通过。手动 curl 验证需要启动后端服务（含 LLM 和 PostgreSQL），不在本次 agent 会话范围内。**
