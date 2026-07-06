/** API 请求/响应类型定义 */

/** 创建知识库请求 */
export interface CreateKBRequest {
  name: string;
  description?: string;
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

/** 上传文档请求 */
export interface UploadDocRequest {
  kb_id: string;
  file: File;
}

/** 上传文档响应 */
export interface UploadDocResponse {
  code: number;
  data: {
    doc_id: string;
    kb_id: string;
    status: string;
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
  doc_id?: string; // 异步索引时用于轮询状态
  name: string;
  size: number;
  status: 'success' | 'failed' | 'processing';
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
  /** 查询改写配置 */
  query_options?: {
    enabled: boolean;
    strategy: string;
  };
  /** 检索简档：speed/balanced/quality 为预设模式，custom 为自定义 */
  profile?: "speed" | "balanced" | "quality" | "custom";
  /** 禁止显式传入 tenant_id */
  tenant_id?: never;
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
  /** 查询处理详情 */
  query_processing?: {
    raw_query: string;
    effective_query: string;
    search_query: string;
    needs_rewrite: boolean;
    strategy: string;
    rewrite_latency_ms: number;
    degraded: boolean;
    degraded_reason: string | null;
    synonym_applied: boolean;
    synonym_expansions: string[];
  } | null;
}

/** 检索响应 */
export interface RetrieveResponse {
  code: number;
  data: {
    hits: RetrieveHit[];
    meta: RetrieveMeta;
  };
  metadata: {
    log_id?: string;
    trace_id?: string;
  };
}

/** /auth/me 响应 */
export interface AuthMeData {
  tenant_id: string;
  tenant_name: string;
  key_id: string;
  key_prefix: string;
  plan: string;
  features: {
    allowed_profiles: string[];
    hybrid_allowed: boolean;
    rerank_allowed: boolean;
    query_rewrite_allowed: boolean;
  };
  limits: {
    retrieve_qps: number;
    retrieve_daily: number;
    max_kb: number;
    max_documents_per_kb: number;
    max_processing_documents: number;
  };
  usage: {
    kb_count: number;
    retrieve_daily_count: number;
  };
}

/** 文档索引状态枚举 */
export enum DocStatus {
  SUCCESS = 'success',
  PROCESSING = 'processing',
  FAILED = 'failed',
}

/** 文档详情 */
export interface DocumentDetail {
  doc_id: string;
  kb_id: string;
  filename: string;
  file_hash: string;
  file_size: number;
  content_type: string;
  status: string;
  chunk_count: number;
  error_message?: string | null;
  uploaded_at: string | null;
  updated_at: string | null;
}

/** 更新知识库请求 */
export interface UpdateKBRequest {
  name?: string;
  description?: string;
  settings?: Record<string, unknown>;
}

/** 知识库详情 */
export interface KBDetail {
  id: string;
  name: string;
  description: string;
  settings: Record<string, unknown>;
  tenant_id: string;
  created_at: string;
}

/** 上传结果（异步索引版） */
export interface UploadResult {
  doc_id: string;
  kb_id: string;
  status: string;
  chunk_count: number;
}

/** 反馈提交请求 */
export interface FeedbackRequest {
  trace_id: string;
  log_id?: string;
  score: number; // 1-5
  comment?: string;
}

/** 反馈数据 */
export interface FeedbackData {
  feedback_id: string;
  trace_id: string;
  log_id?: string;
  score: number;
}
