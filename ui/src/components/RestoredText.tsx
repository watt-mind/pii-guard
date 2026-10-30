import type { ReactNode } from "react";
import type { EntityType } from "../api/types";
import { metaFor } from "../lib/entities";
import type { RestoredSegment } from "../lib/placeholders";
import { Placeholder } from "./Placeholder";

interface Props {
  segments: readonly RestoredSegment[];
  activeKey?: string | null;
  onActivate?: (key: string | null, anchor?: HTMLElement | null) => void;
  /** Index from which segments are new (animated) in a streaming run. */
  freshFrom?: number;
  /** Outgoing text (your own message): its marks were masked, not restored. */
  outgoing?: boolean;
  /**
   * Values detected but kept by policy, as UTF-16 offsets into the whole text (all segments
   * joined): outlined dashed, like the Mask screen does (LAB-1180).
   */
  kept?: readonly { entityType: EntityType; start: number; end: number }[];
}

/** A plain text segment starting at `offset`, with the kept values in it outlined. */
function withKept(text: string, offset: number, kept: Props["kept"], key: number): ReactNode {
  const inside = (kept ?? []).filter((k) => k.start >= offset && k.end <= offset + text.length).sort((a, b) => a.start - b.start);
  if (inside.length === 0) return <span key={key}>{text}</span>;
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const k of inside) {
    const start = k.start - offset;
    if (start < cursor) continue;
    if (start > cursor) parts.push(text.slice(cursor, start));
    const meta = metaFor(k.entityType);
    parts.push(
      <mark
        key={start}
        data-kept={k.entityType}
        className={[
          "rounded-md px-0.5 -mx-0.5",
          meta.mark,
          "bg-transparent! ring-0! outline outline-1 -outline-offset-1 outline-dashed outline-current/45",
        ].join(" ")}
      >
        {text.slice(start, k.end - offset)}
        <span className="sr-only"> ({meta.label}, kept by policy)</span>
      </mark>,
    );
    cursor = k.end - offset;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <span key={key}>{parts}</span>;
}

/** What you got back: the model's answer with the real values put back, each restored value marked. */
export function RestoredText({ segments, activeKey = null, onActivate, freshFrom = 0, outgoing = false, kept }: Props) {
  const starts = segments.reduce<number[]>((acc, seg, i) => [...acc, (acc[i] ?? 0) + seg.text.length], [0]);
  return (
    <div className="doc text-ink" data-testid="restored-text">
      {segments.map((seg, i) => {
        if (seg.kind === "text") return kept?.length ? withKept(seg.text, starts[i]!, kept, i) : <span key={i}>{seg.text}</span>;
        if (seg.kind === "unresolved") {
          return <Placeholder key={i} text={seg.text} entityType={seg.entityType} unresolved />;
        }
        const meta = metaFor(seg.entityType);
        const active = activeKey === seg.placeholder;
        return (
          <mark
            key={i}
            tabIndex={onActivate ? 0 : undefined}
            data-restored={seg.placeholder}
            data-active={active || undefined}
            onMouseEnter={onActivate ? (e) => onActivate(seg.placeholder, e.currentTarget) : undefined}
            onMouseLeave={onActivate ? () => onActivate(null) : undefined}
            onFocus={onActivate ? (e) => onActivate(seg.placeholder, e.currentTarget) : undefined}
            onBlur={onActivate ? () => onActivate(null) : undefined}
            className={[
              "rounded-md px-0.5 -mx-0.5 ring-1 ring-inset",
              outgoing ? meta.mark : "bg-restored-soft text-ink ring-restored/45",
              onActivate ? "cursor-help" : "",
              i >= freshFrom ? "animate-restore" : "",
              active ? "ring-2 outline-2 outline-offset-2 outline-current" : "",
            ].join(" ")}
          >
            {seg.text}
            <span className="sr-only"> ({meta.label}, {outgoing ? "masked as" : "restored from"} {seg.placeholder})</span>
          </mark>
        );
      })}
    </div>
  );
}
