import axios from 'axios';

/** 创建 axios 实例，开发环境走 Vite proxy（baseURL=''），生产由构建注入。
 *  不设置默认 Content-Type，让浏览器根据请求体自动设置
 * （JSON 请求自动 application/json，FormData 请求自动 multipart/form-data）。
 */
const api = axios.create({
 baseURL: '',
 timeout: 300_000,
});

export default api;
