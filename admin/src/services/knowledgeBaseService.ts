import api from '@/lib/axios';
import type { KBDetail, UpdateKBRequest } from '@/types/api';

/** 获取知识库详情 */
export async function fetchKBDetail(kbId: string): Promise<KBDetail> {
  const res = await api.get(`/v1/knowledge-bases/${kbId}`);
  return res.data.data;
}

/** 更新知识库 */
export async function updateKB(
  kbId: string,
  data: UpdateKBRequest,
): Promise<KBDetail> {
  const res = await api.patch(`/v1/knowledge-bases/${kbId}`, data);
  return res.data.data;
}

/** 删除知识库 */
export async function deleteKB(kbId: string): Promise<void> {
  const res = await api.delete(`/v1/knowledge-bases/${kbId}`);
  return res.data;
}
