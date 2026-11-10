// Vite builds the site (app/) into dist/. The Quarto class version (rendered into site/) is copied to dist/quarto/.
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cpSync, existsSync, readdirSync } from "node:fs";
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

/** `virtual:lot-index`: which tracts have lot files (public/data/lots, public/data/lot_shapes), so the tool never asks for a missing file. */
function lotIndex(): Plugin {
  const id = "virtual:lot-index";
  const list = (dir: string, ext: string) => {
    const d = resolve(ROOT, "app/public/data", dir);
    return existsSync(d) ? readdirSync(d).filter((f) => f.endsWith(ext)).map((f) => f.slice(0, -ext.length)) : [];
  };
  return {
    name: "lot-index",
    resolveId: (s) => (s === id ? "\0" + id : null),
    load: (s) =>
      s === "\0" + id ? `export const LOT_TRACTS = ${JSON.stringify(list("lots", ".json"))};\nexport const SHAPE_TRACTS = ${JSON.stringify(list("lot_shapes", ".geojson"))};\nexport const HAS_FIT_CURVES = ${existsSync(resolve(ROOT, "app/public/data/fit_curves.json"))};` : null,
  };
}

export default defineConfig({
  root: resolve(ROOT, "app"),
  base: "/",
  publicDir: "public",
  plugins: [react(), tailwindcss(), lotIndex(), copyQuarto()],
  // The docs (musa*/docs/*.md) and figures live outside app/, so dev needs to read the repo root.
  server: { fs: { allow: [ROOT] } },
  build: { outDir: resolve(ROOT, "dist"), emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
});
