import http from '../lib/axios';
import type { AuthMeData } from '../types/api';

export async function fetchAuthMe(): Promise<AuthMeData> {
  const response = await http.get('/v1/auth/me');
  return response.data;
}
