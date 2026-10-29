/**
 * The benchmark index, cut into parts the Evaluation screen fetches as it needs them (LAB-1454).
 *
 * The whole index is about 7 MB of JSON, and most of it is detail for fixture sets nobody has
 * picked yet. The Vite plugin in `vite.config.ts` splits it with {@link splitIndex} and serves
 * each part as a hashed static JSON file; {@link joinIndex} puts the parts back together, key for
 * key and item for item, so a recombined index is the original one.
 *
 * - `summary`: every small top-level key (systems, fixture sets, featured, visual runs, ...).
 * - `runs`: the run log. The summary metrics, the headline and the run notes all read it.
 * - `set:<fixture set>`: that set's snapshots and history (per-language metrics included).
 * - `detail`: keys the screen never reads (per-fixture rows, stale snapshots, latency samples).
 *
 * This module has no browser or Node dependencies: the plugin and the screen share it.
 */

/** Lists sharded by `fixture_set`, one part per set. */
export const SHARDED_KEYS = ["snapshots", "history"] as const;
/** Keys with a part of their own. */
export const RUNS_KEYS = ["runs"] as const;
/** Keys the screen never reads: fetched only for the full index ({@link joinIndex}). */
export const DETAIL_KEYS = ["rows", "stale_snapshots", "latency"] as const;

export type ShardedKey = (typeof SHARDED_KEYS)[number];

export const SUMMARY_PART = "summary";
export const RUNS_PART = "runs";
export const DETAIL_PART = "detail";
const SET_PREFIX = "set:";

export function setPart(fixtureSet: string): string {
  return SET_PREFIX + fixtureSet;
}

/** What it takes to put the parts back together, besides the parts themselves. */
export interface SplitLayout {
  /** Top-level keys of the index, in order. */
  keys: string[];
  /** The headline fixture set: its part is fetched alongside the summary. */
  headline_set: string | null;
  /** Fixture sets with a part, in first-appearance order. */
  sets: string[];
  /**
   * The original order of each sharded list, run-length encoded as `[set, count]`: history is
   * by date, so sets interleave.
   */
  order: Record<ShardedKey, [string, number][]>;
}

/** `virtual:pii-guard/benchmarks-manifest`: the layout, and each part's file under the base URL. */
export interface BenchmarkManifest extends SplitLayout {
  parts: Record<string, string>;
}

export interface SplitIndex {
  layout: SplitLayout;
  /** Part name to its JSON value. */
  parts: Record<string, Record<string, unknown>>;
}

type Json = Record<string, unknown>;

function setOf(item: unknown): string {
  const set = (item as { fixture_set?: unknown } | null)?.fixture_set;
  if (typeof set !== "string") throw new Error("benchmark index: a sharded item has no fixture_set");
  return set;
}

export function splitIndex(index: Json): SplitIndex {
  const keys = Object.keys(index);
  const sharded = new Set<string>(SHARDED_KEYS);
  const runs = new Set<string>(RUNS_KEYS);
  const detail = new Set<string>(DETAIL_KEYS);
  const summary: Json = {};
  const runsPart: Json = {};
  const detailPart: Json = {};
  for (const k of keys) {
    if (sharded.has(k)) continue;
    (runs.has(k) ? runsPart : detail.has(k) ? detailPart : summary)[k] = index[k];
  }

  const sets: string[] = [];
  const bySet = new Map<string, Json>();
  const order = {} as SplitLayout["order"];
  for (const k of SHARDED_KEYS) {
    const items = index[k];
    order[k] = [];
    if (items === undefined) continue;
    if (!Array.isArray(items)) throw new Error(`benchmark index: ${k} is not a list`);
    for (const item of items) {
      const set = setOf(item);
      let part = bySet.get(set);
      if (!part) {
        part = {};
        bySet.set(set, part);
        sets.push(set);
      }
      ((part[k] ??= []) as unknown[]).push(item);
      const last = order[k].at(-1);
      if (last && last[0] === set) last[1] += 1;
      else order[k].push([set, 1]);
    }
  }

  const parts: SplitIndex["parts"] = { [SUMMARY_PART]: summary, [RUNS_PART]: runsPart, [DETAIL_PART]: detailPart };
  for (const set of sets) {
    const part = bySet.get(set)!;
    // Every sharded key in every set part, so a part always has the same shape.
    parts[setPart(set)] = Object.fromEntries(SHARDED_KEYS.map((k) => [k, part[k] ?? []]));
  }
  const head = index.headline_set;
  return { layout: { keys, headline_set: typeof head === "string" ? head : null, sets, order }, parts };
}

/** The original index from every part ({@link splitIndex} inverted). */
export function joinIndex(layout: SplitLayout, parts: Record<string, Json>): Json {
  const flat: Json = { ...parts[SUMMARY_PART], ...parts[RUNS_PART], ...parts[DETAIL_PART] };
  const cursor = new Map<string, number>();
  for (const k of SHARDED_KEYS) {
    if (!layout.keys.includes(k)) continue;
    cursor.clear();
    const out: unknown[] = [];
    for (const [set, count] of layout.order[k]) {
      const items = parts[setPart(set)]?.[k] as unknown[] | undefined;
      if (!items) throw new Error(`benchmark index: part ${setPart(set)} is missing`);
      const at = cursor.get(set) ?? 0;
      out.push(...items.slice(at, at + count));
      cursor.set(set, at + count);
    }
    flat[k] = out;
  }
  return Object.fromEntries(layout.keys.map((k) => [k, flat[k]]));
}
