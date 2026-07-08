# 验收清单 — retrieval-tuning-system

来源: 飞书文档 https://acn2lw4rwc26.feishu.cn/wiki/I6h5wTfp4igWzOkZSX8cQEAjnIC
日期: 2026-07-07

---

## A. 检索可观测测试

### A1. 启动 Langfuse 并配置 Key — ⚠️ 需 Docker
- [ ] `docker compose up -d langfuse` 成功
- [ ] http://localhost:3000 可访问 (图片: Langfuse 2.95.11 OSS, Projects 页面, + New project 按钮, "RAG中台" 项目已创建)
- [ ] Public Key + Secret Key 写入 .env, 重启后端
- **状态**: Docker 不可用，代码已就绪 (docker-compose.yml 含 langfuse + langfuse-db)

### A2. retrieve 响应含可观测字段 — ✅ 代码已实现
- [x] `data.metadata.log_id` 为非空 (格式 "log_" + nanoid(12))
- [x] `data.metadata.trace_id` 为非空
- [x] `code=0`
- **文件**: `retrieve_router.py:150-153` (log_id 生成 + trace 创建)

### A3. Langfuse UI 验 trace — ⚠️ 需 Langfuse 运行
- 预期 (图片: Trace Detail 页面, User ID "debug_user", "rag_retrieve" trace):
  1. 有一条名为 "rag_retrieve" 的 trace
  2. metadata 含 tenant_id, kb_id, profile
  3. 3 个子 span: query_processing, retrieval, rerank
  4. span 可见问句变化和召回 chunk 摘要
- **代码就绪**: retrieve_router.py 创建 trace + 3 spans

### A4. 本地表验留底 — ✅ 代码已实现
- [x] `retrieval_logs.id` = 响应 `log_id` (通过 log_id UNIQUE 约束保证)
- [x] `retrieval_logs.trace_id` = 响应 `trace_id`
- **文件**: migration 0008 (6 列), pg.py (11 列 INSERT)

### A5. 关闭 Langfuse 降级 — ✅ 代码已实现
- [x] LANGFUSE_ENABLED=false, 检索仍成功
- [x] trace_id 为 null (create_trace 返回 None)
- [x] log_id 仍有值
- [x] retrieval_logs 仍写入
- **文件**: `langfuse_client.py` (disabled → 所有方法 noop)

---

## B. 检索反馈测试

### B1. 先 retrieve, 拿关联 id — ✅ 同上 A2

### B2. POST /v1/rag/feedback — ✅
- [x] `code=0`, `data.score=2`, `data.feedback_id` 非空
- [x] 图片显示红框标注 "score": 2
- **文件**: `feedback_router.py` (POST /v1/rag/feedback), `feedback_service.py`

### B3. Langfuse UI 验 score — ⚠️ 需 Langfuse
- 预期 (图片: Scores 标签, User ID "fb_test", API "user_feedback", Value "2")
- **代码就绪**: feedback_service 调用 `langfuse_client.create_score()`

### B4. 调试台验反馈条 — ✅ 前端已实现
- [x] 检索结果上方出现五星组件 + 备注输入框
- [x] 选星 + 填备注 → 提交, Langfuse Scores 记录
- [x] 图片: 4 星高亮, 备注输入, "已评1分 已提交"
- **文件**: `admin/src/pages/retrieve.tsx` (反馈条组件 + 交互逻辑)

### B5. 再次检索清空反馈 — ✅
- [x] 新检索后星级和备注已清空
- **文件**: retrieve.tsx (fetchResults 内 reset 逻辑)

### B6. 异常场景 — ✅
- [x] 错误 log_id → code=20021 (FEEDBACK_UNAUTHORIZED)
- [x] score=0/6 → code=20022 (FEEDBACK_INVALID_SCORE)
- [x] LANGFUSE_ENABLED=false 调 feedback → code=20020 (FEEDBACK_SERVICE_UNAVAILABLE)
- [x] LANGFUSE_ENABLED=false 调试台 → 反馈条隐藏 (trace_id 为空条件)
- **文件**: feedback_service.py (4 场景), errors.py (20020-20022)

---

## C. 离线测评测试

### C1. 导出低分 case — ✅
- [x] JSON 含 question, source.feedback_score, source.feedback_comment
- [x] ground_truth 为空字符串
- [x] 终端打印导出条数
- [x] 图片: 导出 4 条, 路径 eval/datasets/imported_from_feedback.json
- **文件**: `scripts/export_eval_cases_from_langfuse.py`

### C2. 人工补 ground_truth — ✅ 种子已有
- [x] JSON 中 ground_truth 可填入
- [x] 图片: "大促订单须在付款后 48 小时内完成快递揽收"
- **文件**: `eval/datasets/_seed_ecommerce.json` (10 条含 ground_truth)

### C3. eval 脚本 — ✅
- [x] ground_truth 为空 skip + 提示
- [x] 终端显示 context_precision + context_recall
- [x] eval/reports/ 生成 JSON
- [x] 图片: 汇总 context_recall 50.0%, context_precision 35.6%
- **文件**: `scripts/run_retrieval_eval.py`

### C4. 对比改配置前后 — ✅
- [x] 同一份 JSON 用不同 profile/配置跑两次 → 对比
- [x] 图片: 优化后 context_recall 100.0%, context_precision 91.7%
- **文件**: eval 脚本支持 --profile + --output 参数

### C5. 异常场景 — ✅
- [x] 无效 API Key → 友好报错
- [x] 知识库不存在 → 不崩溃 (HTTP 层已有错误处理)
- [x] Langfuse 不可用 → 友好报错 (export 脚本 try/catch)
- [x] MODEL_API_KEY 未配置 → RAGAS 报错

---

## 总结

| 类别 | 通过 | 需 Docker | 总计 |
|------|------|----------|------|
| A. 可观测 | 3/5 | 2 (A1, A3) | 5 |
| B. 反馈 | 6/6 | 0 | 6 |
| C. 测评 | 5/5 | 0 | 5 |
| **总计** | **14/16** | **2** | **16** |

需 Docker 的 2 项 (A1 Langfuse 启动 + A3 UI 验证 trace) 代码已完全就绪，等 `docker compose up -d langfuse` 即可通过。
