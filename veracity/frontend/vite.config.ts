import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    // Proxied rather than called cross-origin: the browser then sends no
    // preflight, and the deployed build can sit behind the same origin as the
    // API without a second configuration.
    proxy: { "/api": "http://127.0.0.1:8080", "/health": "http://127.0.0.1:8080" },
  },
});
