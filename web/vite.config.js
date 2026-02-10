import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  root: ".",
  publicDir: resolve(__dirname, ".."),
  envDir: resolve(__dirname, ".."),
  server: {
    port: 3000,
    open: false,
  },
});
