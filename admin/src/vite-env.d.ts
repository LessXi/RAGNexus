/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 鉴权密钥，用于 Bearer Token 认证 */
  readonly API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
