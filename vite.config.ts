// Vite builds the site (app/) into dist/. The Quarto class version (rendered into site/) is copied to dist/quarto/.
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = import.meta.dirname;

function copyQuarto(): Plugin {
  return {
    name: "copy-quarto-site",
    apply: "build",
    closeBundle() {
      const site = resolve(ROOT, "site");
      if (!existsSync(site)) throw new Error("site/ missing. Run `quarto render` first.");
      // Skip site/app: Quarto copies the raw app folder there. It is not part of the class site.
      const skip = resolve(site, "app");
      cpSync(site, resolve(ROOT, "dist/quarto"), { recursive: true, filter: (src) => !src.startsWith(skip) });
    },
  };
}

export default defineConfig({
  root: resolve(ROOT, "app"),
  base: "/",
  publicDir: "public",
  plugins: [react(), tailwindcss(), copyQuarto()],
  // The docs (musa*/docs/*.md) and figures live outside app/, so dev needs to read the repo root.
  server: { fs: { allow: [ROOT] } },
  build: { outDir: resolve(ROOT, "dist"), emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
});
