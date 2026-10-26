import type { EntityType, MaskResponse, PublicSpan } from "../api/types";
import { codePointIndex } from "./codepoints";
import { DETECTOR_LABEL, metaFor } from "./entities";
import { alignRestored, tokenize } from "./placeholders";

/** A detected span in UTF-16 indices, ready to slice a JS string. */
export interface LocalSpan {
  start: number;
  end: number;
  entityType: EntityType;
  score: number;
  detector: string;
  /** The placeholder that replaced it in the masked text, if it was masked. */
  placeholder: string | null;
}

/** Where each placeholder occurrence in the masked text came from in the input (UTF-16). */
export interface PlaceholderLink {
  placeholder: string;
  entityType: EntityType | null;
  start: number;
  end: number;
}

export function toLocalSpans(text: string, spans: readonly PublicSpan[]): LocalSpan[] {
  const map = codePointIndex(text);
  const out: LocalSpan[] = [];
  for (const s of spans) {
    const start = map[s.start];
    const end = map[s.end];
    if (start === undefined || end === undefined || start >= end) continue;
    out.push({ start, end, entityType: s.entity_type, score: s.score, detector: s.detector, placeholder: null });
  }
  return out.sort((a, b) => a.start - b.start);
}

/**
 * Lines the masked text up against the input: the literal runs are identical,
 * so whatever sits between them in the input is what each placeholder replaced.
 */
export function linkPlaceholders(
  input: string,
  masked: string,
  spans: readonly LocalSpan[] = [],
): PlaceholderLink[] | null {
  const byStart = new Map(spans.map((s) => [s.start, s]));
  const segments = alignRestored(masked, input, [], (_ph, cursor) => {
    const span = byStart.get(cursor);
    return span ? input.slice(span.start, span.end) : undefined;
  });
  if (!segments) return null;
  const links: PlaceholderLink[] = [];
  let cursor = 0;
  for (const seg of segments) {
    if (seg.kind === "restored") {
      links.push({ placeholder: seg.placeholder, entityType: seg.entityType, start: cursor, end: cursor + seg.text.length });
    }
    cursor += seg.text.length;
  }
  return links;
}

export function attachPlaceholders(spans: LocalSpan[], links: readonly PlaceholderLink[] | null): LocalSpan[] {
  if (!links) return spans;
  const byRange = new Map(links.map((l) => [`${l.start}:${l.end}`, l.placeholder]));
  return spans.map((s) => ({ ...s, placeholder: byRange.get(`${s.start}:${s.end}`) ?? null }));
}

export interface Summary {
  detected: number;
  masked: number;
  kept: number;
  distinctPlaceholders: number;
  types: EntityType[];
}

export function summarize(spans: readonly LocalSpan[], mask: MaskResponse | null): Summary {
  const masked = spans.filter((s) => s.placeholder !== null).length;
  const typeSet = new Set<EntityType>(spans.map((s) => s.entityType));
  mask?.entities.forEach((e) => typeSet.add(e.entity_type));
  return {
    detected: spans.length,
    masked: mask ? mask.entities.reduce((n, e) => n + e.count, 0) || masked : masked,
    kept: spans.filter((s) => s.placeholder === null).length,
    distinctPlaceholders: mask?.entities.length ?? 0,
    types: [...typeSet],
  };
}

/**
 * Fills a sample answer template: `{{value}}` becomes the placeholder that
 * replaced `value` in the input. Values that weren't masked stay as they are.
 */
export function fillAnswerTemplate(template: string, input: string, links: readonly PlaceholderLink[] | null): string {
  const byValue = new Map<string, string>();
  links?.forEach((l) => {
    const value = input.slice(l.start, l.end);
    if (!byValue.has(value)) byValue.set(value, l.placeholder);
  });
  return template.replace(/\{\{([^}]+)\}\}/g, (_, value: string) => byValue.get(value) ?? value);
}

/** A generic answer for custom input, built from the placeholders only. */
export function genericAnswer(mask: MaskResponse): string {
  if (mask.entities.length === 0) return "I could not find anyone to write about in this text.";
  const lines = mask.entities.map((e) => `• ${e.placeholder} (mentioned ${e.count}×)`);
  return `Here is what the document refers to:\n\n${lines.join("\n")}\n\nLet me know which of these you want me to contact first.`;
}

/** placeholder -> the input value it replaced, from the links. */
export function valuesByPlaceholder(input: string, links: readonly PlaceholderLink[] | null): Map<string, string> {
  const map = new Map<string, string>();
  links?.forEach((l) => {
    if (!map.has(l.placeholder)) map.set(l.placeholder, input.slice(l.start, l.end));
  });
  return map;
}

export function placeholdersIn(text: string): string[] {
  return tokenize(text).flatMap((t) => (t.kind === "placeholder" ? [t.text] : []));
}

/** Hover/focus key: spans that share a placeholder light up together. */
export function spanKey(span: LocalSpan): string {
  return span.placeholder ?? `span:${span.start}:${span.end}`;
}

export function describeSpan(span: LocalSpan): string {
  const meta = metaFor(span.entityType);
  const detector = DETECTOR_LABEL[span.detector] ?? span.detector;
  const action = span.placeholder ? `masked as ${span.placeholder}` : "kept by policy";
  return `${meta.label}, ${action}, found by ${detector}, confidence ${Math.round(span.score * 100)}%`;
}

