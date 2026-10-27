// "Send demo traffic" on the Live traffic screen: the same scripted, fictional requests as
// `make demo-traffic` (src/pii_guard/bench/scenarios.py), sent from the browser through the
// gateway. With `make demo` the upstream is the offline mock, which echoes what it received.
//
// Every value is fictional (ADR 0005): placeholder identities, example.* domains and
// well-known test numbers.

import { ApiError, UnreachableError } from "./http";

export const DEMO_MODEL = import.meta.env.VITE_PII_GUARD_DEMO_MODEL || "pii-guard-mock";

const TEXT_HU =
  "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com, telefon: +36 30 123 4567. " +
  "Kérlek, utald a díjat a HU42 1177 3016 1111 1018 0000 0000 számlára, TAJ számom 123 456 788.";
const TEXT_HU_ADDRESS = "Az új lakcímem 1051 Budapest, Minta utca 12., kérlek frissítsd a szerződésen.";
const TEXT_EN =
  "Hi, this is Jane Placeholder (jane.placeholder@example.net, +44 20 7946 0958). Please " +
  "refund the deposit to GB82 WEST 1234 5698 7654 32 and void card 4111 1111 1111 1111.";
const TEXT_DE =
  "Hallo, hier ist Erika Mustermann, E-Mail erika.mustermann@example.de, Telefon +49 30 901820. " +
  "Bitte überweisen Sie auf DE89 3704 0044 0532 0130 00.";
const TOOLS = [
  {
    type: "function",
    function: {
      name: "send_email",
      description: "Send an e-mail on the user's behalf.",
      parameters: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
    },
  },
];
/** A small grey test card (the same image as the Python scenarios). */
const TEST_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAABACAIAAABqVuVZAAAArElEQVR4nO3csQ3DMBAEQcpQbSyatbAYVSBuJMDBTPrZ4uK/9t6Dd7/DDYGaBQWBgkBBoCBQuN8Oa63xsTnn+HsWFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQECgIFAQKAgWBgkBBoCBQEChcHgucWVAQKAgUBAoCBYHG2QOKEQipU5r5KgAAAABJRU5ErkJggg==";

export interface DemoScenario {
  name: string;
  language: string;
  messages: unknown[];
  stream?: boolean;
  tools?: boolean;
  known?: { value: string; entity_type: string }[];
  followUp?: string;
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    name: "hu-chat",
    language: "hu",
    messages: [
      { role: "system", content: "Ügyfélszolgálati asszisztens vagy. Válaszolj röviden." },
      { role: "user", content: TEXT_HU },
    ],
    followUp: "Köszönöm! Kérlek, erősítsd meg az e-mail címemet: teszt.elek@example.com.",
  },
  { name: "hu-stream", language: "hu", messages: [{ role: "user", content: TEXT_HU_ADDRESS }], stream: true },
  { name: "en-stream", language: "en", messages: [{ role: "user", content: TEXT_EN }], stream: true },
  { name: "de-tools", language: "de", messages: [{ role: "user", content: TEXT_DE }], tools: true },
  { name: "de-tools-stream", language: "de", messages: [{ role: "user", content: TEXT_DE }], tools: true, stream: true },
  {
    name: "en-known-values",
    language: "en",
    messages: [{ role: "user", content: "Please draft a short note to Minta Mária about the Placeholder Kft. contract." }],
    known: [
      { value: "Minta Mária", entity_type: "PERSON" },
      { value: "Placeholder Kft.", entity_type: "ORGANIZATION" },
    ],
  },
  {
    name: "hu-image",
    language: "hu",
    messages: [
      {
        role: "user",
        content: [
          { type: "text", text: "Mi látható ezen a képen? Teszt Elek személyi igazolványa." },
          { type: "image_url", image_url: { url: TEST_PNG } },
        ],
      },
    ],
  },
];

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
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
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
