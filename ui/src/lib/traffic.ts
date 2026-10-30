// Pure helpers for the Live traffic screen: the timing waterfall, rolling latency stats,
// entity counts and reading the request / response payloads of a traffic event.

import type { EntityType } from "../api/types";
import type { TrafficEvent, TrafficTiming } from "../api/traffic";
import { detectorLabel } from "./entities";
import { alignLoose, isEntityType, type RestoredSegment } from "./placeholders";
import { clockTime } from "./time";

// --- Waterfall ----------------------------------------------------------------------------

/** pii-guard's own stages, in pipeline order (timing.py OWN_STAGES). */
export const OWN_STAGES = ["parse", "detect", "image", "mask", "forward", "unmask", "response"] as const;
export type OwnStage = (typeof OWN_STAGES)[number];

export const STAGE_LABEL: Record<OwnStage | "upstream" | "other", string> = {
  parse: "Parse",
  detect: "Detect",
  image: "Image",
  mask: "Mask",
  forward: "Forward",
  unmask: "Restore stream",
  response: "Restore",
  upstream: "Model",
  other: "Other",
};

export const STAGE_HINT: Record<OwnStage | "upstream" | "other", string> = {
  parse: "JSON, collecting texts and images, request checks",
  detect: "every detector on every text, then known values (wall time)",
  image: "the visual pipeline for inline images",
  mask: "replacing values with placeholders in the vault",
  forward: "serializing the masked body and opening the HTTP connection to the model (PII Guard's side)",
  unmask: "restoring the stream, summed over its chunks",
  response: "restoring a non-streamed answer and building the response",
  upstream: "waiting on the model: headers and body (not PII Guard's time)",
  other: "inside the timer but outside any stage (scheduling, framing)",
};

export interface WaterfallRow {
  key: OwnStage | "upstream" | "other";
  label: string;
  /** ms from the start of the request. */
  start: number;
  ms: number;
  /** pii-guard's work (counts toward the overhead) or time spent waiting on the model. */
  kind: "own" | "upstream" | "other";
  /** Upstream only: the part until the response headers arrived. */
  ttfbMs?: number;
}

export interface Waterfall {
  rows: WaterfallRow[];
  total: number;
  upstream: number;
  overhead: number;
  /** Sum of the own stages; `own + other === overhead` (up to rounding in the payload). */
  own: number;
  other: number;
  /** Streams: when the first event reached the client, and what pii-guard added to it. */
  ttft: number | null;
  addedTtft: number | null;
  /** The axis length: the total, or the stage sum if rounding put it a hair over. */
  span: number;
}

const round3 = (v: number) => Math.round(v * 1000) / 1000;

/**
 * Lay the stages of one event end to end, in pipeline order. Stages that didn't run (0 ms)
 * are left out. The numbers are the event's own: every row's `ms` is a `stages_ms` value,
 * `total`, `upstream` and `overhead` are copied from the payload, and `other` is what the
 * stages don't account for of the overhead. On a stream, unmasking happens between upstream
 * reads; the waterfall shows its summed time after the upstream bar.
 */
export function waterfall(t: TrafficTiming): Waterfall {
  const s = t.stages_ms;
  const rows: WaterfallRow[] = [];
  let at = 0;
  const push = (key: WaterfallRow["key"], ms: number, kind: WaterfallRow["kind"], extra: Partial<WaterfallRow> = {}) => {
    if (!(ms > 0)) return;
    rows.push({ key, label: STAGE_LABEL[key], start: round3(at), ms, kind, ...extra });
    at += ms;
  };
  for (const stage of ["parse", "detect", "image", "mask", "forward"] as const) push(stage, s[stage] ?? 0, "own");
  push("upstream", t.upstream_ms, "upstream", { ttfbMs: s.upstream_ttfb ?? 0 });
  for (const stage of ["unmask", "response"] as const) push(stage, s[stage] ?? 0, "own");
  const own = round3(OWN_STAGES.reduce((sum, k) => sum + (s[k] ?? 0), 0));
  const other = round3(Math.max(t.overhead_ms - own, 0));
  push("other", other, "other");
  return {
    rows,
    total: t.total_ms,
    upstream: t.upstream_ms,
    overhead: t.overhead_ms,
    own,
    other,
    ttft: t.ttft_ms,
    addedTtft: t.added_ttft_ms,
    span: Math.max(t.total_ms, round3(at)),
  };
}

// --- Stats --------------------------------------------------------------------------------

/** Linear-interpolated percentile (numpy's default), `p` in 0..100. */
export function percentile(values: readonly number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (rank - lo);
}

export interface RollingPoint {
  id: string;
  index: number;
  overhead: number;
  p50: number;
  p95: number;
}

/** Each event's overhead with the p50 / p95 of the last `window` events up to it. */
export function rollingOverhead(events: readonly TrafficEvent[], window = 20): RollingPoint[] {
  return events.map((e, i) => {
    const slice = events.slice(Math.max(0, i - window + 1), i + 1).map((x) => x.timing.overhead_ms);
    return { id: e.id, index: i, overhead: e.timing.overhead_ms, p50: percentile(slice, 50)!, p95: percentile(slice, 95)! };
  });
}

