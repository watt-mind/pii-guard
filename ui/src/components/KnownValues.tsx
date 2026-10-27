import { useId } from "react";
import { TEXT_ENTITY_TYPES, type KnownValuesResponse, type TextEntityType } from "../api/types";
import { metaFor } from "../lib/entities";
import { Button } from "./ui";

import type { KnownRow } from "../lib/knownRows";
import { newKnownRow } from "../lib/knownRows";

interface Props {
  rows: KnownRow[];
  onRows: (rows: KnownRow[]) => void;
  counts: KnownValuesResponse | null;
  /** The row the guard refused, with its message. */
  error: { index: number; message: string } | null;
}


/** Values the application already knows are sensitive, pre-loaded into the session. */
export function KnownValues({ rows, onRows, counts, error }: Props) {
  const base = useId();
  const used = rows.filter((r) => r.value.trim() !== "");
  const set = (id: number, patch: Partial<KnownRow>) => onRows(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  return (
    <details className="group rounded-2xl border border-line bg-surface" open={rows.length > 0 || undefined}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
        <span>
          <span className="block text-sm font-semibold text-ink">
            Known values{used.length > 0 && <span className="ml-1.5 font-normal text-muted">({used.length})</span>}
          </span>
          <span className="block text-xs text-muted">
            Tell the guard about values you already know are sensitive (a customer record). They are masked in any inflected form, even when no detector finds them.
          </span>
        </span>
        <span aria-hidden="true" className="text-xs text-muted">
          <span className="group-open:hidden">Show</span>
          <span className="hidden group-open:inline">Hide</span>
        </span>
      </summary>
      <div className="space-y-3 border-t border-line px-4 py-4 sm:px-5">
        {rows.length > 0 && (
          <ul className="space-y-2">
            {rows.map((r, i) => {
              const refused = error?.index === i;
              const valueId = `${base}-v${r.id}`;
              const errId = `${base}-e${r.id}`;
              return (
                <li key={r.id} className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor={valueId} className="sr-only">
                      Known value {i + 1}
                    </label>
                    <input
                      id={valueId}
                      value={r.value}
                      onChange={(e) => set(r.id, { value: e.target.value })}
                      placeholder="Gyakorló Tihamér"
                      aria-invalid={refused || undefined}
                      aria-describedby={refused ? errId : undefined}
                      className={[
                        "h-9 min-w-0 flex-1 basis-40 rounded-lg border bg-surface-2 px-3 text-sm text-ink placeholder:text-faint focus:border-guard focus:outline-none",
                        refused ? "border-danger" : "border-line",
                      ].join(" ")}
                    />
                    <label className="sr-only" htmlFor={`${base}-t${r.id}`}>
                      Type of known value {i + 1}
                    </label>
                    <select
                      id={`${base}-t${r.id}`}
                      value={r.entity_type}
                      onChange={(e) => set(r.id, { entity_type: e.target.value as TextEntityType })}
                      className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink"
                    >
                      {TEXT_ENTITY_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {metaFor(t).label}
                        </option>
                      ))}
                    </select>
                    <Button variant="ghost" aria-label={`Remove known value ${i + 1}`} onClick={() => onRows(rows.filter((x) => x.id !== r.id))}>
                      Remove
                    </Button>
                  </div>
                  {refused && (
                    <p id={errId} className="text-xs text-danger">
                      Refused: {error.message}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={() => onRows([...rows, newKnownRow()])}>
            + Add a value
          </Button>
          {rows.length === 0 && (
            <Button variant="ghost" onClick={() => onRows([newKnownRow("Gyakorló Tihamér")])}>
              Try a fictional one
            </Button>
          )}
          {counts && used.length > 0 && (
            <p className="text-xs text-muted" data-testid="known-counts">
              Session: added {counts.added} / total {counts.total}
            </p>
          )}
        </div>
      </div>
    </details>
  );
}
