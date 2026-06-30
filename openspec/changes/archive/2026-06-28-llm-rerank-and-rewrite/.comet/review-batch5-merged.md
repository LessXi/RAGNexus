# 批次5合并审查报告：Task 5.1-5.3（thorough + OCR both 模式）

## 审查模式
`review_engine: both` — OCR + subagent 并行运行，合并去重

## OCR 结果（9 comments）
| # | 文件 | 严重度 | 内容摘要 |
|---|------|--------|---------|
| 1 | test_noop_rewrite.py | MINOR | 硬编码中文 reason 字符串，建议提取常量 |
| 2 | llm.py:281-285 | MINOR | 多 kb_ids 时重复 embed 同一 query（与 subagent 发现一致）|
| 3 | llm.py:405-428 | IMPORTANT | 精炼失败时丢弃有效改写结果，建议回退到长改写而非原始 query |
| 4 | llm.py:111-112 | MINOR | 正则提取嵌套 JSON 深度有限（实际风险低）|
| 5 | test_llm_rewrite.py:441-447 | MINOR | mock 风格不一致 |
| 6 | test_llm_rewrite.py:231-234 | MINOR | 直接测试私有函数 |
| 7 | test_rewrite_port.py:72-75 | MINOR | 缺类型注解断言 |
| 8 | test_rewrite_port.py:91-93 | MINOR | 缺参数 kind 断言 |
| 9 | test_rewrite_port.py:121-129 | MINOR | asyncio.run() 与项目约定不一致 |

## Subagent 结果
- Spec Compliance: 12/12 ✅
- Code Quality: Approved（3 个 MINOR/P3）
- 关键发现：
  1. [P3] _check_cache 在 kb_ids 循环内重复 embed（与 OCR #2 一致，去重）
  2. [P3] logger 引用风格与 LLMRerankProvider 不一致
  3. [P3] _refine_if_needed 首行死代码

## 合并去重后的发现

### IMPORTANT（1 项，建议修复）
1. **[OCR #3] 精炼失败丢弃有效改写** — 二次精炼失败时返回原始 query，丢弃了初次的长改写结果。建议回退到长 rewritten_query（needs_rewrite=True）而非完全降级。

### MINOR（7 项，非阻断，可后续处理）
1. [合并] _check_cache 重复 embed（OCR #2 + subagent P3 #1）
2. [subagent P3 #2] logger 引用风格不一致
3. [subagent P3 #3] _refine_if_needed 死代码
4. [OCR #1] 硬编码 reason 字符串
5. [OCR #4] 正则嵌套深度有限
6. [OCR #5/#6] 测试风格建议
7. [OCR #7/#8/#9] 测试断言完整性建议

## 判定
**通过审查。** Spec Compliance 全部通过，无 CRITICAL。1 个 IMPORTANT（精炼失败处理，建议修复但不阻断），7 个 MINOR（非阻断）。

## comet-ocr-integration skill 使用确认
✅ 本次审查按 `review_engine: both` 模式运行了 OCR CLI（`ocr review --from ... --to ... --format json`），OCR 返回 9 个 comments，与 subagent 结果合并去重。skill 正确介入。
