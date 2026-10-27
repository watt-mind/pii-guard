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
}

/** What you got back: the model's answer with the real values put back, each restored value marked. */
export function RestoredText({ segments, activeKey = null, onActivate, freshFrom = 0, outgoing = false }: Props) {
  return (
    <div className="doc text-ink" data-testid="restored-text">
      {segments.map((seg, i) => {
        if (seg.kind === "text") return <span key={i}>{seg.text}</span>;
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
