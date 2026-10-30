import { useId, useState } from "react";
import { COMPARISON, SETS } from "./proof";
import { Field, Select } from "../components/ui";

/** A small view of the same published results used by the hero; no benchmark index download. */
export function LandingBenchmarkChart() {
  const [dataset, setDataset] = useState(1);
  const id = useId();
  return <figure className="rounded-xl border border-line bg-surface p-4 sm:p-6" aria-labelledby={`${id}-title`} aria-describedby={`${id}-caption`}>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h3 id={`${id}-title`} className="text-base font-medium text-ink">Personal values leaked</h3>
        <p className="mt-1 text-xs text-muted">Lower is better · share of reference values left unmasked</p>
      </div>
      <div className="w-full sm:w-64"><Field label="Test dataset">
        <Select value={dataset} onChange={(e) => setDataset(Number(e.target.value))}>
          {SETS.map((label, index) => <option value={index} key={label}>{label}</option>)}
        </Select>
      </Field></div>
    </div>
    <ul className="mt-6 space-y-4" aria-label="Leak rate by tool">
      {COMPARISON.map((row) => <li key={row.system}>
        <div className="mb-1.5 flex items-baseline justify-between gap-4 text-sm">
          <span className={row.ours ? "font-medium text-ink" : "text-muted"}>{row.system}{row.ours && <span className="ml-2 text-xs font-normal text-muted">Rules + NER</span>}</span>
          <span className="font-mono tabular-nums text-ink">{row.leak[dataset]}%</span>
        </div>
        <div aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-surface-2">
          <div className={`h-full rounded-full ${row.ours ? "bg-primary" : "bg-field"}`} style={{ width: `${row.leak[dataset]}%` }} />
        </div>
      </li>)}
    </ul>
    <div aria-hidden="true" className="mt-3 flex justify-between font-mono text-xs tabular-nums text-faint"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
    <figcaption id={`${id}-caption`} className="mt-5 max-w-3xl text-xs text-muted">{SETS[dataset]} · published runs from 27–28 Oct 2026. Each tool is measured on the same dataset. These results describe these test sets, not a guarantee for your documents.</figcaption>
  </figure>;
}
