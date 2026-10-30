import type { HTMLAttributes } from "react";
import { TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, type EntityType } from "../api/types";

export type ActivateHandler = (key: string | null, anchor?: HTMLElement | null) => void;

/** Hover, focus, and Escape dismissal props for an interactive entity mark or placeholder chip. */
export function activationHandlers(key: string, onActivate?: ActivateHandler): HTMLAttributes<HTMLElement> {
  if (!onActivate) return {};
  return {
    tabIndex: 0,
    onMouseEnter: (e) => onActivate(key, e.currentTarget),
    onMouseLeave: () => onActivate(null),
    onFocus: (e) => onActivate(key, e.currentTarget),
    onBlur: () => onActivate(null),
    onKeyDown: (e) => {
      if (e.key === "Escape") onActivate(null);
    },
  };
}

/** docs/contracts.md, "Placeholder format". */
export const PLACEHOLDER_SOURCE = String.raw`\[\[([A-Z][A-Z0-9_]*)_([0-9a-f]{4,})\]\]`;

export function placeholderRegex(): RegExp {
  return new RegExp(PLACEHOLDER_SOURCE, "g");
}

const KNOWN_TYPES = new Set<string>([...TEXT_ENTITY_TYPES, ...VISUAL_ENTITY_TYPES]);

export function isEntityType(value: string): value is EntityType {
  return KNOWN_TYPES.has(value);
}

export type Token =
  | { kind: "text"; text: string }
  | { kind: "placeholder"; text: string; entityType: EntityType | null; id: string };

/** Splits text into literal runs and placeholder tokens, in order. */
export function tokenize(text: string): Token[] {
  const tokens: Token[] = [];
  let last = 0;
  for (const m of text.matchAll(placeholderRegex())) {
    const at = m.index;
    if (at > last) tokens.push({ kind: "text", text: text.slice(last, at) });
    const type = m[1] ?? "";
    tokens.push({
      kind: "placeholder",
      text: m[0],
      entityType: isEntityType(type) ? type : null,
      id: m[2] ?? "",
    });
    last = at + m[0].length;
  }
  if (last < text.length) tokens.push({ kind: "text", text: text.slice(last) });
  return tokens;
}

