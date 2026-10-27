// Chat through the pii-guard gateway (`POST /v1/chat/completions`, OpenAI-compatible).
//
// The UI asks the gateway to echo what the model saw and said (`X-PII-Guard-Echo: masked`),
// so the screen can show both sides of the boundary. The echo carries masked text only.
// The demo engine has a simulated stand-in (`createMockChat`) with the same interface.

import { chunkify } from "../lib/stream";
import { StreamBuffer, placeholderRegex } from "../lib/placeholders";
import { ApiError, UnreachableError } from "./http";
import type { GuardClient } from "./types";

export type ChatRole = "system" | "user" | "assistant";
/** `audit` was called `strict` until LAB-1186; the gateway still accepts that name (deprecated). */
export type ChatMode = "fast" | "audit";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatTurnRequest {
  /** The whole conversation, original values included: the gateway masks it. */
  messages: ChatMessage[];
  model: string;
  mode: ChatMode;
  language: string;
  /** The conversation's vault session; null starts one. */
  sessionId: string | null;
  signal?: AbortSignal;
  /** The masked messages, as forwarded to the model (first event of the stream). */
  onMaskedRequest?: (messages: ChatMessage[]) => void;
  /** The restored answer so far. */
  onAnswer?: (restoredSoFar: string) => void;
  /** The model is streaming reasoning tokens (not shown) before its answer. */
  onThinking?: () => void;
}

export interface ChatTurnResult {
  sessionId: string;
  answer: string;
  /** The model's own answer, placeholders and all. */
  maskedAnswer: string;
  maskedMessages: ChatMessage[];
  /** Values masked in this request (`X-PII-Guard-Masked`). */
  masked: number | null;
  /** How the gateway picked the session (`X-PII-Guard-Session-Source`, LAB-1286); null from the demo engine. */
  sessionSource?: string | null;
  mode: ChatMode;
  ms: number;
}

export interface ChatClient {
  readonly kind: "api" | "mock";
  send(req: ChatTurnRequest): Promise<ChatTurnResult>;
}

/** Tells the model how to treat placeholders, including Hungarian suffixes after them. */
export const SYSTEM_PROMPT =
  "Values like [[PERSON_1a2b3c]] stand for the user's real data, masked for privacy. " +
  "Use them verbatim wherever you mean that value, and put any grammatical suffix right after the closing brackets " +
  "(for example [[PERSON_1a2b3c]]nak). Never ask what they stand for. Answer briefly, in plain text without Markdown.";

export const DEFAULT_CHAT_MODEL = import.meta.env.VITE_PII_GUARD_CHAT_MODEL || "meta-models/muse-spark-open-1026";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function asMessages(v: unknown): ChatMessage[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((m) =>
    isRecord(m) && typeof m.content === "string" && typeof m.role === "string"
      ? [{ role: m.role as ChatRole, content: m.content }]
      : [],
  );
}

async function errorFrom(res: Response): Promise<Error> {
  let payload: unknown;
  try {
    payload = JSON.parse(await res.text());
  } catch {
    payload = undefined;
  }
  const err = isRecord(payload) && isRecord(payload.error) ? payload.error : null;
  if (err && typeof err.code === "string") {
    return new ApiError(res.status, err.code, typeof err.message === "string" ? err.message : err.code);
  }
  if (res.status === 404 || res.status === 405) return new ApiError(res.status, "not_found", "the gateway route is not available");
  return new UnreachableError(`pii-guard answered ${res.status} without a contract error body`);
}

export interface HttpChatOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
}

