import { createProjectFetch } from "./project";
// "Send demo traffic" on the Live traffic screen: the same scripted, fictional requests as
// `make demo-traffic`, sent from the browser through the gateway. With `make demo` the
// upstream is the offline mock, which echoes what it received.
//
// The scenarios are not copied by hand: ../content/demoScenarios.json is written from
// src/pii_guard/bench/scenarios.py (`uv run python scripts/demo_traffic.py --export-ui`) and
// a pytest keeps the two in sync. Every value is fictional (ADR 0005): placeholder
// identities, example.* domains and checksum-valid test numbers. Names are pre-loaded as
// session known values, so rules-only mode masks them too, except in the one scenario
// labelled "needs fast mode (NER)": a free-text name only the NER can find.

import exported from "../content/demoScenarios.json";
import { ApiError, UnreachableError } from "./http";
import type { TrafficEvent } from "./traffic";
import { requestMessages } from "../lib/traffic";

export const DEMO_MODEL = import.meta.env.VITE_PII_GUARD_DEMO_MODEL || "pii-guard-mock";

/** A small grey test card (the same image as the Python scenarios). */
const TEST_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAABACAIAAABqVuVZAAAArElEQVR4nO3csQ3DMBAEQcpQbSyatbAYVSBuJMDBTPrZ4uK/9t6Dd7/DDYGaBQWBgkBBoCBQuN8Oa63xsTnn+HsWFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQEChcHgucWVAQKAgUBAoCBYHG2QOKEQipU5r5KgAAAABJRU5ErkJggg==";

interface ExportedScenario {
  name: string;
  language: string;
  system?: string;
  text: string;
  gold: string[];
  stream?: boolean;
  tools?: boolean;
  image?: boolean;
  known?: { value: string; entity_type: string }[];
  followUp?: string;
  requires?: string[];
  label?: string | null;
}

export interface DemoScenario {
  name: string;
  language: string;
  messages: unknown[];
  stream?: boolean;
  tools?: boolean;
  known?: { value: string; entity_type: string }[];
  followUp?: string;
  /** The user text of the first turn. */
  text: string;
  /** Values that must not reach the model (when `requires` is met). */
  gold: string[];
  /** Detectors the gold needs beyond rules + known values, e.g. ["ner"]. */
  requires: string[];
  /** Shown on its calls, e.g. "needs fast mode (NER)". */
  label: string | null;
}

const TOOLS = exported.tools;

function toScenario(s: ExportedScenario): DemoScenario {
  const user = s.image
    ? { role: "user", content: [{ type: "text", text: s.text }, { type: "image_url", image_url: { url: TEST_PNG } }] }
    : { role: "user", content: s.text };
  return {
    name: s.name,
    language: s.language,
    messages: [...(s.system ? [{ role: "system", content: s.system }] : []), user],
    stream: s.stream,
    tools: s.tools,
    known: s.known,
    followUp: s.followUp,
    text: s.text,
    gold: s.gold,
    requires: s.requires ?? [],
    label: s.label ?? null,
  };
}

export const DEMO_SCENARIOS: DemoScenario[] = (exported.scenarios as ExportedScenario[]).map(toScenario);

/** Scenarios whose values only an optional detector finds: expected misses in rules-only mode. */
export const LABELLED_SCENARIOS = DEMO_SCENARIOS.filter((s) => s.requires.length > 0);

const escapeRe = (v: string) => v.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export interface LabelledMatch {
  scenario: DemoScenario;
  /** Gold values that reached the model as written (the expected miss in rules-only mode). */
  missed: string[];
}

/**
 * The labelled demo scenario this call came from, if any: its last user message is the
 * scenario's text, with each gold value either as written (missed) or as a placeholder.
 */
