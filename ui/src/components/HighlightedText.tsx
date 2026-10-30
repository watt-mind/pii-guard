import type { ReactNode } from "react";
import { describeSpan, isKept, spanKey, type LocalSpan } from "../lib/analysis";
import { metaFor } from "../lib/entities";
import { activationHandlers, type ActivateHandler } from "../lib/placeholders";

interface Props {
  text: string;
  spans: readonly LocalSpan[];
  activeKey: string | null;
  onActivate: ActivateHandler;
}

const KEPT_MARK_CLASS = "bg-transparent! ring-0! outline outline-1 -outline-offset-1 outline-dashed outline-current/45";
const ACTIVE_MARK_CLASS = "ring-2 outline-2 outline-offset-2 outline-current";

function appendKnownWordBadge(parts: ReactNode[], text: string, span: LocalSpan, next: LocalSpan | undefined): number {
  // The badge goes after the whole word, so an inflectional suffix stays visibly outside the value.
  const suffix = /^\p{L}*/u.exec(text.slice(span.end))?.[0] ?? "";
  const keep = next && next.start < span.end + suffix.length ? "" : suffix;
  if (keep) parts.push(keep);
  parts.push(
    <span
      key={`known-${span.start}`}
      aria-hidden="true"
      data-known
      className="ml-1 inline-block -translate-y-px rounded-sm bg-surface-2 px-1 align-middle font-mono text-2xs leading-4 text-muted ring-1 ring-line-strong"
    >
      known
    </span>,
  );
  return keep.length;
}

/** The user's own document with every detected span marked. Values are shown only here. */
export function HighlightedText({ text, spans, activeKey, onActivate }: Props) {
  const parts: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, i) => {
    if (span.start < cursor) return; // overlapping spans are merged by the resolver; skip defensively
    if (span.start > cursor) parts.push(text.slice(cursor, span.start));
    const meta = metaFor(span.entityType);
    const key = spanKey(span);
    const active = key === activeKey;
    parts.push(
      <mark
        key={`${span.start}-${i}`}
        data-entity={span.entityType}
        data-active={active || undefined}
        {...activationHandlers(key, onActivate)}
        className={[
          "rounded-md px-0.5 -mx-0.5 ring-1 ring-inset transition-shadow cursor-help",
          meta.mark,
          isKept(span) ? KEPT_MARK_CLASS : "",
          active ? ACTIVE_MARK_CLASS : "",
        ].join(" ")}
      >
        {text.slice(span.start, span.end)}
        <span className="sr-only"> ({describeSpan(span)})</span>
      </mark>,
    );
    cursor = span.end;
    if (span.detector === "known") {
      cursor += appendKnownWordBadge(parts, text, span, spans[i + 1]);
    }
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <div className="doc text-ink">{parts}</div>;
}
