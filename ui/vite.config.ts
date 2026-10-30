/// <reference types="vitest/config" />
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { splitIndex, type BenchmarkManifest } from "./src/api/benchmarksSplit.ts";

const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));

// index.html reads %VITE_PII_GUARD_HOSTED% (the theme default); a local build sets it to "false".
process.env.VITE_PII_GUARD_HOSTED ??= "false";

/**
 * The benchmark index, built from the committed run records when the UI is built, served or
 * tested. It used to be committed as `src/api/benchmarks.index.json`, and every pair of pull
 * requests that added a run record conflicted on it (LAB-1269).
 *
 * The screen fetches it in parts (`src/api/benchmarksSplit.ts`, LAB-1454): each part is a
 * content-hashed static file, `assets/benchmarks-<part>-<hash>.json`, emitted into the build (and
 * served from memory by the dev server), and `virtual:pii-guard/benchmarks-manifest` maps part
 * names to those files. `virtual:pii-guard/benchmarks-index` is the whole index as one module,
 * for tests only: the app never imports it.
 *
 * The index is built by `pii-guard eval report --print-index`, with the repository's
 * `.venv` when there is one (`uv sync`), otherwise through `uv run`. `PII_GUARD_PYTHON` picks
 * another interpreter that has pii-guard installed. `PII_GUARD_BENCHMARKS_INDEX` names a
 * prebuilt index file to read instead, with no Python at all: the demo stack's Node container
 * mounts only `ui/` and gets the index from its `benchmarks-index` service (LAB-1356).
 */
