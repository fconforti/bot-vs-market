// @ts-check
import { defineConfig } from "astro/config";

// GitHub Pages project site: https://fconforti.github.io/finance/
export default defineConfig({
  site: "https://fconforti.github.io",
  base: "/finance",
  trailingSlash: "ignore",
  build: { format: "directory", assets: "_assets" },
  compressHTML: true,
});
