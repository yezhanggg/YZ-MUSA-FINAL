// Vite builds the tool (app/) into dist/app/.
// The Quarto pages (rendered locally into site/) are copied into dist/ as they are.
import { defineConfig } from "vite";
import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = import.meta.dirname;

export default defineConfig({
  root: resolve(ROOT, "app"),
  base: "/app/",
  publicDir: "public",
  worker: { format: "es" },
  build: { outDir: resolve(ROOT, "dist/app"), emptyOutDir: true },
  plugins: [{
    name: "copy-quarto-site",
    apply: "build",
    closeBundle() {
      const site = resolve(ROOT, "site");
      if (!existsSync(site)) throw new Error("site/ missing. Run `quarto render` first.");
      // Skip site/app: Quarto copies the raw tool page there. Vite's build of it is in dist/app.
      const skip = resolve(site, "app");
      cpSync(site, resolve(ROOT, "dist"), { recursive: true, filter: (src) => !src.startsWith(skip) });
    },
  }],
});
