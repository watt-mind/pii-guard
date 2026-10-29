import type { EntityType } from "../api/types";
import { ENTITY_META } from "../lib/entities";

interface Props {
  counts: ReadonlyMap<EntityType, number>;
  /** Types that were detected but left in place by policy. */
  kept?: ReadonlySet<EntityType>;
  /** Highlight a type (e.g. the one under the cursor). */
  activeType?: EntityType | null;
  /** How many spans came from pre-loaded known values. */
  known?: number;
}

/** Entity types present in the current document, with their colour and policy. */
export function Legend({ counts, kept: keptTypes, activeType = null, known = 0 }: Props) {
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
              "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors",
              activeType === type ? "border-ink text-ink" : "border-line text-muted",
            ].join(" ")}
          >
            <span
              aria-hidden="true"
              className={["size-2 rounded-full", kept ? "border border-dashed border-kept" : meta.swatch].join(" ")}
            />
            <span className="font-medium text-ink">{meta.label}</span>
            <span className="tabular-nums">{n}</span>
            {kept && (
              <span className="font-mono text-2xs text-kept-ink">kept</span>
            )}
          </li>
        );
      })}
      {known > 0 && (
        <li className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-muted">
          <span className="rounded-sm bg-surface-2 px-1 font-mono text-2xs ring-1 ring-line-strong">known</span>
          <span className="font-medium text-ink">from your known values</span>
          <span className="tabular-nums">{known}</span>
        </li>
      )}
    </ul>
  );
}
