"use client";
import { useRouter } from "next/navigation";

// 统一页面跳转(解决 dev http 与打包 file:// 的路由差异):
//   - dev(http://localhost): Next 客户端路由 router.push("/articles?.."), dev server 有该路由
//   - 打包(file://): 静态导出文件相对跳转 "articles.html?..", 由 electron main.js 重写加载
export function useNav() {
  const router = useRouter();
  return (p: string) => {
    if (window.location.protocol.startsWith("http")) {
      router.push(p);
      return;
    }
    // file:// 下相对跳转(与 out/ 同目录)
    let href: string;
    if (p === "/") {
      href = "index.html";
    } else {
      const [path, q] = p.split("?");
      href = path.slice(1) + ".html" + (q ? "?" + q : "");
    }
    window.location.href = href;
  };
}