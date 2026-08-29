// 后端 API 基础地址: 环境变量优先(打包/启动时设 NEXT_PUBLIC_API_BASE 可改端口), 默认本地后端
// 例(打包): set NEXT_PUBLIC_API_BASE=http://127.0.0.1:9999 后再 npm run build, 前端产物指向新端口
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000"