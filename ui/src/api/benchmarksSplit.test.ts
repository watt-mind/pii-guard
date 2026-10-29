import { gzipSync } from "node:zlib";
import { beforeAll, describe, expect, it } from "vitest";
import manifestModule from "virtual:pii-guard/benchmarks-manifest";
import type { BenchmarkIndex } from "./benchmarks";
import { fetchedBenchmarks } from "./benchmarks";
import { DETAIL_PART, joinIndex, RUNS_PART, setPart, splitIndex, SUMMARY_PART, type BenchmarkManifest } from "./benchmarksSplit";

// First import builds the index in Python (see benchmarks.test.ts, LAB-1435).
const INDEX_BUILD_TIMEOUT_MS = 60_000;
let full: BenchmarkIndex;
let raw: Record<string, unknown>;
const manifest = manifestModule as BenchmarkManifest;

beforeAll(async () => {
  raw = (await import("virtual:pii-guard/benchmarks-index")).default as Record<string, unknown>;
  full = raw as unknown as BenchmarkIndex;
}, INDEX_BUILD_TIMEOUT_MS);

/** The parts as the build serves them: file name to JSON text. */
function served(): Map<string, string> {
  const { parts } = splitIndex(raw);
  return new Map(Object.entries(parts).map(([name, value]) => [manifest.parts[name]!, JSON.stringify(value)]));
}

function source() {
  const files = served();
  const fetched: string[] = [];
  const get = (url: string) => {
    fetched.push(url);
    const json = files.get(url.slice("/".length));
    return json === undefined ? Promise.reject(new Error(`404 ${url}`)) : Promise.resolve(JSON.parse(json) as Record<string, unknown>);
  };
  return { src: fetchedBenchmarks(manifest, get, "/"), fetched };
}

describe("split benchmark index (LAB-1454)", () => {
  it("recombines to the original index, key for key and item for item", () => {
    const { layout, parts } = splitIndex(raw);
    expect(JSON.stringify(joinIndex(layout, parts))).toBe(JSON.stringify(raw));
    // History is by date, so its sets interleave: the order has to survive the round trip.
    expect(layout.order.history.length).toBeGreaterThan(layout.sets.length);
  });

  it("recombines from the served files, through the same fetch path as the screen", async () => {
    const { src } = source();
    expect(JSON.stringify(await src.full())).toBe(JSON.stringify(raw));
  });

  it("has a manifest from the Vite plugin that matches the split, with hashed file names", () => {
    const { layout, parts } = splitIndex(raw);
    const { parts: files, ...rest } = manifest;
    expect(rest).toEqual(layout);
    expect(Object.keys(files).sort()).toEqual(Object.keys(parts).sort());
    for (const file of Object.values(files)) expect(file).toMatch(/^assets\/benchmarks-[\w-]+-[\w-]{10}\.json$/);
    expect(new Set(Object.values(files)).size).toBe(Object.keys(files).length);
  });

  it("puts each set's snapshots and history in that set's part only", () => {
    const { layout, parts } = splitIndex(raw);
    for (const set of layout.sets) {
      const part = parts[setPart(set)] as unknown as Pick<BenchmarkIndex, "snapshots" | "history">;
      expect([...part.snapshots, ...part.history].every((x) => x.fixture_set === set)).toBe(true);
    }
    expect(Object.keys(parts[SUMMARY_PART]!)).not.toContain("snapshots");
    expect(Object.keys(parts[RUNS_PART]!)).toEqual(["runs"]);
    expect(Object.keys(parts[DETAIL_PART]!)).toContain("rows");
  });

  it("loads the summary and the headline set first, and no other set until it is picked", async () => {
    const { src, fetched } = source();
    const summary = await src.summary();
    expect(summary.runs).toEqual([]); // the run log comes on its own, already on its way
    expect((await src.runs!()).runs).toEqual(full.runs);
    expect(summary.systems).toEqual(full.systems);
    expect(summary.snapshots).toEqual([]);
    expect(fetched.sort()).toEqual([manifest.parts[SUMMARY_PART], manifest.parts[RUNS_PART], manifest.parts[setPart(full.headline_set!)]].map((f) => `/${f}`).sort());
    const head = await src.set(full.headline_set!);
    expect(head.snapshots).toEqual(full.snapshots.filter((s) => s.fixture_set === full.headline_set));
    expect(head.history).toEqual(full.history.filter((h) => h.fixture_set === full.headline_set));
    expect(fetched).toHaveLength(3); // summary, headline set, run log: the set was already on its way
    expect(await src.set("no-such-set")).toEqual({ snapshots: [], history: [] });
  });

  it("keeps the first Evaluation payload under 500 KB gzip", () => {
    const files = served();
    const first = [SUMMARY_PART, RUNS_PART, setPart(full.headline_set!)].map((n) => files.get(manifest.parts[n]!)!);
    const gz = first.reduce((n, json) => n + gzipSync(json).length, 0);
    expect(gz).toBeLessThan(500 * 1024);
  });
});

it("retries rejected summary, dataset and run-log parts while retaining successful reads", async () => {
  const files = served();
  const failed = new Set<string>();
  const calls: string[] = [];
  const src = fetchedBenchmarks(manifest, async (url) => {
    calls.push(url);
    if (!failed.has(url)) { failed.add(url); throw new Error("offline"); }
    return JSON.parse(files.get(url.slice(1))!) as Record<string, unknown>;
  }, "/");
  await expect(src.summary()).rejects.toThrow("offline");
  await expect(src.summary()).resolves.toHaveProperty("schema_version", 1);
  const other = manifest.sets.find((s) => s !== manifest.headline_set)!;
  await expect(src.set(other)).rejects.toThrow("offline");
  await expect(src.set(other)).resolves.toHaveProperty("snapshots");
  await expect(src.runs!()).rejects.toThrow("offline");
  await expect(src.runs!()).resolves.toHaveProperty("runs");
  const count = calls.length;
  await src.summary(); await src.set(other); await src.runs!();
  expect(calls).toHaveLength(count);
});
