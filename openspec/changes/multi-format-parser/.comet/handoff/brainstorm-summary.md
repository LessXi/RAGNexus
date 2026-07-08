# Brainstorm Summary

- Change: multi-format-parser
- Date: 2026-07-07

## 确认的技术方案

1. **DocxParser**：直接用 mammoth 文档转换事件 API 产出 `sections` 结构，不经过 mammoth→Markdown→再解析的中间步骤。标题 1/2 样式映射为 Section(heading, level)，表格映射为 Section(content)。

2. **PdfParser**：PyMuPDF 按页抽取文字，每页一个 Section（heading=`第 N 页`, level=2）。本期不做启发式标题检测，后续根据实际效果迭代。

3. **文件存储清理**：原文件始终保留以支持任意次数 reparse，仅在 Document 被删除时同步删除对应文件。

4. **Upload 双模式**：独立路由 `/v1/documents:upload-text`（JSON body），与现有 multipart 路由分离。

5. **ParsedDocument**：保持 sections 模型，扩展 source_type + metadata 字段。chunking 零改动。

6. **IndexingService**：在 parse 前增加 `_prepare_content()` 步骤，从 `source_file_path` 读取并解析二进制文件。

## 关键取舍与风险

- **取舍**：选择 sections 模型而非扁平 Markdown 字符串 → 保持现有 splitter 验证不变，但要求每个 Parser 理解 sections 语义
- **风险**：mammoth 对中文 Word 的标题样式识别准确率未知 → 验证阶段用真实中文制度文档实测
- **风险**：大 PDF 解析可能超时 → Celery task 设置合理 timeout，PyMuPDF 按页流式读取

## 测试策略

- 单元测试：DocxParser、PdfParser、registry、UploadUseCase 双模式
- 集成测试：扫描件 PDF→FAILED、JSON upload 回归
- E2E 验证脚本：docx/pdf/md 三种上传 → retrieve 验证
- 回归测试：运行现有 319 个测试确认零破坏

## Spec Patch

无（本次不修改任何已有 spec 的需求级行为，纯新增 `multi-format-parsing` capability）
