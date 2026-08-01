/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API origin 前缀：默认空串（同源反代）；跨站部署时设为绝对 origin，如 https://api.example.com。 */
  readonly VITE_API_BASE_URL?: string;
}
