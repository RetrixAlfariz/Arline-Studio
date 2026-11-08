import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // Keep the browser's Host header: the runtime rejects writes whose Origin
    // differs from Host, and the string shorthand would rewrite Host to :7860.
    proxy: Object.fromEntries(
      ["/api", "/static", "/downloads", "/dataset-downloads"].map((path) => [path, { target: "http://127.0.0.1:7860", changeOrigin: false }]),
    )
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true
  }
});
