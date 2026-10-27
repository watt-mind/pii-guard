// Built-in demo engine. Runs entirely in the browser so the demo works before
// (or without) the API. It is NOT the real detector: a few regexes with
// checksums plus a gazetteer of the fictional names used in the samples.
// Nothing here leaves the page.

import { utf16ToCodePoint } from "../lib/codepoints";
import { ENTITY_META } from "../lib/entities";
import { placeholderRegex } from "../lib/placeholders";
import { ApiError } from "./http";
import { createMockImageEngine } from "./imageMock";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  GuardClient,
  KnownValue,
  KnownValuesResponse,
  MaskRequest,
  MaskResponse,
  PublicSpan,
  TextEntityType,
  UnmaskRequest,
  UnmaskResponse,
} from "./types";

interface RawSpan {
  start: number; // UTF-16 index
  end: number;
  entity_type: TextEntityType;
  score: number;
  detector: "rules" | "ner" | "llm" | "known";
}

// --- checksums (same rules the real `rules` detector validates) -------------

function digits(s: string): number[] {
  return [...s.replace(/\D/g, "")].map(Number);
}

export function validHuTaxId(value: string): boolean {
  const d = digits(value);
  if (d.length !== 10 || d[0] !== 8) return false;
  const sum = d.slice(0, 9).reduce((acc, n, i) => acc + n * (i + 1), 0);
  return sum % 11 === d[9];
}

export function validHuTaj(value: string): boolean {
  const d = digits(value);
  if (d.length !== 9) return false;
  const sum = d.slice(0, 8).reduce((acc, n, i) => acc + n * (i % 2 === 0 ? 3 : 7), 0);
  return sum % 10 === d[8];
}

export function validIban(value: string): boolean {
  const s = value.replace(/\s/g, "").toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(s)) return false;
  const moved = s.slice(4) + s.slice(0, 4);
  let rem = 0;
  for (const ch of moved) {
    const n = parseInt(ch, 36);
    for (const digit of String(n)) rem = (rem * 10 + Number(digit)) % 97;
  }
  return rem === 1;
}

// --- detectors --------------------------------------------------------------

const UPPER = "A-ZÁÉÍÓÖŐÚÜŰ";
const LOWER = "a-záéíóöőúüű";
const MONTHS = "január|február|március|április|május|június|július|augusztus|szeptember|október|november|december";

const SURNAMES = [
  "Bárdos", "Varga", "Somogyi", "Takács", "Fehér", "Németh", "Kerekes", "Kovács", "Szabó", "Tóth",
  "Nagy", "Horváth", "Kiss", "Molnár", "Farkas", "Balogh", "Papp", "Lakatos", "Teszt", "Minta",
];
const GIVEN = [
  "Kinga", "Levente", "Ádám", "Gábor", "Ilona", "Zsófia", "Bálint", "Ottó", "Elek", "Péter", "Anna",
  "Eszter", "László", "Katalin", "Mária", "Zoltán", "Judit", "Bence", "Réka", "Dóra", "Márta",
];

interface Pattern {
  type: TextEntityType;
  detector: RawSpan["detector"];
  score: number;
  re: RegExp;
  /** Capture group holding the value, when the match includes context. */
  group?: number;
  validate?: (value: string) => boolean;
}

