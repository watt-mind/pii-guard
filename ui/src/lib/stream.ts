import type { RoutingClient } from "../api/engine";
import { alignRestored, StreamBuffer, type RestoredSegment } from "./placeholders";

/** Splits text into small, reproducible chunks, the way a model streams tokens. */
export function chunkify(text: string, seed = 7, min = 2, max = 8): string[] {
  let state = seed >>> 0 || 1;
  const rand = () => {
    // xorshift32
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x1_0000_0000;
  };
  const chars = [...text];
  const out: string[] = [];
  let i = 0;
  while (i < chars.length) {
    const n = min + Math.floor(rand() * (max - min + 1));
    out.push(chars.slice(i, i + n).join(""));
    i += n;
  }
  return out;
}

export interface Restoration {
  segments: RestoredSegment[];
  unresolved: string[];
}

/** Unmask a piece of text and split the result into highlightable segments. */
export async function restore(
  client: RoutingClient,
  sessionId: string,
  text: string,
  expected: (placeholder: string) => string | undefined,
): Promise<Restoration> {
  if (text === "") return { segments: [], unresolved: [] };
  const res = await client.unmask({ text, session_id: sessionId });
  const { text: restored, unresolved } = res.data;
  const segments = alignRestored(text, restored, unresolved, (ph) => expected(ph)) ?? [{ kind: "text", text: restored }];
  return { segments, unresolved };
}

export interface StreamStep {
  /** Chunks received so far (masked, as the model sent them). */
  received: string[];
  /** Tail held back because it may be the start of a placeholder. */
  held: string;
  restoration: Restoration;
  /** How many segments existed before this step (for the reveal animation). */
  previousSegmentCount: number;
  done: boolean;
}

export interface StreamOptions {
  client: RoutingClient;
  sessionId: string;
  chunks: readonly string[];
  delayMs: number;
  expected: (placeholder: string) => string | undefined;
  onStep: (step: StreamStep) => void;
  signal: AbortSignal;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}

function defaultSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });
}

/**
 * Plays chunks through a client-side hold-back buffer and unmasks each safe
 * piece as soon as it can. The concatenated output equals unmasking the whole
 * answer at once (the StreamUnmasker contract).
 */
export async function playStream(opts: StreamOptions): Promise<void> {
  const sleep = opts.sleep ?? defaultSleep;
  const buffer = new StreamBuffer();
  const received: string[] = [];
  const segments: RestoredSegment[] = [];
  const unresolved = new Set<string>();

  const emit = async (safe: string, done: boolean) => {
    const previousSegmentCount = mergeText(segments).length;
    if (safe) {
      const r = await restore(opts.client, opts.sessionId, safe, opts.expected);
      segments.push(...r.segments);
      r.unresolved.forEach((u) => unresolved.add(u));
    }
    if (opts.signal.aborted) return;
    opts.onStep({
      received: [...received],
      held: buffer.held,
      restoration: { segments: mergeText(segments), unresolved: [...unresolved] },
      previousSegmentCount,
      done,
    });
  };

  for (const chunk of opts.chunks) {
    if (opts.signal.aborted) return;
    received.push(chunk);
    await emit(buffer.feed(chunk), false);
    await sleep(opts.delayMs, opts.signal);
  }
  if (opts.signal.aborted) return;
  await emit(buffer.flush(), true);
}

/** Adjacent literal segments are merged so the DOM stays small. */
function mergeText(segments: readonly RestoredSegment[]): RestoredSegment[] {
  const out: RestoredSegment[] = [];
  for (const s of segments) {
    const last = out[out.length - 1];
    if (s.kind === "text" && last?.kind === "text") out[out.length - 1] = { kind: "text", text: last.text + s.text };
    else out.push(s);
  }
  return out;
}
