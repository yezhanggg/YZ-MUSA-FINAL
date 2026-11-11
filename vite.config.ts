// Vite builds the site (app/) into dist/. The Quarto class version (rendered into site/) is copied to dist/quarto/.
import { defineConfig } from "vitest/config";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cpSync, existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = import.meta.dirname;

function copyQuarto(): Plugin {
  let outDir = resolve(ROOT, "dist");
  return {
    name: "copy-quarto-site",
    apply: "build",
    configResolved(c) {
      outDir = c.build.outDir;
    },
    closeBundle() {
      const site = resolve(ROOT, "site");
      if (!existsSync(site)) throw new Error("site/ missing. Run `quarto render` first.");
      // Skip site/app: Quarto copies the raw app folder there. It is not part of the class site.
      const skip = resolve(site, "app");
      // Also skip sync-conflict copies ("site_libs 2", "index 2.html") that cloud folders can leave behind.
      const dupe = /\/[^/]+ [2-9](\.[^/.]+)?$/;
      cpSync(site, resolve(outDir, "quarto"), { recursive: true, filter: (src) => !src.startsWith(skip) && !dupe.test(src) });
    },
  };
}

/** `virtual:lot-index`: which tracts have lot files (public/data/lots), and if fit_curves.json exists, so the tool never asks for a missing file. */
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
      s === "\0" + id ? `export const LOT_TRACTS = ${JSON.stringify(list("lots", ".json"))};\nexport const HAS_FIT_CURVES = ${existsSync(resolve(ROOT, "app/public/data/fit_curves.json"))};\nexport const HAS_LOT_DETAIL = ${existsSync(resolve(ROOT, "app/public/data/lot_detail.pmtiles"))};` : null,
  };
}

/** In `vite dev`, serve api/agent.ts the way Vercel does. Keys come from the repo-root .env (never the bundle). */
function devApi(): Plugin {
  return {
    name: "dev-api",
    apply: "serve",
    configureServer(server) {
      const env = resolve(ROOT, ".env");
      if (existsSync(env)) {
        for (const line of readFileSync(env, "utf8").split("\n")) {
          const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
          if (m && m[2] && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
        }
      }
      server.middlewares.use("/api/agent", async (req, res) => {
        const chunks: Buffer[] = [];
        for await (const c of req) chunks.push(c as Buffer);
        const mod = await server.ssrLoadModule(resolve(ROOT, "api/agent.ts"));
        const text = Buffer.concat(chunks).toString("utf8");
        const shim = {
          status(code: number) {
            res.statusCode = code;
            return shim;
          },
          json(b: unknown) {
            res.setHeader("content-type", "application/json");
            res.end(JSON.stringify(b));
          },
          setHeader: (k: string, v: string) => res.setHeader(k, v),
        };
        await mod.default({ method: req.method, body: text ? JSON.parse(text) : null, headers: req.headers, socket: req.socket }, shim);
      });
    },
  };
}

export default defineConfig({
  root: resolve(ROOT, "app"),
  base: "/",
  publicDir: "public",
  plugins: [react(), tailwindcss(), lotIndex(), devApi(), copyQuarto()],
  // The docs (musa*/docs/*.md) and figures live outside app/, so dev needs to read the repo root.
  server: { fs: { allow: [ROOT] } },
  build: { outDir: resolve(ROOT, "dist"), emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
  // Unit tests live next to the code (app/src, api). `npm run eval:agent` adds the live agent eval (needs a key).
  test: {
    root: ROOT,
    environment: "node",
    include: ["app/src/**/*.test.ts", "api/**/*.test.ts", ...(process.env.EVAL ? ["agent/**/*.eval.ts"] : [])],
    testTimeout: 30_000,
  },
});
