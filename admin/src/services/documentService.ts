import api from '@/lib/axios';
import type { DocumentDetail } from '@/types/api';

/** 删除文档 */
export async function deleteDocument(docId: string): Promise<void> {
  const res = await api.delete(`/v1/documents/${docId}`);
  return res.data;
}

/** 重新索引文档 */
export async function reindexDocument(
  docId: string,
): Promise<{ doc_id: string; status: string }> {
  const res = await api.post(`/v1/documents/${docId}/reindex`);
  return res.data.data;
}

/** 获取单个文档详情 */
export async function fetchDocument(docId: string): Promise<DocumentDetail> {
  const res = await api.get(`/v1/documents/${docId}`);
  return res.data.data;
}
