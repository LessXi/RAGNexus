## 实现说明

### 问题 1：`log_model_call` 硬编码截断

`logger.py:377-381` 和 `logger.py:399-403` 中对 `prompt_val` 和 `result_str` 执行了 `[:200] + "..."` 截断。此截断在格式化之前发生，同时影响文件和控制台输出。

**修复**：移除字段级别的截断逻辑。控制台输出由 `_TruncatingColoredFormatter`（`max_length=500`）在最终格式化行级别截断，文件 Handler 获得完整内容。

### 问题 2：中间件不记录请求体

`middleware.py:57-67` 的 API_REQUEST 日志仅记录 `body_present` 和 `body_length` 元数据，不记录实际请求体内容。设计文档要求对 JSON 请求体"读取并回填"。

**修复**：在 `extra` 字典中添加 `body` 字段，记录 JSON 请求体的字符串表示。multipart 请求和读取失败场景保持跳过。

### 设计约束

- 控制台截断行为不变：`_TruncatingColoredFormatter` 仍将最终行截断至 500 字符
- 文件 Handler 无额外截断：`RotatingFileHandler` 使用标准 `logging.Formatter`，不做字段截断
- 无新增配置项，不改变现有接口
