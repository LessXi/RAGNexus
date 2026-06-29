import axios from 'axios';

/** 创建 axios 实例，开发环境走 Vite proxy（baseURL=''），生产由构建注入 */
const api = axios.create({
  baseURL: '',
  timeout: 300_000,
  headers: { 'Content-Type': 'application/json' },
});

export default api;
