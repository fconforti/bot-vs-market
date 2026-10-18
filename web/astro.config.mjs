// @ts-check
import { defineConfig } from "astro/config";

// GitHub Pages project site: https://fconforti.github.io/bot-vs-market/
export default defineConfig({
  site: "https://fconforti.github.io",
  base: "/bot-vs-market",
  trailingSlash: "ignore",
  build: { format: "directory", assets: "_assets" },
  compressHTML: true,
});
