import http from '../lib/axios';
import type { RetrieveRequest, RetrieveResponse } from '../types/api';

/** 执行检索请求 */
export async function retrieve(params: RetrieveRequest): Promise<RetrieveResponse> {
  const { data } = await http.post<RetrieveResponse>('/v1/rag:retrieve', params);
  return data;
}
