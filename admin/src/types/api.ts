/** API 请求/响应类型定义 */

/** 创建知识库请求 */
export interface CreateKBRequest {
  name: string;
}

/** 创建知识库响应 */
export interface CreateKBResponse {
  code: number;
  data: {
    kb_id: string;
    name: string;
    created_at: string;
  };
  message: string;
}

/** 上传文档响应 */
export interface UploadDocResponse {
  code: number;
  data: {
    doc_id: string;
    kb_id: string;
    chunk_count: number;
  };
  message: string;
}

/** API 错误响应 */
export interface ApiErrorResponse {
  code: number;
  data: null;
  message: string;
  errors?: { field: string; reason: string }[];
}

/** 缓存的知识库 */
export interface CachedKB {
  kb_id: string;
  name: string;
  created_at: string;
}

/** 上传结果条目 */
export interface UploadResultEntry {
  name: string;
  size: number;
  status: 'success' | 'failed';
  detail: string; // 成功时 chunk 数，失败时原因
}

/** 文件预过滤跳过条目 */
export interface SkippedFile {
  name: string;
  size: number;
  reason: string;
}

/** 上传进度回调 */
export type UploadProgressCallback = (progress: {
  current: number;
  total: number;
  currentFile: string;
  successCount: number;
  failCount: number;
}) => void;
