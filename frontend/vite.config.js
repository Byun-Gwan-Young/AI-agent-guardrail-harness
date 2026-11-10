import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_PROXY_TARGET || "http://127.0.0.1:8040";
  const proxy = {
    "/api": { target, changeOrigin: true },
    "/legacy-login": {
      target,
      changeOrigin: true,
      rewrite: (p) => p.replace(/^\/legacy-login/, "/login"),
    },
  };
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy,
      watch: {
        ignored: [
          "**/.local-logs/**",
          "**/test-results/**",
          "**/playwright-report/**",
        ],
      },
    },
    preview: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  };
});
