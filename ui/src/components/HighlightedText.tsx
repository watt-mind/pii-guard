import type { ReactNode } from "react";
import { describeSpan, spanKey, type LocalSpan } from "../lib/analysis";
import { metaFor } from "../lib/entities";

interface Props {
  text: string;
  spans: readonly LocalSpan[];
  activeKey: string | null;
  onActivate: (key: string | null, anchor?: HTMLElement | null) => void;
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
    const kept = span.placeholder === null;
    parts.push(
      <mark
        key={`${span.start}-${i}`}
        tabIndex={0}
        data-entity={span.entityType}
        data-active={active || undefined}
        onMouseEnter={(e) => onActivate(key, e.currentTarget)}
        onMouseLeave={() => onActivate(null)}
        onFocus={(e) => onActivate(key, e.currentTarget)}
        onBlur={() => onActivate(null)}
        className={[
          "rounded-[5px] px-0.5 -mx-0.5 ring-1 ring-inset transition-shadow cursor-help",
          meta.mark,
          kept ? "bg-transparent! ring-0! outline outline-1 -outline-offset-1 outline-dashed outline-current/45" : "",
          active ? "ring-2 shadow-[0_0_0_3px_var(--canvas),0_0_0_5px_currentColor]" : "",
        ].join(" ")}
      >
        {text.slice(span.start, span.end)}
        <span className="sr-only"> ({describeSpan(span)})</span>
      </mark>,
    );
    cursor = span.end;
    if (span.detector === "known") {
      // The badge goes after the whole word, so an inflectional suffix stays visibly outside the value.
      const suffix = /^\p{L}*/u.exec(text.slice(span.end))?.[0] ?? "";
      const next = spans[i + 1];
      const keep = next && next.start < span.end + suffix.length ? "" : suffix;
      if (keep) parts.push(keep);
      parts.push(
        <span
          key={`known-${span.start}`}
          aria-hidden="true"
          data-known
          className="ml-1 inline-block translate-y-[-1px] rounded bg-guard-soft px-1 align-middle font-sans text-[10px] leading-4 font-semibold tracking-wide text-guard-ink uppercase ring-1 ring-guard/40"
        >
          known
        </span>,
      );
      cursor += keep.length;
    }
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <div className="doc text-ink">{parts}</div>;
}