export function createHttpChat(options: HttpChatOptions = {}): ChatClient {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));

  return {
    kind: "api",
    async send(req) {
      const started = performance.now();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-PII-Guard-Echo": "masked",
        "X-PII-Guard-Mode": req.mode,
        "X-PII-Guard-Language": req.language,
      };
      if (req.sessionId) headers["X-PII-Guard-Session"] = req.sessionId;
      let res: Response;
      try {
        res = await doFetch(`${baseUrl}/v1/chat/completions`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            model: req.model,
            stream: true,
            reasoning_effort: "low",
            max_tokens: 1200,
            messages: req.messages,
          }),
          signal: req.signal,
        });
      } catch (err) {
        if (req.signal?.aborted) throw err;
        throw new UnreachableError();
      }
      if (!res.ok) throw await errorFrom(res);
      const sessionId = res.headers.get("x-pii-guard-session") ?? req.sessionId ?? "";
      const maskedHeader = res.headers.get("x-pii-guard-masked");
      let maskedMessages: ChatMessage[] = [];
      let maskedAnswer = "";
      let answer = "";
      let thinking = false;

      const handle = (data: string) => {
        if (data.trim() === "[DONE]") return;
        let event: unknown;
        try {
          event = JSON.parse(data);
        } catch {
          return;
        }
        if (!isRecord(event)) return;
        if (isRecord(event.error)) {
          const e = event.error;
          throw new ApiError(502, typeof e.code === "string" ? e.code : "stream_failed", typeof e.message === "string" ? e.message : "the response stream failed");
        }
        if (event.object === "pii_guard.masked_request") {
          maskedMessages = asMessages(event.messages);
          req.onMaskedRequest?.(maskedMessages);
          return;
        }
        if (event.object === "pii_guard.masked_answer") {
          const first = Array.isArray(event.choices) ? event.choices[0] : undefined;
          if (isRecord(first) && typeof first.content === "string") maskedAnswer = first.content;
          return;
        }
        const choice = Array.isArray(event.choices) ? event.choices[0] : undefined;
        const delta = isRecord(choice) && isRecord(choice.delta) ? choice.delta : null;
        if (delta && !answer && typeof delta.reasoning_content === "string" && delta.reasoning_content && !thinking) {
          thinking = true;
          req.onThinking?.();
        }
        if (delta && typeof delta.content === "string" && delta.content) {
          answer += delta.content;
          req.onAnswer?.(answer);
        }
      };

      if (!res.body) throw new UnreachableError("the gateway returned no stream");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let data: string[] = [];
      try {
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let nl: number;
          while ((nl = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, nl).replace(/\r$/, "");
            buffer = buffer.slice(nl + 1);
            if (line === "") {
              if (data.length) handle(data.join("\n"));
              data = [];
            } else if (line.startsWith("data:")) {
              data.push(line.slice(line.startsWith("data: ") ? 6 : 5));
            }
          }
        }
        if (data.length) handle(data.join("\n"));
      } catch (err) {
        if (req.signal?.aborted || err instanceof ApiError) throw err;
        throw new UnreachableError("the answer stream was interrupted");
      }
      return {
        sessionId,
        answer,
        maskedAnswer,
        maskedMessages,
        masked: maskedHeader === null ? null : Number(maskedHeader),
        sessionSource: res.headers.get("x-pii-guard-session-source"),
        mode: req.mode,
        ms: Math.round(performance.now() - started),
      };
    },
  };
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

/** The simulated model: it can only refer to what it was sent, so it lists the placeholders. */
export function simulatedAnswer(maskedUser: string, language: string): string {
  const placeholders = [...new Set([...maskedUser.matchAll(placeholderRegex())].map((m) => m[0]))];
  if (language === "hu") {
    if (placeholders.length === 0) return "Rendben. Ebben az üzenetben nem találtam személyes adatot.";
    return `Rendben, átnéztem az üzenetet. Ezekre az adatokra hivatkozik: ${placeholders.join(", ")}. Megírjam a választ?`;
  }
  if (placeholders.length === 0) return "Sure. I found no personal data in this message.";
  return `Sure, I read the message. It refers to ${placeholders.join(", ")}. Shall I draft the reply?`;
}

/**
 * Demo engine stand-in for the gateway: masks with the in-browser engine, answers with a
 * simulated model, and restores the answer chunk by chunk. Nothing leaves the page.
 */
export function createMockChat(mock: GuardClient, options: { delayMs?: number } = {}): ChatClient {
  const delayMs = options.delayMs ?? 35;
  return {
    kind: "mock",
    async send(req) {
      const started = performance.now();
      let sessionId = req.sessionId;
      const maskedMessages: ChatMessage[] = [];
      let masked = 0;
      for (const m of req.messages) {
        if (m.role === "system") {
          maskedMessages.push(m);
          continue;
        }
        const r = await mock.mask({ text: m.content, language: req.language, session_id: sessionId });
        sessionId = r.session_id;
        maskedMessages.push({ role: m.role, content: r.masked_text });
        if (m === req.messages[req.messages.length - 1]) masked = r.entities.reduce((n, e) => n + e.count, 0);
      }
      req.onMaskedRequest?.(maskedMessages);
      const lastUser = [...maskedMessages].reverse().find((m) => m.role === "user")?.content ?? "";
      const maskedAnswer = simulatedAnswer(lastUser, req.language);
      const buffer = new StreamBuffer();
      let answer = "";
      for (const chunk of chunkify(maskedAnswer, maskedAnswer.length)) {
        await sleep(delayMs, req.signal);
        const safe = buffer.feed(chunk);
        if (safe) {
          answer += (await mock.unmask({ text: safe, session_id: sessionId! })).text;
          req.onAnswer?.(answer);
        }
      }
      const rest = buffer.flush();
      if (rest) {
        answer += (await mock.unmask({ text: rest, session_id: sessionId! })).text;
        req.onAnswer?.(answer);
      }
      return {
        sessionId: sessionId!,
        answer,
        maskedAnswer,
        maskedMessages,
        masked,
        mode: req.mode,
        ms: Math.round(performance.now() - started),
      };
    },
  };
}
