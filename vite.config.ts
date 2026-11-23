// Vite builds the site (app/) into dist/. The Quarto class version (rendered into site/) is copied to dist/quarto/.
import { defineConfig } from "vitest/config";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cpSync, createReadStream, existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";

import { lotDataDir } from "./app/devData";
import { resolve, sep } from "node:path";

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

/** `virtual:lot-index`: which tracts have lot files (public/data/lots), so the tool never asks for a missing file. */
function lotIndex(): Plugin {
  const id = "virtual:lot-index";
  const list = (dir: string, ext: string) => {
    const d = resolve(ROOT, "app/public/data", dir);
    return existsSync(d) ? readdirSync(d).filter((f) => f.endsWith(ext)).map((f) => f.slice(0, -ext.length)) : [];
  };
  return {
    name: "lot-index",
    resolveId: (s) => (s === id ? "\0" + id : null),
    load: (s) => (s === "\0" + id ? `export const LOT_TRACTS = ${JSON.stringify(list("lots", ".json"))};` : null),
  };
}

/**
 * In `vite dev`, a JSON file imported on demand with `{ with: { type: "json" } }` (the rule files in
 * app/src/agent/ruleText.ts; the Ask server function on Vercel needs that attribute) reaches the browser already turned
 * into JavaScript, and the browser refuses it as not JSON. The attribute is dropped from browser code in dev only. The
 * production build bundles these files and is not changed.
 */
function devJsonImports(): Plugin {
  const RE = /import\((['"][^'"]+\.json['"])\s*,\s*\{\s*with:\s*\{\s*type:\s*['"]json['"]\s*\}\s*\}\s*\)/g;
  return {
    name: "dev-json-imports",
    apply: "serve",
    enforce: "pre",
    transform(code, id, opts) {
      if (opts?.ssr || !/\.[jt]sx?$/.test(id.split("?")[0]) || !code.includes("type: 'json'") && !code.includes('type: "json"')) return null;
      const out = code.replace(RE, "import($1)");
      return out === code ? null : { code: out, map: null };
    },
  };
}

/**
 * In `vite dev`, serve api/agent.ts the way Vercel does. Keys come from the repo-root .env (never the bundle).
 * With no key there, or a key the API turns down, the question goes to the live site's Ask function instead
 * (ASK_FALLBACK_URL, default https://pa-adu.vercel.app/api/agent), so ParcelIQ works on localhost without a key.
 * ASK_LIVE=1 always uses the live function.
 */
const ASK_FALLBACK_URL = process.env.ASK_FALLBACK_URL ?? "https://pa-adu.vercel.app/api/agent";
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
      let live = process.env.ASK_LIVE === "1" || !process.env.ANTHROPIC_API_KEY;
      const viaLive = async (text: string, res: ServerResponse) => {
        const r = await fetch(ASK_FALLBACK_URL, { method: "POST", headers: { "content-type": "application/json" }, body: text });
        res.statusCode = r.status;
        res.setHeader("content-type", r.headers.get("content-type") ?? "application/json");
        res.end(await r.text());
      };
      server.middlewares.use("/api/agent", async (req, res) => {
        const chunks: Buffer[] = [];
        for await (const c of req) chunks.push(c as Buffer);
        const text = Buffer.concat(chunks).toString("utf8");
        if (live) return viaLive(text, res).catch(() => ((res.statusCode = 502), res.end(JSON.stringify({ type: "error", error: "upstream", message: "The live Ask function did not answer." }))));
        const mod = await server.ssrLoadModule(resolve(ROOT, "api/agent.ts"));
        // The local answer is held until it is known to be good: a missing or refused key switches to the live one.
        let code = 200;
        let body: unknown = null;
        const shim = {
          status(c: number) {
            code = c;
            return shim;
          },
          json(b: unknown) {
            body = b;
          },
          setHeader: (k: string, v: string) => res.setHeader(k, v),
        };
        await mod.default({ method: req.method, body: text ? JSON.parse(text) : null, headers: req.headers, socket: req.socket }, shim);
        const err = (body as { type?: string; error?: string } | null)?.type === "error" ? (body as { error?: string }).error : null;
        if (err === "not_configured" || err === "upstream") {
          live = true;
          server.config.logger.info(`Ask: the local key did not work (${err}). Using the live Ask function from now on.`);
          return viaLive(text, res);
        }
        res.statusCode = code;
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify(body));
      });
    },
  };
}

/**
 * In `vite dev`, serve the lot records (built outside the repo) at /data/lots2/, the default VITE_LOT_DATA_URL.
 * The folder is LOT_DATA_DIR, else the data drive (~/musa-drive/lots), else the laptop copy of the public data
 * repository (app/devData.ts). Byte ranges are supported for the parcel PMTiles.
 * .json.gz files go out as plain bytes: the browser decodes them (app/src/lib/lot/load.ts).
 */
function devLotData(): Plugin {
  const MOUNT = "/data/lots2/";
  const TYPES: Record<string, string> = { ".json": "application/json", ".gz": "application/octet-stream", ".pmtiles": "application/octet-stream" };
  const root = lotDataDir();
  console.log(`lot records: ${root}`);
  const serve = (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = decodeURIComponent((req.url ?? "").split("?")[0]);
    if (!url.startsWith(MOUNT)) return next();
    const file = resolve(root, url.slice(MOUNT.length));
    if (!file.startsWith(root + sep) || !existsSync(file) || !statSync(file).isFile()) {
      res.statusCode = 404;
      return res.end("not found");
    }
    const size = statSync(file).size;
    const ext = Object.keys(TYPES).find((e) => file.endsWith(e));
    res.setHeader("content-type", ext ? TYPES[ext] : "application/octet-stream");
    res.setHeader("accept-ranges", "bytes");
    res.setHeader("cache-control", "no-cache");
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
    if (m) {
      const start = m[1] ? Number(m[1]) : Math.max(0, size - Number(m[2]));
      const end = m[1] && m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
      if (start >= size || start > end) {
        res.statusCode = 416;
        res.setHeader("content-range", `bytes */${size}`);
        return res.end();
      }
      res.statusCode = 206;
      res.setHeader("content-range", `bytes ${start}-${end}/${size}`);
      res.setHeader("content-length", String(end - start + 1));
      return createReadStream(file, { start, end }).pipe(res);
    }
    res.setHeader("content-length", String(size));
    createReadStream(file).pipe(res);
  };
  return {
    name: "dev-lot-data",
    configureServer(server) {
      server.middlewares.use(serve);
    },
    // `vite preview` too, so the production build can be checked against the same lot files.
    configurePreviewServer(server) {
      server.middlewares.use(serve);
    },
  };
}

export default defineConfig({
  root: resolve(ROOT, "app"),
  base: "/",
  publicDir: "public",
  plugins: [react(), tailwindcss(), lotIndex(), devLotData(), devApi(), devJsonImports(), copyQuarto()],
  // The docs (musa*/docs/*.md) and figures live outside app/, so dev needs to read the repo root.
  server: { fs: { allow: [ROOT] } },
  build: { outDir: resolve(ROOT, "dist"), emptyOutDir: true, target: "es2022", chunkSizeWarningLimit: 1500 },
  // Unit tests live next to the code (app/src, api). `npm run eval:agent` adds the live agent eval (needs a key).
  test: {
    root: ROOT,
    environment: "node",
    include: ["app/src/**/*.test.ts", "api/**/*.test.ts", "agent/**/*.test.ts", ...(process.env.EVAL ? ["agent/**/*.eval.ts"] : [])],
    testTimeout: 30_000,
  },
});
