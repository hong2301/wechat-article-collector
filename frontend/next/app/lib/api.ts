// 后端 API 基础地址: 环境变量 NEXT_PUBLIC_API_BASE 优先; 否则按环境区分
//   dev(开发): http://127.0.0.1:8000 | 生产打包: http://127.0.0.1:8001
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE
  || (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "http://127.0.0.1:8001")
