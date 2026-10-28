/// <reference types="vitest/config" />
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));

/**
 * `virtual:pii-guard/benchmarks-index`: the benchmark index, built from the committed run
 * records when the UI is built, served or tested. It used to be committed as
 * `src/api/benchmarks.index.json`, and every pair of pull requests that added a run record
 * conflicted on it (LAB-1269).
 *
 * The index is built by `pii-guard eval report --print-index`, with the repository's
 * `.venv` when there is one (`uv sync`), otherwise through `uv run`. `PII_GUARD_PYTHON` picks
 * another interpreter that has pii-guard installed. `PII_GUARD_BENCHMARKS_INDEX` names a
 * prebuilt index file to read instead, with no Python at all: the demo stack's Node container
 * mounts only `ui/` and gets the index from its `benchmarks-index` service (LAB-1356).
 */
function benchmarksIndex(): Plugin {
  const id = "virtual:pii-guard/benchmarks-index";
  const resolved = "\0" + id;
  let cached: string | undefined;
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
  return {
    name: "pii-guard-benchmarks-index",
    resolveId: (source) => (source === id ? resolved : null),
    load(source) {
      if (source !== resolved) return null;
      if (prebuilt) {
        this.addWatchFile(prebuilt);
        try {
          return `export default ${readFileSync(prebuilt, "utf-8").trim()};`;
        } catch (err) {
          throw new Error(`benchmark index: cannot read PII_GUARD_BENCHMARKS_INDEX (${prebuilt}).`, {
            cause: err,
          });
        }
      }
      const runs = join(REPO_ROOT, "eval", "results", "runs");
      for (const name of readdirSync(runs)) if (name.endsWith(".json")) this.addWatchFile(join(runs, name));
      this.addWatchFile(join(REPO_ROOT, "docs", "benchmarks", "config.json"));
      cached ??= build();
      return `export default ${cached.trim()};`;
    },
    handleHotUpdate({ file }) {
      if (file.startsWith(join(REPO_ROOT, "eval")) || file.startsWith(join(REPO_ROOT, "docs"))) cached = undefined;
    },
  };
}

// The UI never talks to model providers. It only reaches the pii-guard API,
// through this proxy, so the browser stays same-origin.
const API_TARGET = process.env.PII_GUARD_API_URL ?? "http://127.0.0.1:8787";

const proxy = {
  "/v1": { target: API_TARGET, changeOrigin: true },
  "/e": { target: API_TARGET, changeOrigin: true },
  "/healthz": { target: API_TARGET, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), benchmarksIndex()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 4173, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
