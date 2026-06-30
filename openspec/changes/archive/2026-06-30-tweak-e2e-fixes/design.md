# Design: E2E 测试 Bug 修复

## 修复 1: axios 默认 Content-Type
**文件**: `admin/src/lib/axios.ts`  
**问题**: `Content-Type: application/json` 覆盖了 multipart upload 必需的 `multipart/form-data`  
**方案**: 移除默认 header，让浏览器根据请求体自动设置

## 修复 2: 错误消息提取
**文件**: `admin/src/pages/create-kb.tsx`  
**问题**: catch 块显示原始 axios error（如 "Request failed with status code 409"）  
**方案**: 从 `AxiosError.response.data.message` 提取后端返回的中文错误消息

## 修复 3: rerank logger req_id
**文件**: `src/ragnexus/adapters/rerank/llm.py`  
**问题**: 使用裸 `logging.getLogger("ragnexus")` 而非项目的 ContextAdapter，导致 req_id 丢失  
**方案**: 替换为 `from ragnexus.core.logger import logger`，与 rewrite 模块保持一致
