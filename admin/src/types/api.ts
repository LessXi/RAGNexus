/** API 请求/响应类型定义 */

/** 创建知识库请求 */
export interface CreateKBRequest {
  name: string;
  tenant_id?: string;
}

/** 创建知识库响应 */
export interface CreateKBResponse {
  code: number;
  data: {
    kb_id: string;
    name: string;
    tenant_id: string;
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

/** Tree API 中的文档节点 */
export interface DocItem {
  doc_id: string;
  filename: string;
  status: string;
  uploaded_at: string;
}

/** Tree API 中的知识库节点 */
export interface KBItem {
  kb_id: string;
  name: string;
  description: string;
  document_count: number;
  total_chunks: number;
  created_at: string;
  documents: DocItem[];
}

/** Tree API 中的租户节点 */
export interface TreeItem {
  tenant_id: string;
  knowledge_bases: KBItem[];
}

/** Tree API 响应包装 */
export interface TreeResponse {
  code: number;
  data: TreeItem[];
  message: string;
}

/** 检索请求 */
export interface RetrieveRequest {
  query: string;
  kb_ids: string[];
  top_k?: number;
  mode?: "vector" | "bm25" | "hybrid";
  vector_top_k?: number;
  bm25_top_k?: number;
  rrf_k?: number;
  rerank?: {
    enabled: boolean;
    top_n?: number;
  };
}

/** 检索命中条目 */
export interface RetrieveHit {
  chunk_id: string;
  kb_id: string;
  doc_id: string;
  score: number;
  text: string;
  title: string;
  metadata: Record<string, unknown>;
  vector_score?: number | null;
  bm25_score?: number | null;
  rerank_score?: number | null;
}

/** 检索元信息 */
export interface RetrieveMeta {
  total: number;
  latency_ms: number;
  mode: string;
  vector_count: number;
  bm25_count: number;
  fused_count: number;
  rerank_model: string | null;
  degraded: boolean;
  degraded_reason: string | null;
}

/** 检索响应 */
export interface RetrieveResponse {
  code: number;
  data: {
    hits: RetrieveHit[];
    meta: RetrieveMeta;
  };
}
