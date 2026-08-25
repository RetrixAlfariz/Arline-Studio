import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:7860",
      "/static": "http://127.0.0.1:7860",
      "/downloads": "http://127.0.0.1:7860",
      "/dataset-downloads": "http://127.0.0.1:7860"
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true
  }
});