export interface ModeStats {
  mode: string;
  n: number;
  p50: number;
  p95: number;
  max: number;
}

const MODE_ORDER = ["fast", "audit"];

/** Modes in display order: fast (the default), audit, then any other name alphabetically. */
export function modeOrder(modes: readonly string[]): string[] {
  return [...modes].sort((a, b) => (MODE_ORDER.indexOf(a) + 1 || 9) - (MODE_ORDER.indexOf(b) + 1 || 9) || a.localeCompare(b));
}

export function overheadByMode(events: readonly TrafficEvent[]): ModeStats[] {
  const by = new Map<string, number[]>();
  for (const e of events) {
    const m = e.mode ?? "unknown";
    by.set(m, [...(by.get(m) ?? []), e.timing.overhead_ms]);
  }
  return modeOrder([...by.keys()])
    .map((mode) => [mode, by.get(mode)!] as const)
    .map(([mode, v]) => ({ mode, n: v.length, p50: percentile(v, 50)!, p95: percentile(v, 95)!, max: Math.max(...v) }));
}

/** Values masked per type: text entities plus image regions. */
export function maskedCounts(e: TrafficEvent): Partial<Record<EntityType, number>> {
  const out: Partial<Record<EntityType, number>> = {};
  const add = (counts: Partial<Record<EntityType, number>> | undefined) => {
    for (const [k, v] of Object.entries(counts ?? {})) if (isEntityType(k) && v) out[k] = (out[k] ?? 0) + v;
  };
  add(e.entities?.masked);
  add(e.entities?.images?.masked);
  return out;
}

export const totalMasked = (e: TrafficEvent) => Object.values(maskedCounts(e)).reduce((a, b) => a + (b ?? 0), 0);

export interface MinuteBucket {
  /** Start of the minute, ms since the epoch. */
  minute: number;
  counts: Partial<Record<EntityType, number>>;
  total: number;
}

/** Masked values per minute and type, for the last `minutes` minutes up to `now` (empty minutes included). */
export function entitiesPerMinute(events: readonly TrafficEvent[], now: number, minutes = 10): MinuteBucket[] {
  const end = Math.floor(now / 60_000) * 60_000;
  const buckets: MinuteBucket[] = Array.from({ length: minutes }, (_, i) => ({ minute: end - (minutes - 1 - i) * 60_000, counts: {}, total: 0 }));
  for (const e of events) {
    const t = Date.parse(e.time);
    if (!Number.isFinite(t)) continue;
    const b = buckets.find((x) => t >= x.minute && t < x.minute + 60_000);
    if (!b) continue;
    for (const [k, v] of Object.entries(maskedCounts(e)) as [EntityType, number][]) {
      b.counts[k] = (b.counts[k] ?? 0) + v;
      b.total += v;
    }
  }
  return buckets;
}

// --- Payloads -----------------------------------------------------------------------------

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export type Part = { kind: "text"; text: string } | { kind: "image"; summary: string };

export interface ToolCall {
  name: string;
  arguments: string;
}

export interface Message {
  role: string;
  parts: Part[];
  toolCalls: ToolCall[];
}

function toolCallsOf(v: unknown): ToolCall[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((c) => {
    if (!isRecord(c) || !isRecord(c.function)) return [];
    const args = c.function.arguments;
    return [{ name: String(c.function.name ?? "tool"), arguments: typeof args === "string" ? args : JSON.stringify(args ?? {}) }];
  });
}

function partsOf(content: unknown): Part[] {
  if (typeof content === "string") return [{ kind: "text", text: content }];
  if (!Array.isArray(content)) return [];
  return content.flatMap((p): Part[] => {
    if (!isRecord(p)) return [];
    if (p.type === "text" && typeof p.text === "string") return [{ kind: "text", text: p.text }];
    if (p.type === "image_url") {
      const url = isRecord(p.image_url) ? p.image_url.url : p.image_url;
      return [{ kind: "image", summary: typeof url === "string" ? url : "[image]" }];
    }
    return [];
  });
}

/** The messages of a chat request body (masked or original). */
export function requestMessages(body: unknown): Message[] {
  if (!isRecord(body) || !Array.isArray(body.messages)) return [];
  return body.messages.flatMap((m) =>
    isRecord(m) ? [{ role: typeof m.role === "string" ? m.role : "user", parts: partsOf(m.content), toolCalls: toolCallsOf(m.tool_calls) }] : [],
  );
}

export interface ToolDef {
  name: string;
  /** The definition as JSON text: descriptions and parameter docs are masked like messages. */
  json: string;
}

export function requestTools(body: unknown): ToolDef[] {
  if (!isRecord(body) || !Array.isArray(body.tools)) return [];
  return body.tools.flatMap((t) => {
    if (!isRecord(t)) return [];
    const fn = isRecord(t.function) ? t.function : t;
    return [{ name: String(fn.name ?? "tool"), json: JSON.stringify(fn, null, 2) }];
  });
}

