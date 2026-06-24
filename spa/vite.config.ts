import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "../agent_seal/server/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8081",
      "/health": "http://127.0.0.1:8081",
      "/ready": "http://127.0.0.1:8081",
      "/metrics": "http://127.0.0.1:8081",
    },
  },
});
