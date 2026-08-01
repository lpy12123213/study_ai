import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发代理目标可配置（默认本地后端），跨站联调时用 VITE_DEV_PROXY_TARGET 覆盖。
const proxyTarget = process.env.VITE_DEV_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 领域 chunk 拆分（架构 Phase 2）：路由 lazy 负责按页拆分，
        // 这里把大而稳定的第三方依赖拆为可长期缓存的 vendor chunk。
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router"],
          "vendor-query": ["@tanstack/react-query", "zustand"],
          "vendor-markdown": ["react-markdown", "remark-gfm", "remark-math", "rehype-katex", "katex"],
        },
      },
    },
  },
});
