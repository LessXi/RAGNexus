import type { CreateKBRequest, CreateKBResponse, TreeItem, TreeResponse, UploadDocResponse, RetrieveRequest, RetrieveResponse } from '@/types/api';
import api from '@/lib/axios';

/** 创建知识库 */
export async function createKB(params: CreateKBRequest): Promise<CreateKBResponse> {
  const { data } = await api.post<CreateKBResponse>(
    '/v1/knowledge-bases:create',
    { name: params.name },
  );
  return data;
}

/** 获取租户→知识库→文档三级树 */
export async function fetchTree(keyword?: string): Promise<TreeItem[]> {
  const { data } = await api.get<TreeResponse>(
    '/v1/knowledge-bases/tree',
    { params: keyword ? { keyword } : {} },
  );
  return data.data ?? [];
}


/** 上传文档（multipart form） */
export async function uploadDoc(
  kb_id: string,
  file: File,
): Promise<UploadDocResponse> {
  const form = new FormData();
  form.append('kb_id', kb_id);
  form.append('file', file);
  const { data } = await api.post<UploadDocResponse>(
    '/v1/documents:upload',
    form,
  );
  return data;
}

/** 执行检索 */
export async function retrieve(params: RetrieveRequest): Promise<RetrieveResponse> {
  const { data } = await api.post<RetrieveResponse>(
    '/v1/rag:retrieve',
    params,
  );
  return data;
}
