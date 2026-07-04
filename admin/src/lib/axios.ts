import axios from 'axios';

/** 创建 axios 实例，开发环境走 Vite proxy（baseURL=''），生产由构建注入。
 *  不设置默认 Content-Type，让浏览器根据请求体自动设置
 * （JSON 请求自动 application/json，FormData 请求自动 multipart/form-data）。
 */
const api = axios.create({
 baseURL: '',
 timeout: 300_000,
});

// 请求拦截器：自动附加 API Key 鉴权
api.interceptors.request.use((config) => {
 const apiKey = import.meta.env.API_KEY;
 if (apiKey) {
  config.headers.Authorization = `Bearer ${apiKey}`;
 }
 return config;
});

// 响应拦截器：统一处理鉴权错误（业务 code 10200 = UNAUTHORIZED）
api.interceptors.response.use(
 (response) => {
  if (response.data?.code === 10200) {
   console.error('API Key 无效或未配置，请检查 admin/.env 中的 API_KEY');
   return Promise.reject(new Error('API Key 无效或未配置'));
  }
  return response;
 },
 (error) => {
  if (error.response?.status === 401 && error.response?.data?.code === 10200) {
   console.error('API Key 无效或未配置，请检查 admin/.env 中的 API_KEY');
  }
  return Promise.reject(error);
 },
);

export default api;
