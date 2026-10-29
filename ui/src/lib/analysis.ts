import type { EntityType, MaskResponse, PublicSpan } from "../api/types";
import { codePointIndex } from "./codepoints";
import { CHECKSUM_TYPES, detectorLabel, metaFor, subtypeLabel } from "./entities";
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
  /** The type's effective policy from `/v1/analyze`, when the API reports it. */
  policy?: "mask" | "keep" | "block";
  /** A SECRET span's kind (`github_token` …), when the API reports it. */
  subtype?: string;
}

/**
 * Kept by policy: the API says so, or (older APIs and the demo engine, which send no policy)
 * no placeholder replaced it. A `mask` span whose placeholder couldn't be linked is still masked.
 */
export function isKept(span: LocalSpan): boolean {
  return span.policy ? span.policy === "keep" : span.placeholder === null;
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
    out.push({ start, end, entityType: s.entity_type, score: s.score, detector: s.detector, placeholder: null, ...(s.policy ? { policy: s.policy } : {}), ...(s.subtype ? { subtype: s.subtype } : {}) });
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
  // Exact range first; otherwise the placeholder that overlaps the span most (the mask may
  // have trimmed a title such as "Dr." that analyze kept inside the span).
  return spans.map((s) => {
    const exact = byRange.get(`${s.start}:${s.end}`);
    if (exact) return { ...s, placeholder: exact };
    let best: PlaceholderLink | null = null;
    let bestOverlap = 0;
    for (const l of links) {
      const overlap = Math.min(s.end, l.end) - Math.max(s.start, l.start);
      if (overlap > bestOverlap) {
        best = l;
        bestOverlap = overlap;
      }
    }
    return { ...s, placeholder: best?.placeholder ?? null };
  });
}

export interface Summary {
  detected: number;
  masked: number;
  kept: number;
  distinctPlaceholders: number;
  types: EntityType[];
}

export function summarize(spans: readonly LocalSpan[], mask: MaskResponse | null): Summary {
  const masked = spans.filter((s) => !isKept(s)).length;
  const typeSet = new Set<EntityType>(spans.map((s) => s.entityType));
  mask?.entities.forEach((e) => typeSet.add(e.entity_type));
  return {
    detected: spans.length,
    masked: mask ? mask.entities.reduce((n, e) => n + e.count, 0) || masked : masked,
    kept: spans.filter(isKept).length,
    distinctPlaceholders: mask?.entities.length ?? 0,
    types: [...typeSet],
  };
}

/**
 * What the model saw for input[start, end): masked stretches become their
 * placeholders, everything else is the text that was sent as is.
 */
export function maskedSlice(input: string, start: number, end: number, links: readonly PlaceholderLink[]): string {
  let out = "";
  let cursor = start;
  for (const l of links) {
    if (l.end <= start || l.start >= end) continue;
    if (l.start > cursor) out += input.slice(cursor, l.start);
    out += l.placeholder;
    cursor = Math.max(cursor, l.end);
  }
  if (cursor < end) out += input.slice(cursor, end);
  return out;
}

/**
 * Fills a sample answer template. `{{value}}` becomes exactly what the model
 * saw for that value: its placeholder when the whole value was masked, the
 * placeholders of any masked parts otherwise (a postcode inside an address),
 * and plain text only for parts that reached the model unmasked anyway. The
 * simulated model never "knows" a value it was not sent. Returns null when the
 * masked text could not be lined up with the input (then nothing is safe to
 * echo, and callers should fall back to the generic answer).
 */
export function fillAnswerTemplate(template: string, input: string, links: readonly PlaceholderLink[] | null): string | null {
  if (!links) return null;
  const sorted = [...links].sort((a, b) => a.start - b.start);
  return template.replace(/\{\{([^}]+)\}\}/g, (_, value: string) => {
    const at = input.indexOf(value);
    if (at < 0) return "(not in the document)";
    return maskedSlice(input, at, at + value.length, sorted);
  });
}

/** A generic answer for custom input, built from the placeholders only. */
export function genericAnswer(mask: MaskResponse): string {
  if (mask.entities.length === 0) return "I could not find anyone to write about in this text.";
  const lines = mask.entities.map((e) => `• ${e.placeholder} (mentioned ${e.count}×)`);
  return `Here is what the document refers to:\n\n${lines.join("\n")}\n\nWhich of these should I look into?`;
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
  const kind = subtypeLabel(span.subtype);
  const detector = detectorLabel(span.detector, { types: [span.entityType] });
  const action = span.placeholder ? `masked as ${span.placeholder}` : isKept(span) ? "kept by policy" : "masked";
  const confidence = span.detector === "demo" ? "" : `, confidence ${Math.round(span.score * 100)}%`;
  return `${meta.label}${kind ? ` (${kind})` : ""}, ${action}, found by ${detector}${confidence}`;
}


/** Human labels of the detectors that produced at least one span. */
export function detectorsUsed(spans: readonly LocalSpan[]): string[] {
  const byDetector = new Map<string, EntityType[]>();
  for (const s of spans) byDetector.set(s.detector, [...(byDetector.get(s.detector) ?? []), s.entityType]);
  return [...byDetector].map(([detector, types]) => {
    // "Rules + checksum" for nine values when three were checksum-validated overstates it.
    if (detector === "rules") {
      const checked = types.filter((t) => CHECKSUM_TYPES.has(t)).length;
      if (checked > 0 && checked < types.length) return `Rules (${checked} checksum-validated)`;
    }
    return detectorLabel(detector, { types });
  });
}

export function joinList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