const PATTERNS: Pattern[] = [
  { type: "EMAIL", detector: "rules", score: 1, re: /\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b/g },
  {
    type: "BANK_ACCOUNT",
    detector: "rules",
    score: 1,
    re: /\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b/g,
    validate: validIban,
  },
  { type: "BANK_ACCOUNT", detector: "rules", score: 0.98, re: /\b\d{8}-\d{8}(?:-\d{8})?\b/g },
  { type: "NATIONAL_ID_HU_TAX", detector: "rules", score: 1, re: /\b8\d{9}\b/g, validate: validHuTaxId },
  { type: "NATIONAL_ID_HU_TAJ", detector: "rules", score: 0.99, re: /\b\d{3} ?\d{3} ?\d{3}\b/g, validate: validHuTaj },
  { type: "COMPANY_ID_HU", detector: "rules", score: 0.99, re: /\b\d{2}-\d{2}-\d{6}\b/g },
  {
    type: "PHONE",
    detector: "rules",
    score: 0.97,
    re: /(?<![\w+])(?:\+36|06)[ -]?(?:1|[2-9]\d)[ -/]?\d{3}[ -]?\d{3,4}\b/g,
  },
  { type: "PHONE", detector: "rules", score: 0.97, re: /\+44 ?\d{2} ?\d{4} ?\d{4}\b/g },
  { type: "PERSON", detector: "ner", score: 0.95, re: /\b(?:Jane Placeholder|Sam Example|John Sample)\b/g },
  { type: "VEHICLE_PLATE", detector: "rules", score: 0.96, re: /\b(?:[A-Z]{2} )?[A-Z]{2,3}-\d{3}\b/g },
  { type: "ID_DOCUMENT", detector: "rules", score: 0.93, re: /\b\d{6}[A-Z]{2}\b/g },
  {
    type: "PARCEL_NUMBER_HU",
    detector: "llm",
    score: 0.88,
    re: /\bhrsz\.?\s*(\d{1,6}(?:\/\d+)?(?:\/[A-Z])?(?:\/\d+)?)/gi,
    group: 1,
  },
  {
    type: "ADDRESS",
    detector: "llm",
    score: 0.86,
    re: new RegExp(
      String.raw`\b[1-9]\d{3} [${UPPER}][${LOWER}]+,? (?:[${UPPER}][${LOWER}]+ ){1,3}(?:utca|út|tér|körút|köz|sor|sétány|fasor) \d+(?:\/[A-Z])?\.(?: \d+\/\d+\.)?`,
      "gu",
    ),
  },
  {
    type: "DATE_OF_BIRTH",
    detector: "llm",
    score: 0.91,
    re: new RegExp(String.raw`(?:szület\w*|szül\.)[^\d\n]{0,20}(\d{4}\. (?:${MONTHS}) \d{1,2}\.)`, "giu"),
    group: 1,
  },
  {
    type: "PERSON",
    detector: "ner",
    score: 0.95,
    re: new RegExp(String.raw`\b(?:${SURNAMES.join("|")})(?:né)? (?:${GIVEN.join("|")})(?: (?:${GIVEN.join("|")}))?`, "gu"),
  },
  {
    type: "ORGANIZATION",
    detector: "ner",
    score: 0.84,
    re: new RegExp(String.raw`(?:[${UPPER}][${LOWER}-]+ ){1,4}(?:Kft\.|Zrt\.|Nyrt\.|Bt\.|Ügyvédi Iroda)`, "gu"),
  },
];

function scoreJitter(text: string, base: number): number {
  if (base >= 1) return 1;
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return Math.round(Math.min(0.99, base + ((h % 7) - 3) / 100) * 100) / 100;
}

/** Longer spans win, then higher scores; overlapping losers are dropped. */
function resolve(spans: RawSpan[]): RawSpan[] {
  const ranked = [...spans].sort((a, b) => b.end - b.start - (a.end - a.start) || b.score - a.score);
  const kept: RawSpan[] = [];
  for (const s of ranked) {
    if (kept.every((k) => s.end <= k.start || s.start >= k.end)) kept.push(s);
  }
  return kept.sort((a, b) => a.start - b.start);
}

export function detect(text: string): RawSpan[] {
  const found: RawSpan[] = [];
  for (const p of PATTERNS) {
    for (const m of text.matchAll(p.re)) {
      const value = p.group ? m[p.group] : m[0];
      if (!value) continue;
      const start = m.index + (p.group ? m[0].indexOf(value) : 0);
      if (p.validate && !p.validate(value)) continue;
      found.push({
        start,
        end: start + value.length,
        entity_type: p.type,
        score: scoreJitter(value, p.score),
        detector: p.detector,
      });
    }
  }
  return resolve(found);
}

