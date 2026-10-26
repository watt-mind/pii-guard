import type { EntityType } from "../api/types";
import { ENTITY_META } from "../lib/entities";

interface Props {
  counts: ReadonlyMap<EntityType, number>;
  /** Types that were detected but left in place by policy. */
  kept?: ReadonlySet<EntityType>;
  /** Highlight a type (e.g. the one under the cursor). */
  activeType?: EntityType | null;
}

/** Entity types present in the current document, with their colour and policy. */
export function Legend({ counts, kept: keptTypes, activeType = null }: Props) {
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  return (
    <ul aria-label="Entity legend" className="flex flex-wrap gap-1.5">
      {entries.map(([type, n]) => {
        const meta = ENTITY_META[type];
        const kept = keptTypes ? keptTypes.has(type) : meta.policy === "keep";
        return (
          <li
            key={type}
            data-active={activeType === type || undefined}
            className={[
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
              activeType === type ? "border-ink text-ink" : "border-line text-muted",
            ].join(" ")}
          >
            <span
              aria-hidden="true"
              className={["size-2.5 rounded-full", meta.swatch, kept ? "opacity-50 ring-1 ring-current ring-dashed" : ""].join(" ")}
            />
            <span className="font-medium text-ink">{meta.label}</span>
            <span className="tabular-nums">{n}</span>
            {kept && (
              <span className="rounded bg-surface-2 px-1 text-[10px] font-semibold tracking-wide text-faint uppercase">
                kept
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
