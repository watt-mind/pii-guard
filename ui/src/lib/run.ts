import type { EngineKind, RoutingClient } from "../api/engine";
import { ApiError, UnreachableError } from "../api/http";
import type { MaskResponse } from "../api/types";
import type { Sample } from "../data/samples";
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
  spans: LocalSpan[];
  mask: MaskResponse;
  links: PlaceholderLink[] | null;
  engine: EngineKind;
  ms: number;
  sampleId: string | null;
}

export interface RunError {
  code: string;
  message: string;
}

export function toRunError(err: unknown): RunError {
  if (err instanceof ApiError) return { code: err.code, message: err.message };
  if (err instanceof UnreachableError) return { code: "unreachable", message: err.message };
  return { code: "internal_error", message: "Something went wrong in the UI." };
}

/** Analyze and mask the same text; both go through the same engine. */
export async function runGuard(client: RoutingClient, text: string, sampleId: string | null): Promise<RunResult> {
  const started = performance.now();
  const analyzed = await client.analyze({ text, language: "hu" });
  const masked = await client.mask({ text, language: "hu", session_id: null });
  const ms = Math.round(performance.now() - started);
  const local = toLocalSpans(text, analyzed.data.spans);
  const links = linkPlaceholders(text, masked.data.masked_text, local);
  return {
    input: text,
    spans: attachPlaceholders(local, links),
    mask: masked.data,
    links,
    engine: masked.engine,
    ms,
    sampleId,
  };
}

export function initialAnswer(result: RunResult, sample: Sample | undefined): string {
  if (sample && sample.text === result.input) return fillAnswerTemplate(sample.answer, result.input, result.links);
  return genericAnswer(result.mask);
}