// A tail that could still grow into a placeholder: "[", "[[", "[[PERS", "[[PERSON_7f", "[[PERSON_7f3a]".
const PARTIAL_TAIL = /\[(?:\[(?:[A-Z][A-Z0-9_]*(?:_[0-9a-f]*)?)?(?:\])?)?$/;
const MAX_PLACEHOLDER_LENGTH = 96;

/**
 * Splits a stream buffer into the part that is safe to emit now and the
 * trailing part that must be held back because it may be the start of a
 * placeholder split across chunks. Mirrors `StreamUnmasker.feed` in the vault
 * contract; holding back never needs the mapping, only the shape.
 */
export function splitSafe(buffer: string): { safe: string; held: string } {
  const m = PARTIAL_TAIL.exec(buffer);
  if (!m || buffer.length - m.index > MAX_PLACEHOLDER_LENGTH) return { safe: buffer, held: "" };
  const tail = buffer.slice(m.index);
  // A complete placeholder at the end is safe to emit.
  if (new RegExp(`^${PLACEHOLDER_SOURCE}$`).test(tail)) return { safe: buffer, held: "" };
  return { safe: buffer.slice(0, m.index), held: tail };
}

/** Client-side mirror of `StreamUnmasker`: feed chunks, get text that is safe to send to unmask. */
export class StreamBuffer {
  private pending = "";

  feed(chunk: string): string {
    const { safe, held } = splitSafe(this.pending + chunk);
    this.pending = held;
    return safe;
  }

  get held(): string {
    return this.pending;
  }

  flush(): string {
    const rest = this.pending;
    this.pending = "";
    return rest;
  }
}

/**
 * Re-identified text as segments, so restored values can be highlighted.
 * Literal runs between placeholders survive unmasking unchanged, so the
 * restored value for each placeholder is whatever sits between them.
 * Returns null if the unmasked text doesn't line up (then show it plain).
 */
export type RestoredSegment =
  | { kind: "text"; text: string }
  | { kind: "restored"; text: string; placeholder: string; entityType: EntityType | null }
  | { kind: "unresolved"; text: string; entityType: EntityType | null };

function matchesExpectedHint(unmasked: string, cursor: number, hint: string | undefined, next: Token | undefined): hint is string {
  if (!hint || !unmasked.startsWith(hint, cursor)) return false;
  if (next === undefined) return cursor + hint.length === unmasked.length;
  return next.kind === "text" ? unmasked.startsWith(next.text, cursor + hint.length) : true;
}

function resolvePlaceholderEnd(
  unmasked: string,
  cursor: number,
  hint: string | undefined,
  next: Token | undefined,
): number | null {
  if (matchesExpectedHint(unmasked, cursor, hint, next)) return cursor + hint.length;
  if (next === undefined) return unmasked.length;
  if (next.kind !== "text") return null; // Two placeholders back to back can't be told apart; give up on highlighting.
  const end = unmasked.indexOf(next.text, cursor);
  return end < 0 ? null : end;
}

/**
 * `expected(placeholder, cursor)` may return the value a placeholder is known
 * to stand for (from the analysed input); it settles ambiguous alignments such
 * as a value that contains the literal text that follows it.
 */
export function alignRestored(
  masked: string,
  unmasked: string,
  unresolved: readonly string[] = [],
  expected?: (placeholder: string, cursor: number) => string | undefined,
): RestoredSegment[] | null {
  const tokens = tokenize(masked);
  const unresolvedSet = new Set(unresolved);
  const segments: RestoredSegment[] = [];
  let cursor = 0;

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]!;
    if (token.kind === "text") {
      if (!unmasked.startsWith(token.text, cursor)) return null;
      segments.push({ kind: "text", text: token.text });
      cursor += token.text.length;
      continue;
    }
    if (unresolvedSet.has(token.text) && unmasked.startsWith(token.text, cursor)) {
      segments.push({ kind: "unresolved", text: token.text, entityType: token.entityType });
      cursor += token.text.length;
      continue;
    }
    const end = resolvePlaceholderEnd(unmasked, cursor, expected?.(token.text, cursor), tokens[i + 1]);
    if (end === null) return null;
    segments.push({
      kind: "restored",
      text: unmasked.slice(cursor, end),
      placeholder: token.text,
      entityType: token.entityType,
    });
    cursor = end;
  }
  return cursor === unmasked.length ? segments : null;
}

function resolveLooseAnchor(unmasked: string, cursor: number, text: string): { end: number; remainingText: string } | null {
  // The suffix glued to the value (its leading letters) may have been re-inflected.
  const suffix = /^\p{L}{0,6}/u.exec(text)?.[0].length ?? 0;
  const anchorFrom = suffix < text.length ? suffix : 0;
  const remainingText = text.slice(anchorFrom);
  const end = unmasked.indexOf(remainingText, cursor);
  return end < 0 ? null : { end, remainingText };
}

/**
 * Like {@link alignRestored}, for restored text whose seams may differ from the masked text:
 * the gateway can re-inflect a suffix after a value (Hungarian vowel harmony), so a literal
 * run may not survive byte for byte. Each placeholder's value runs up to the next literal
 * run, found by its tail (its first few characters may have changed). Returns null only when
 * a run can't be found at all.
 */
export function alignLoose(masked: string, unmasked: string): RestoredSegment[] | null {
  const tokens = tokenize(masked);
  const segments: RestoredSegment[] = [];
  let cursor = 0;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i]!;
    if (token.kind === "text") {
      if (!unmasked.startsWith(token.text, cursor)) return null;
      segments.push({ kind: "text", text: token.text });
      cursor += token.text.length;
      continue;
    }
    // Swallow any directly following placeholders into this value (they can't be told apart).
    let j = i + 1;
    while (tokens[j]?.kind === "placeholder") j++;
    const next = tokens[j];
    let end = unmasked.length;
    if (next !== undefined) {
      const anchored = resolveLooseAnchor(unmasked, cursor, next.text);
      if (!anchored) return null;
      end = anchored.end;
      // The changed head of the next run belongs to this value's suffix.
      tokens[j] = { kind: "text", text: anchored.remainingText };
    }
    segments.push({ kind: "restored", text: unmasked.slice(cursor, end), placeholder: token.text, entityType: token.entityType });
    cursor = end;
    i = j - 1;
  }
  return cursor === unmasked.length ? segments : null;
}
