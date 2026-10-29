import type { MaskedEntity } from "../api/types";
import type { LocalSpan } from "../lib/analysis";
import { detectorLabel, metaFor } from "../lib/entities";
import { Placeholder } from "./Placeholder";

interface Props {
  entities: readonly MaskedEntity[];
  spans: readonly LocalSpan[];
  activeKey: string | null;
  onActivate: (key: string | null, anchor?: HTMLElement | null) => void;
}

/**
 * Placeholder ↔ type mapping for the session. Deliberately has no "value"
 * column: original values are only ever visible in the input pane.
 */
export function EntityTable({ entities, spans, activeKey, onActivate }: Props) {
  if (entities.length === 0) {
    return <p className="text-sm text-muted">Nothing was masked in this document.</p>;
  }
  return (
    // Focusable, so a keyboard can scroll the table sideways on a phone.
    <div tabIndex={0} role="region" aria-label="Placeholders issued" className="-mx-4 overflow-x-auto sm:mx-0">
      <table className="w-full min-w-[30rem] border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">Placeholders issued for this session. Original values are not listed.</caption>
        <thead>
          <tr className="text-xs text-faint">
            <th scope="col" className="border-b border-line px-4 py-2 font-medium sm:pl-0">
              Placeholder
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-medium">
              Type
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 text-right font-medium">
              Replaced
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-medium">
              Found by
            </th>
            <th scope="col" className="border-b border-line px-4 py-2 text-right font-medium sm:pr-0">
              Confidence
            </th>
          </tr>
        </thead>
        <tbody>
          {entities.map((e) => {
            const own = spans.filter((s) => s.placeholder === e.placeholder);
            const detectors = [...new Set(own.map((s) => detectorLabel(s.detector, { types: [s.entityType] })))];
            const scored = own.filter((s) => s.detector !== "demo");
            const best = scored.length ? Math.max(...scored.map((s) => s.score)) : null;
            const active = activeKey === e.placeholder;
            return (
              <tr
                key={e.placeholder}
                data-active={active || undefined}
                onMouseEnter={() => onActivate(e.placeholder)}
                onMouseLeave={() => onActivate(null)}
                className={active ? "bg-surface-2" : ""}
              >
                <td className="border-b border-line px-4 py-2 sm:pl-0">
                  <Placeholder text={e.placeholder} entityType={e.entity_type} active={active} />
                </td>
                <td className="border-b border-line px-3 py-2 text-ink">{metaFor(e.entity_type).label}</td>
                <td className="border-b border-line px-3 py-2 text-right tabular-nums text-muted">{e.count}×</td>
                <td className="border-b border-line px-3 py-2 text-muted">{detectors.join(", ") || "—"}</td>
                <td className="border-b border-line px-4 py-2 text-right tabular-nums text-muted sm:pr-0">
                  {best === null ? "—" : `${Math.round(best * 100)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
