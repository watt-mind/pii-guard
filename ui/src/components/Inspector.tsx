import type { EntityType } from "../api/types";
import { detectorLabel, metaFor } from "../lib/entities";

export interface InspectorInfo {
  entityType: EntityType | null;
  placeholder: string | null;
  detector?: string;
  score?: number;
  occurrences?: number;
  /** False when the value was masked even though no placeholder could be linked to it. */
  kept?: boolean;
}

interface Props {
  info: InspectorInfo | null;
  hint: string;
}

/** A one-line readout for the entity under the cursor or keyboard focus. Never shows a value. */
export function Inspector({ info, hint }: Props) {
  return (
    <div aria-live="polite" className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1">
      {info ? (
        <>
          <span className="inline-flex items-center gap-1.5 font-medium text-ink">
            <span aria-hidden="true" className={["size-2 rounded-full", metaFor(info.entityType).swatch].join(" ")} />
            {metaFor(info.entityType).label}
          </span>
          <span>{info.placeholder ? <>masked as <code className="font-mono text-ink">{info.placeholder}</code></> : info.kept === false ? "masked" : "kept (policy: keep)"}</span>
          {info.detector && <span>found by {detectorLabel(info.detector, { types: info.entityType ? [info.entityType] : [] })}</span>}
          {info.score !== undefined && info.detector !== "demo" && (
            <span className="inline-flex items-center gap-1.5">
              confidence
              <span aria-hidden="true" className="inline-block h-1.5 w-12 overflow-hidden rounded-full bg-line">
                <span className="block h-full rounded-full bg-ink" style={{ width: `${Math.round(info.score * 100)}%` }} />
              </span>
              <span className="tabular-nums text-ink">{Math.round(info.score * 100)}%</span>
            </span>
          )}
          {info.occurrences !== undefined && info.occurrences > 1 && <span>{info.occurrences} occurrences</span>}
        </>
      ) : (
        <span>{hint}</span>
      )}
    </div>
  );
}
