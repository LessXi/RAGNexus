# Proposal: E2E 测试 Bug 修复

## 动机
端到端测试发现 3 个代码问题，需要修复。

## 变更范围
- `admin/src/lib/axios.ts` — 移除默认 Content-Type header
- `admin/src/pages/create-kb.tsx` — 改进错误消息提取
- `src/ragnexus/adapters/rerank/llm.py` — 统一使用 ContextAdapter logger

## 非目标
- 不新增 capability
- 不改变 API 接口
- 不涉及架构调整
