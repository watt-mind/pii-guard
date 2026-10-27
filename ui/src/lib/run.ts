import type { EngineKind, RoutingClient } from "../api/engine";
import { ApiError, UnreachableError } from "../api/http";
import type { KnownValue, KnownValuesResponse, MaskResponse } from "../api/types";
import type { Sample } from "../content/samples";
import {
  attachPlaceholders,
  fillAnswerTemplate,
  genericAnswer,
  linkPlaceholders,
  toLocalSpans,
  type LocalSpan,
  type PlaceholderLink,
} from "./analysis";

export interface RunResult {
  input: string;
  language: string;
  spans: LocalSpan[];
  mask: MaskResponse;
  links: PlaceholderLink[] | null;
  engine: EngineKind;
  ms: number;
  sampleId: string | null;
  /** Counts from the known-values session, when values were pre-loaded. */
  known: KnownValuesResponse | null;
  /** The known values this result was made with (see `knownSignatureOf`). */
  knownSignature: string;
}

export interface RunError {
  code: string;
  message: string;
  /** For `invalid_known_value`: the panel row the API refused. */
  knownIndex?: number;
}

/** A known-values session the Mask screen keeps across runs (values are added, never re-sent). */
export interface KnownSession {
  sessionId: string;
  engine: EngineKind;
  /** `TYPE:value` of every value already in the session. */
  sent: string[];
}

export const knownKey = (v: KnownValue) => `${v.entity_type}:${v.value.trim().toLowerCase()}`;

/** Order-insensitive fingerprint of the known values in use. */
export const knownSignatureOf = (values: readonly KnownValue[]) =>
  values
    .filter((v) => v.value.trim() !== "")
    .map(knownKey)
    .sort()
    .join("|");

export function toRunError(err: unknown): RunError {
  if (err instanceof ApiError) {
    const knownIndex = (err as ApiError & { knownIndex?: number }).knownIndex;
    return knownIndex === undefined ? { code: err.code, message: err.message } : { code: err.code, message: err.message, knownIndex };
  }
  if (err instanceof UnreachableError) return { code: "unreachable", message: err.message };
  return { code: "internal_error", message: "Something went wrong in the UI." };
}

/**
 * Creates the known-values session, or adds only the rows it doesn't hold yet. A refused row
 * comes back as `invalid_known_value` with its index into `values`.
 */
async function prepareKnown(
  client: RoutingClient,
  values: readonly KnownValue[],
  previous: KnownSession | null,
): Promise<{ session: KnownSession; counts: KnownValuesResponse }> {
  const refused = (err: unknown, sent: readonly KnownValue[]) => {
    if (err instanceof ApiError && err.code === "invalid_known_value") {
      const m = /known value (\d+)/.exec(err.message);
      const row = m ? sent[Number(m[1])] : undefined;
      const index = row ? values.indexOf(row) : -1;
      return Object.assign(err, { knownIndex: index >= 0 ? index : undefined });
    }
    return err;
  };
  // A removed row can't be taken out of a session: start a new one.
  const keys = values.map(knownKey);
  if (previous && previous.sent.every((k) => keys.includes(k))) {
    const fresh = values.filter((v) => !previous.sent.includes(knownKey(v)));
    if (fresh.length === 0) {
      return { session: previous, counts: { session_id: previous.sessionId, added: 0, total: previous.sent.length } };
    }
    try {
      const r = await client.addKnownValues(previous.sessionId, fresh);
      return { session: { ...previous, sent: [...previous.sent, ...fresh.map(knownKey)] }, counts: r.data };
    } catch (err) {
      // Expired: start over with every row.
      if (!(err instanceof ApiError && err.code === "not_found")) throw refused(err, fresh);
    }
  }
  try {
    const r = await client.createSession([...values]);
    return { session: { sessionId: r.data.session_id, engine: r.engine, sent: values.map(knownKey) }, counts: r.data };
  } catch (err) {
    throw refused(err, values);
  }
}

export interface RunOptions {
  language?: string;
  known?: readonly KnownValue[];
  knownSession?: KnownSession | null;
  onKnownSession?: (s: KnownSession | null) => void;
}

/** Analyze and mask the same text; both go through the same engine. */
export async function runGuard(client: RoutingClient, text: string, sampleId: string | null, options: RunOptions = {}): Promise<RunResult> {
  const started = performance.now();
  const language = options.language ?? "hu";
  let sessionId: string | null = null;
  let known: KnownValuesResponse | null = null;
  if (options.known?.length) {
    const prepared = await prepareKnown(client, options.known, options.knownSession ?? null);
    options.onKnownSession?.(prepared.session);
    sessionId = prepared.session.sessionId;
    known = prepared.counts;
  }
  const analyzed = await client.analyze(sessionId ? { text, language, session_id: sessionId } : { text, language });
  const masked = await client.mask({ text, language, session_id: sessionId });
  const ms = Math.round(performance.now() - started);
  const local = toLocalSpans(text, analyzed.data.spans);
  const links = linkPlaceholders(text, masked.data.masked_text, local);
  return {
    input: text,
    language,
    known,
    knownSignature: knownSignatureOf(options.known ?? []),
    spans: attachPlaceholders(local, links),
    mask: masked.data,
    links,
    engine: masked.engine,
    ms,
    sampleId,
  };
}

export function initialAnswer(result: RunResult, sample: Sample | undefined): string {
  if (sample && sample.text === result.input) {
    const filled = fillAnswerTemplate(sample.answer, result.input, result.links);
    if (filled !== null) return filled;
  }
  return genericAnswer(result.mask);
}