export function labelledScenarioFor(event: TrafficEvent): LabelledMatch | null {
  const messages = requestMessages(event.request?.masked);
  const last = [...messages].reverse().find((m) => m.role === "user");
  const part = last?.parts.find((p) => p.kind === "text");
  if (!part || part.kind !== "text") return null;
  for (const scenario of LABELLED_SCENARIOS) {
    let pattern = escapeRe(scenario.text);
    for (const g of scenario.gold) pattern = pattern.split(escapeRe(g)).join(`(?:${escapeRe(g)}|\\[\\[[A-Z_]+_[0-9a-f]+\\]\\])`);
    if (new RegExp(`^${pattern}$`).test(part.text)) {
      return { scenario, missed: scenario.gold.filter((g) => part.text.includes(g)) };
    }
  }
  return null;
}

export interface DemoProgress {
  done: number;
  total: number;
  /** Requests the gateway refused (an image without SAM is refused by design: fail closed). */
  refused: number;
}

/** Requests one run sends: every scenario plus each follow-up turn. */
export const DEMO_REQUESTS = DEMO_SCENARIOS.reduce((n, s) => n + (s.followUp ? 2 : 1), 0);

export interface DemoTrafficOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  model?: string;
  signal?: AbortSignal;
  onProgress?: (p: DemoProgress) => void;
}

async function readAnswer(res: Response, stream: boolean): Promise<string | null> {
  const text = await res.text();
  if (stream) {
    let out = "";
    for (const line of text.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") break;
      try {
        const chunk = JSON.parse(data) as { choices?: { delta?: { content?: unknown } }[] };
        const c = chunk.choices?.[0]?.delta?.content;
        if (typeof c === "string") out += c;
      } catch {
        // keep-alives and echo events
      }
    }
    return out;
  }
  try {
    const body = JSON.parse(text) as { choices?: { message?: { content?: unknown } }[] };
    const c = body.choices?.[0]?.message?.content;
    return typeof c === "string" ? c : null;
  } catch {
    return null;
  }
}

/**
 * Send the demo scenarios one after another. Resolves with the final progress; throws
 * `UnreachableError` when the gateway can't be reached at all, or an `ApiError` when
 * the gateway route is missing (a server without an upstream configured).
 */
export async function sendDemoTraffic(options: DemoTrafficOptions = {}): Promise<DemoProgress> {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = createProjectFetch(options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args)));
  const model = options.model ?? DEMO_MODEL;
  const progress: DemoProgress = { done: 0, total: DEMO_REQUESTS, refused: 0 };
  const post = async (path: string, body: unknown, headers: Record<string, string> = {}) => {
    try {
      return await doFetch(`${baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(body),
        signal: options.signal,
      });
    } catch (err) {
      if (options.signal?.aborted) throw err;
      throw new UnreachableError();
    }
  };

  for (const s of DEMO_SCENARIOS) {
    let session: string | null = null;
    if (s.known) {
      const r = await post("/v1/sessions", { known_values: s.known });
      if (r.ok) session = ((await r.json()) as { session_id?: string }).session_id ?? null;
    }
    const send = async (messages: unknown[]) => {
      const body: Record<string, unknown> = { model, messages };
      if (s.stream) {
        body.stream = true;
        body.stream_options = { include_usage: true };
      }
      if (s.tools) body.tools = TOOLS;
      const headers: Record<string, string> = { "X-PII-Guard-Mode": "fast", "X-PII-Guard-Language": s.language };
      if (session) headers["X-PII-Guard-Session"] = session;
      const res = await post("/v1/chat/completions", body, headers);
      if (res.status === 404 && progress.done === 0) throw new ApiError(404, "not_found", "the gateway route is not available on this server");
      session = res.headers.get("x-pii-guard-session") ?? session;
      const answer = res.ok ? await readAnswer(res, Boolean(s.stream)) : (await res.text(), null);
      if (!res.ok) progress.refused += 1;
      progress.done += 1;
      options.onProgress?.({ ...progress });
      return answer;
    };
    const answer = await send(s.messages);
    if (s.followUp && answer !== null) {
      await send([...s.messages, { role: "assistant", content: answer }, { role: "user", content: s.followUp }]);
    } else if (s.followUp) {
      progress.done += 1; // the follow-up isn't sent without a first answer
      options.onProgress?.({ ...progress });
    }
  }
  return progress;
}
