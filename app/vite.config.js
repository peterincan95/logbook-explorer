import { defineConfig } from "vite";

// Relative base so the built site works from a GitHub Pages project path
// (https://<user>.github.io/<repo>/) without knowing the repo name.
export default defineConfig({
  base: "./",
  build: { outDir: "dist", chunkSizeWarningLimit: 4000 },
  server: { port: 5176, strictPort: true },
});