/** Everything else in the body (model, stream options, metadata, ...), as JSON text. */
export function requestExtras(body: unknown): string | null {
  if (!isRecord(body)) return null;
  const rest = Object.fromEntries(Object.entries(body).filter(([k]) => k !== "messages" && k !== "tools"));
  return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : null;
}

export interface Choice {
  index: number;
  content: string | null;
  toolCalls: ToolCall[];
}

/**
 * The answer's choices: a `chat.completion` body (non-streamed), or a stream's collected
 * content per choice (`{"content": {"0": "..."}}`, as the traffic log keeps it).
 */
export function responseChoices(body: unknown): Choice[] {
  if (!isRecord(body)) return [];
  if (Array.isArray(body.choices)) {
    return body.choices.flatMap((c, i) => {
      if (!isRecord(c)) return [];
      const msg = isRecord(c.message) ? c.message : {};
      return [
        {
          index: typeof c.index === "number" ? c.index : i,
          content: typeof msg.content === "string" ? msg.content : null,
          toolCalls: toolCallsOf(msg.tool_calls),
        },
      ];
    });
  }
  if (isRecord(body.content)) {
    return Object.entries(body.content)
      .filter(([, v]) => typeof v === "string")
      .map(([k, v]) => ({ index: Number(k), content: v as string, toolCalls: [] }));
  }
  return [];
}

/** The original / restored text with each value marked against its placeholder; null when they don't line up. */
export function alignValues(masked: string, unmasked: string): RestoredSegment[] | null {
  if (masked === unmasked) return [{ kind: "text", text: masked }];
  return alignLoose(masked, unmasked);
}

const LOOPBACK = /^(localhost|127(?:\.\d{1,3}){3}|\[?::1\]?)$/i;

/** `localhost`, `127.x.y.z` or `::1`. */
export function isLoopbackHost(host: string): boolean {
  return LOOPBACK.test(host) || host.toLowerCase().endsWith(".localhost");
}

/**
 * Originals are shown only when the server logged them (level `full`, which pii-guard
 * refuses on anything but a loopback bind) and this page is itself on localhost.
 */
export function canShowOriginals(e: TrafficEvent, pageHost: string, source: "api" | "fixture"): boolean {
  return source === "api" && e.level === "full" && isLoopbackHost(pageHost);
}

export const OUTCOME_LABEL: Record<string, string> = {
  ok: "OK",
  blocked: "Blocked",
  refused: "Refused",
  upstream_error: "Upstream error",
  stream_error: "Stream error",
  error: "Error",
};

export function formatMsShort(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "–";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 100) return `${Math.round(ms)} ms`;
  if (ms >= 10) return `${ms.toFixed(1)} ms`;
  return `${ms.toFixed(2)} ms`;
}

/** How the gateway picked the session, as a person reads it (LAB-1286). */
export const SESSION_SOURCE_LABEL: Record<string, string> = {
  header: "X-PII-Guard-Session header",
  path: "session in the base URL",
  prompt_cache_key: "one per conversation (prompt_cache_key)",
  default: "this client's default session",
};

/** Detector names as the other screens show them; "visual" is the image pipeline. */
export const detectorName = (d: string) => (d === "visual" ? "Image pipeline" : detectorLabel(d));

/** "14:05:09": the console's one clock format (lib/time, LAB-1619). */
export const clock = (iso: string) => clockTime(iso);

/** "fast: Rules + Multilingual NER" from what the calls actually ran. */
export function modeNote(events: TrafficEvent[]): string {
  const by = new Map<string, Set<string>>();
  for (const e of events) {
    const m = e.mode ?? "unknown";
    const set = by.get(m) ?? new Set<string>();
    e.detectors.forEach((d) => set.add(d));
    by.set(m, set);
  }
  if (!by.size) return "Detectors per mode appear with the first call.";
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  return (
    "Detectors seen in the shown calls. " +
    [...by.entries()].map(([m, d]) => `${cap(m)}: ${[...d].map((x) => detectorName(x)).join(" + ") || "none reported"}`).join(". ") +
    "."
  );
}

/** Why a call stopped before the model, from its error code (the traffic event carries no message). */
export function refusalReason(code: string | undefined, image: boolean): string {
  switch (code) {
    case "detection_unavailable":
      return "The requested mode can't run on this server (audit mode needs the LLM detector's key), so PII Guard refused instead of masking with less.";
    case "detection_failed":
      return `A detector failed${image ? " (or the image pipeline is missing OCR or a face detector)" : ""}, so PII Guard refused instead of sending the text unmasked.`;
    case "blocked_entity":
      return "A detected type has the policy block (see Policy), so the request stopped.";
    case "not_found":
      return "Unknown or expired session: drop the X-PII-Guard-Session header, or reuse the one from an earlier answer. Sessions live in the server's memory, so a restart clears them.";
    case "invalid_request":
    case "unsupported_content":
      return "PII Guard couldn't read the request body, so it sent nothing rather than guess what to mask.";
    case "payload_too_large":
      return "The request is larger than the server accepts.";
    case "unauthorized":
      return "The server needs a bearer token (PII_GUARD_API_TOKEN).";
    default:
      return "PII Guard fails closed: when it can't mask a request, the request stops instead of going out unmasked.";
  }
}