// --- known values (the `known` detector) -------------------------------------

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Every whole-word occurrence of a known value, case-insensitive, with any suffix glued on
 * (Gyakorló Tihamérnak): the span covers the value, the suffix stays outside.
 */
export function detectKnown(text: string, known: readonly KnownValue[]): RawSpan[] {
  const out: RawSpan[] = [];
  for (const k of known) {
    const words = k.value.trim().split(/\s+/).map(escapeRe).join("\\s+");
    const re = new RegExp(`(?<![\\p{L}\\p{N}])${words}`, "giu");
    for (const m of text.matchAll(re)) {
      out.push({ start: m.index, end: m.index + m[0].length, entity_type: k.entity_type, score: 1, detector: "known" });
    }
  }
  return out;
}

/** Known spans win every conflict, as in the real resolver. */
export function mergeKnown(spans: RawSpan[], known: RawSpan[]): RawSpan[] {
  if (!known.length) return spans;
  const winners = resolve(known);
  const rest = spans.filter((s) => winners.every((k) => s.end <= k.start || s.start >= k.end));
  return [...rest, ...winners].sort((a, b) => a.start - b.start);
}

// --- vault ------------------------------------------------------------------

function fnv1a(input: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

function normalize(type: TextEntityType, value: string): string {
  const v = value.normalize("NFC").trim().replace(/\s+/g, " ").toLowerCase();
  return type === "PHONE" || type === "BANK_ACCOUNT" || type === "NATIONAL_ID_HU_TAJ" ? v.replace(/[\s-]/g, "") : v;
}

function randomHex(bytes: number): string {
  const arr = new Uint8Array(bytes);
  globalThis.crypto.getRandomValues(arr);
  return [...arr].map((b) => b.toString(16).padStart(2, "0")).join("");
}

interface MockSession {
  salt: string;
  byKey: Map<string, string>; // normalized key -> placeholder
  values: Map<string, string>; // placeholder -> original surface value
  counts: Map<string, number>;
  types: Map<string, TextEntityType>;
  known: KnownValue[];
}

export interface MockClientOptions {
  /** Artificial latency in ms for analyze/mask so the UI states are visible. 0 in tests. */
  latencyMs?: number;
}

export const MOCK_SESSION_PREFIX = "s_demo_";

export function createMockClient(options: MockClientOptions = {}): GuardClient {
  const latency = options.latencyMs ?? 0;
  const sessions = new Map<string, MockSession>();

  const wait = () => (latency > 0 ? new Promise((r) => setTimeout(r, latency)) : Promise.resolve());

  function toPublic(text: string, spans: RawSpan[]): PublicSpan[] {
    const cp = utf16ToCodePoint(text);
    return spans.map((s) => ({
      start: cp(s.start),
      end: cp(s.end),
      entity_type: s.entity_type,
      score: s.score,
      detector: s.detector,
    }));
  }

  function newSession(): [string, MockSession] {
    const id = MOCK_SESSION_PREFIX + randomHex(6);
    const session: MockSession = { salt: randomHex(8), byKey: new Map(), values: new Map(), counts: new Map(), types: new Map(), known: [] };
    sessions.set(id, session);
    return [id, session];
  }

  function addKnown(sessionId: string, session: MockSession, values: KnownValue[]): KnownValuesResponse {
    values.forEach((v, i) => {
      if (v.value.replace(/\s/g, "").length < 3) {
        throw new ApiError(422, "invalid_known_value", `known value ${i} (${v.entity_type}) is too short: at least 3 non-space characters`);
      }
    });
    let added = 0;
    for (const v of values) {
      const key = `${v.entity_type}:${normalize(v.entity_type, v.value)}`;
      if (session.known.some((k) => `${k.entity_type}:${normalize(k.entity_type, k.value)}` === key)) continue;
      session.known.push({ value: v.value.trim(), entity_type: v.entity_type });
      added++;
    }
    return { session_id: sessionId, added, total: session.known.length };
  }

  function spansFor(text: string, session: MockSession | undefined): RawSpan[] {
    return mergeKnown(detect(text), session ? detectKnown(text, session.known) : []);
  }

  function placeholderFor(session: MockSession, type: TextEntityType, value: string): string {
    const key = `${type}:${normalize(type, value)}`;
    const existing = session.byKey.get(key);
    if (existing) return existing;
    const digest = fnv1a(session.salt + key);
    for (let len = 4; len <= digest.length; len++) {
      const candidate = `[[${type}_${digest.slice(0, len)}]]`;
      if (!session.values.has(candidate)) {
        session.byKey.set(key, candidate);
        session.values.set(candidate, value);
        session.types.set(candidate, type);
        return candidate;
      }
    }
    throw new ApiError(500, "masking_failed", `could not allocate a ${type} placeholder`);
  }

  return {
    async analyze(req: AnalyzeRequest): Promise<AnalyzeResponse> {
      await wait();
      let session: MockSession | undefined;
      if (req.session_id) {
        session = sessions.get(req.session_id);
        if (!session) throw new ApiError(404, "not_found", "unknown session_id");
      }
      return { spans: toPublic(req.text, spansFor(req.text, session)) };
    },

    async createSession(known: KnownValue[]): Promise<KnownValuesResponse> {
      await wait();
      const [id, session] = newSession();
      try {
        return addKnown(id, session, known);
      } catch (err) {
        sessions.delete(id);
        throw err;
      }
    },

    async addKnownValues(sessionId: string, known: KnownValue[]): Promise<KnownValuesResponse> {
      await wait();
      const session = sessions.get(sessionId);
      if (!session) throw new ApiError(404, "not_found", "unknown session_id");
      return addKnown(sessionId, session, known);
    },

    async mask(req: MaskRequest): Promise<MaskResponse> {
      await wait();
      let session: MockSession;
      let sessionId: string;
      if (req.session_id) {
        const found = sessions.get(req.session_id);
        if (!found) throw new ApiError(404, "not_found", "unknown session_id");
        session = found;
        sessionId = req.session_id;
      } else {
        [sessionId, session] = newSession();
      }

      // Known values are masked even for a `keep` type: the application asked for it.
      const spans = spansFor(req.text, session).filter((s) => s.detector === "known" || ENTITY_META[s.entity_type].policy === "mask");
      const used = new Map<string, number>();
      let out = "";
      let cursor = 0;
      for (const s of spans) {
        const ph = placeholderFor(session, s.entity_type, req.text.slice(s.start, s.end));
        out += req.text.slice(cursor, s.start) + ph;
        cursor = s.end;
        used.set(ph, (used.get(ph) ?? 0) + 1);
        session.counts.set(ph, (session.counts.get(ph) ?? 0) + 1);
      }
      out += req.text.slice(cursor);

      return {
        masked_text: out,
        session_id: sessionId,
        entities: [...used.entries()].map(([placeholder, count]) => ({
          placeholder,
          entity_type: session.types.get(placeholder)!,
          count,
        })),
      };
    },

    // Images: replays recorded regions for the built-in samples (see imageMock.ts).
    maskImage: createMockImageEngine({ latencyMs: latency * 3 }).maskImage,

    // No artificial latency here: streaming calls unmask once per chunk.
    async unmask(req: UnmaskRequest): Promise<UnmaskResponse> {
      const session = sessions.get(req.session_id);
      if (!session) throw new ApiError(404, "not_found", "unknown session_id");
      const unresolved: string[] = [];
      const text = req.text.replace(placeholderRegex(), (ph) => {
        const value = session.values.get(ph);
        if (value === undefined) {
          if (!unresolved.includes(ph)) unresolved.push(ph);
          return ph;
        }
        return value;
      });
      return { text, unresolved };
    },
  };
}

