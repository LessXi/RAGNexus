import http from '../lib/axios';
import type { RetrieveRequest, RetrieveResponse, FeedbackRequest, FeedbackData } from '../types/api';

/** 执行检索请求 */
export async function retrieve(params: RetrieveRequest): Promise<RetrieveResponse> {
  const { data } = await http.post<RetrieveResponse>('/v1/rag:retrieve', params);
  return data;
}

/** 提交检索反馈 */
export async function submitFeedback(params: FeedbackRequest): Promise<FeedbackData> {
  const { data } = await http.post<FeedbackData>('/v1/rag/feedback', params);
  return data;
}