function benchmarksIndex(): Plugin {
  const indexId = "virtual:pii-guard/benchmarks-index";
  const manifestId = "virtual:pii-guard/benchmarks-manifest";
  let cached: string | undefined;
  let split: { manifest: BenchmarkManifest; files: Map<string, string> } | undefined;
  let base = "/";
  let building = false;
  const prebuilt = process.env.PII_GUARD_BENCHMARKS_INDEX || undefined;
  const python = (): [string, string[]] => {
    const args = ["-m", "pii_guard.eval.report_cli", "--print-index"];
    if (process.env.PII_GUARD_PYTHON) return [process.env.PII_GUARD_PYTHON, args];
    const venv = join(REPO_ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (existsSync(venv)) return [venv, args];
    return ["uv", ["run", "--no-dev", "--project", REPO_ROOT, "python", ...args]];
  };
  const build = (): string => {
    const [cmd, args] = python();
    try {
      return execFileSync(cmd, args, { cwd: REPO_ROOT, encoding: "utf-8", maxBuffer: 256 * 1024 * 1024 });
    } catch (err) {
      throw new Error(
        `benchmark index: \`${cmd} ${args.join(" ")}\` failed. Run \`uv sync\` at the repository ` +
          "root (or set PII_GUARD_PYTHON).",
        { cause: err },
      );
    }
  };
  const indexText = (ctx: { addWatchFile: (f: string) => void }): string => {
    if (prebuilt) {
      ctx.addWatchFile(prebuilt);
      try {
        return readFileSync(prebuilt, "utf-8").trim();
      } catch (err) {
        throw new Error(`benchmark index: cannot read PII_GUARD_BENCHMARKS_INDEX (${prebuilt}).`, { cause: err });
      }
    }
    const runs = join(REPO_ROOT, "eval", "results", "runs");
    for (const name of readdirSync(runs)) if (name.endsWith(".json")) ctx.addWatchFile(join(runs, name));
    ctx.addWatchFile(join(REPO_ROOT, "docs", "benchmarks", "config.json"));
    ctx.addWatchFile(join(REPO_ROOT, "docs", "benchmarks", "colours.json"));
    cached ??= build().trim();
    return cached;
  };
  const splitParts = (text: string) => {
    if (split) return split;
    const { layout, parts } = splitIndex(JSON.parse(text) as Record<string, unknown>);
    const files = new Map<string, string>();
    const names: Record<string, string> = {};
    for (const [name, value] of Object.entries(parts)) {
      const json = JSON.stringify(value);
      const hash = createHash("sha256").update(json).digest("base64url").slice(0, 10);
      const slug = name.replace(/[^A-Za-z0-9_-]+/g, "-");
      const fileName = `assets/benchmarks-${slug}-${hash}.json`;
      files.set(fileName, json);
      names[name] = fileName;
    }
    split = { manifest: { ...layout, parts: names }, files };
    return split;
  };
  return {
    name: "pii-guard-benchmarks-index",
    configResolved(config) {
      base = config.base;
      building = config.command === "build";
    },
    resolveId: (source) => (source === indexId || source === manifestId ? "\0" + source : null),
    load(source) {
      if (source === "\0" + indexId) return `export default ${indexText(this)};`;
      if (source !== "\0" + manifestId) return null;
      const { manifest, files } = splitParts(indexText(this));
      if (building) for (const [fileName, json] of files) this.emitFile({ type: "asset", fileName, source: json });
      return `export default ${JSON.stringify(manifest)};`;
    },
    configureServer(server) {
      // The dev server has no build output: it answers the part files from memory.
      server.middlewares.use((req, res, next) => {
        const path = req.url?.split("?")[0] ?? "";
        const json = path.startsWith(base) ? split?.files.get(path.slice(base.length)) : undefined;
        if (json === undefined) return next();
        res.setHeader("Content-Type", "application/json");
        res.setHeader("Cache-Control", "no-cache");
        res.end(json);
      });
    },
    handleHotUpdate({ file }) {
      if (file.startsWith(join(REPO_ROOT, "eval")) || file.startsWith(join(REPO_ROOT, "docs"))) {
        cached = undefined;
        split = undefined;
      }
    },
  };
}

/**
 * `robots.txt`, written at build time: `VITE_PII_GUARD_ROBOTS=allow` lets crawlers index the
 * public landing (the production hosted build); anything else, the default, disallows all,
 * so dev and local builds stay out of search results (docs/hosted.md, "Build and configuration").
 * The hosted app does not serve this file: it answers `/robots.txt` per request host at runtime.
 */
function robots(): Plugin {
  return {
    name: "pii-guard-robots",
    apply: "build",
    generateBundle() {
      const allow = process.env.VITE_PII_GUARD_ROBOTS === "allow";
      this.emitFile({ type: "asset", fileName: "robots.txt", source: `User-agent: *\n${allow ? "Allow: /" : "Disallow: /"}\n` });
    },
  };
}

/**
 * Preload the two Latin Geist files (sans and mono) that the first screen uses. Without it the
 * page paints in the fallback font and reflows when Geist arrives, which Lighthouse counts as
 * layout shift on the landing (LAB-1466). The other subsets still load on demand.
 */
function preloadFonts(): Plugin {
  return {
    name: "pii-guard-preload-fonts",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const files = Object.keys(ctx.bundle ?? {}).filter((f) => /\/geist(-mono)?-latin-wght-normal-[^/]+\.woff2$/.test(f));
        return files.map((f) => ({ tag: "link", injectTo: "head", attrs: { rel: "preload", href: `/${f}`, as: "font", type: "font/woff2", crossorigin: "" } }));
      },
    },
  };
}

// The UI never talks to model providers. It only reaches the pii-guard API,
// through this proxy, so the browser stays same-origin.
const API_TARGET = process.env.PII_GUARD_API_URL ?? "http://127.0.0.1:8787";

const proxy = {
  // Preserve the browser-facing Host so cookie/origin checks see the same origin.
  "/v1": { target: API_TARGET, changeOrigin: false },
  "/e": { target: API_TARGET, changeOrigin: false },
  "/healthz": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), benchmarksIndex(), robots(), preloadFonts()],
  // ui/pnpm-workspace.yaml makes ui/ the workspace root; the #api page imports docs/openapi.json
  // from the repository root (LAB-1586).
  server: { port: 5173, strictPort: true, proxy, fs: { allow: [REPO_ROOT] } },
  preview: { port: 4173, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
