import type { ReactNode } from "react";
import type { EntityType } from "../api/types";
import { metaFor } from "../lib/entities";
import { alignLoose } from "../lib/placeholders";

/*
 * The landing's demo marks values the way the console does (ui/DESIGN.md, "Colour carries
 * meaning"): a value in your text and the placeholder that replaced it are masked blue
 * (`meta.mark`, `<Placeholder>` through `MaskedText`), and a value put back is restored green
 * (`RestoredText`). The type is always written out for screen readers.
 */

function Masked({ type, children }: { type: EntityType | null; children: ReactNode }) {
  const meta = metaFor(type);
  return <mark data-masked className={["rounded-md px-0.5 -mx-0.5 ring-1 ring-inset", meta.mark].join(" ")}>{children}<span className="sr-only"> ({meta.label}, masked)</span></mark>;
}

/** Your text, each value the guard masked marked. Aligned against the masked text, else the server's spans. */
export function YourText({ text, masked, entities = [] }: { text: string; masked: string; entities?: readonly { start: number; end: number; type: string }[] }) {
  const aligned = alignLoose(masked, text);
  const parts: ReactNode[] = [];
  if (aligned) aligned.forEach((s, i) => parts.push(s.kind === "restored" ? <Masked key={i} type={s.entityType}>{s.text}</Masked> : <span key={i}>{s.text}</span>));
  else {
    let cursor = 0;
    for (const e of [...entities].sort((a, b) => a.start - b.start)) {
      if (e.start < cursor || e.end > text.length) continue;
      if (e.start > cursor) parts.push(text.slice(cursor, e.start));
      parts.push(<Masked key={e.start} type={e.type as EntityType}>{text.slice(e.start, e.end)}</Masked>);
      cursor = e.end;
    }
    if (cursor < text.length) parts.push(text.slice(cursor));
  }
  return <div className="doc text-ink">{parts}</div>;
}
