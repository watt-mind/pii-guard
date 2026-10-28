import type { ReactNode } from "react";
import { metaFor } from "../lib/entities";
import { alignLoose, alignRestored, tokenize, type RestoredSegment } from "../lib/placeholders";
import type { EntityType } from "../api/types";

/**
 * The landing's three highlight kinds (ui/DESIGN.md, "Hosted landing"): personal data in your
 * text (danger tint), the placeholder the model sees (plum) and the value put back (guard green).
 * The type is always written out for screen readers, so colour never carries it alone.
 */
type Kind = "original" | "placeholder" | "restored";
const SUFFIX: Record<Kind, string> = { original: "personal data, masked", placeholder: "placeholder", restored: "put back" };

function Mark({ kind, type, children }: { kind: Kind; type: EntityType | null; children: ReactNode }) {
  return <mark className={`hl hl-${kind}`} data-kind={kind}>{children}<span className="sr-only"> ({metaFor(type).label} {SUFFIX[kind]})</span></mark>;
}

function fromSegments(segments: readonly RestoredSegment[], kind: Kind): ReactNode[] {
  return segments.map((s, i) => s.kind === "restored" ? <Mark key={i} kind={kind} type={s.entityType}>{s.text}</Mark> : <span key={i}>{s.text}</span>);
}

/** Your text, each value the guard masked marked. Aligned against the masked text, else the server's spans. */
export function OriginalText({ text, masked, entities = [] }: { text: string; masked: string; entities?: readonly { start: number; end: number; type: string }[] }) {
  const aligned = alignLoose(masked, text);
  if (aligned) return <>{fromSegments(aligned, "original")}</>;
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const e of [...entities].sort((a, b) => a.start - b.start)) {
    if (e.start < cursor || e.end > text.length) continue;
    if (e.start > cursor) parts.push(text.slice(cursor, e.start));
    parts.push(<Mark key={e.start} kind="original" type={e.type as EntityType}>{text.slice(e.start, e.end)}</Mark>);
    cursor = e.end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

/** What crossed to the model: placeholders marked. */
export function PlaceholderText({ text }: { text: string }) {
  return <>{tokenize(text).map((t, i) => t.kind === "text" ? <span key={i}>{t.text}</span> : <Mark key={i} kind="placeholder" type={t.entityType}>{t.text}</Mark>)}</>;
}

/**
 * The answer with the real values put back, each one marked. The values found in your text
 * (masked vs original) settle where each value ends, e.g. an e-mail followed by a full stop.
 */
export function RestoredAnswer({ answer, restored, masked, original }: { answer: string; restored: string; masked?: string; original?: string }) {
  const values = new Map<string, string>();
  if (masked !== undefined && original !== undefined) for (const s of alignLoose(masked, original) ?? []) if (s.kind === "restored") values.set(s.placeholder, s.text);
  const aligned = alignRestored(answer, restored, [], (placeholder) => values.get(placeholder)) ?? alignLoose(answer, restored);
  return aligned ? <>{fromSegments(aligned, "restored")}</> : <>{restored}</>;
}
