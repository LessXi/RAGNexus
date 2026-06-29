import type { CreateKBResponse, UploadDocResponse } from '@/types/api';
import api from '@/lib/axios';

/** 创建知识库 */
export async function createKB(name: string): Promise<CreateKBResponse> {
  const { data } = await api.post<CreateKBResponse>(
    '/v1/knowledge-bases:create',
    { name },
  );
  return data;
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
