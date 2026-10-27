import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  documentCount,
  formatMs,
  formatPct,
  languageName,
  loadBenchmarks,
  originLabel,
  pick,
  snapshotsFor,
  systemsOn,
  textSets,
  type BenchmarkIndex,
  type BenchmarkLoader,
  type LanguageFilter,
  type Metrics,
  type Snapshot,
} from "../api/benchmarks";
import { LanguageBars, LeakLatencyChart, MarkerIcon, ProgressChart, TypeHeatmap } from "./BenchmarksCharts";

type Load = { state: "loading" } | { state: "ready"; index: BenchmarkIndex } | { state: "error"; message: string };

/**
 * Every recorded evaluation run, browsable: the same data as docs/benchmarks.md, read from
 * the index bundled at build time (so it works in demo mode, without the API).
 */
export function Benchmarks({ load = loadBenchmarks }: { load?: BenchmarkLoader }) {
  const [data, setData] = useState<Load>({ state: "loading" });
  useEffect(() => {
    let live = true;
    load().then(
      (index) => live && setData({ state: "ready", index }),
      (err: unknown) => live && setData({ state: "error", message: err instanceof Error ? err.message : String(err) }),
    );
    return () => {
      live = false;
    };
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">How much gets through, measured on every run.</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          Each evaluation run of pii-guard, and of the open-source tools it is compared with, is recorded with its commit, models, fixtures and hardware. All test documents are fictional.
        </p>
      </div>
      {data.state === "loading" && (
        <p role="status" className="text-sm text-muted">
          Loading benchmark results…
        </p>
      )}
      {data.state === "error" && (
        <div role="alert" className="rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm">
          <p className="font-semibold text-danger">The benchmark results could not be loaded.</p>
          <p className="mt-1 text-muted">{data.message}</p>
        </div>
      )}
      {data.state === "ready" && <Explorer index={data.index} />}
    </div>
  );
}

function Explorer({ index }: { index: BenchmarkIndex }) {
  const sets = useMemo(() => textSets(index), [index]);
  const [set, setSet] = useState(sets[0] ?? "");
  const [lang, setLang] = useState<LanguageFilter>("all");
  const available = useMemo(() => systemsOn(index, set), [index, set]);
  const featured = useMemo(() => available.filter((k) => index.systems[k]?.featured), [available, index]);
  const [chosen, setChosen] = useState<string[] | null>(null); // null: the featured systems
  const selected = (chosen ?? (featured.length ? featured : available)).filter((k) => available.includes(k));
  const info = index.fixture_sets[set];
  const languages = info?.languages ?? [];
  const snapshots = snapshotsFor(index, set, selected);
  const history = index.history.filter(
    (h) => h.fixture_set === set && selected.includes(h.system) && index.systems[h.system]?.family === "pii-guard",
  );
  const lastRun = index.runs.length ? index.runs[index.runs.length - 1]!.date : "–";

  const toggle = (k: string) => {
    const base = selected;
    setChosen(base.includes(k) ? base.filter((x) => x !== k) : available.filter((x) => base.includes(x) || x === k));
  };

  return (
    <>
      <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Fact label="Runs" value={index.runs.length} />
        <Fact label="Systems" value={Object.keys(index.systems).length} />
        <Fact label="Fixture sets" value={`${sets.length} text + ${Object.values(index.fixture_sets).filter((f) => f.kind === "visual").length} image`} />
        <Fact label="Latest run" value={lastRun} />
      </dl>

      <section aria-label="Filters" className="space-y-4 rounded-2xl border border-line bg-surface p-4 sm:p-5">
        <Segmented
          label="Fixture set"
          value={set}
          options={sets.map((s) => ({ id: s, label: s, hint: index.fixture_sets[s]?.origin === "generated" ? "generated" : "hand-written" }))}
          onChange={(s) => {
            setSet(s);
            if (lang !== "all" && !index.fixture_sets[s]?.languages.includes(lang)) setLang("all");
          }}
        />
        <Segmented
          label="Language"
          value={lang}
          options={[{ id: "all", label: "All, pooled" }, ...languages.map((l) => ({ id: l, label: languageName(l) }))]}
          onChange={setLang}
        />
        <fieldset className="min-w-0">
          <legend className="mb-2 flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-xs font-semibold tracking-[0.08em] text-faint uppercase">
            Systems
            <span className="flex gap-1 font-medium tracking-normal normal-case">
              <button type="button" className="rounded px-1.5 py-0.5 text-muted underline-offset-2 hover:text-ink hover:underline" onClick={() => setChosen(null)}>
                Featured
              </button>
              <button type="button" className="rounded px-1.5 py-0.5 text-muted underline-offset-2 hover:text-ink hover:underline" onClick={() => setChosen(available)}>
                All
              </button>
            </span>
          </legend>
          <div className="space-y-2">
            {(["pii-guard", "comparison"] as const).map((family) => {
              const keys = available.filter((k) => index.systems[k]?.family === family);
              if (!keys.length) return null;
              return (
                <div key={family} className="flex flex-wrap items-center gap-1.5">
                  <span className="w-full text-xs text-muted sm:w-28 sm:shrink-0">{family === "pii-guard" ? "pii-guard" : "Open-source tools"}</span>
                  {keys.map((k) => {
                    const sys = index.systems[k];
                    const on = selected.includes(k);
                    return (
                      <label
                        key={k}
                        title={sys?.label}
                        className={[
                          "inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink",
                          on ? "border-ink bg-surface-2 text-ink" : "border-line text-muted hover:border-line-strong",
                        ].join(" ")}
                      >
                        <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(k)} />
                        <MarkerIcon info={sys} />
                        {sys?.short_label ?? k}
                        {sys?.default && <span className="rounded bg-guard-soft px-1 text-[10px] font-semibold text-guard-ink uppercase">default</span>}
                      </label>
                    );
                  })}
                </div>
              );
            })}
            {Object.values(index.systems).some((v) => v.family === "comparison") && !available.some((k) => index.systems[k]?.family === "comparison") && (
              <p className="text-xs text-muted">The open-source tools weren’t run on this set; pick another set to compare with them.</p>
            )}
          </div>
        </fieldset>
      </section>

      <p className="text-sm text-muted">
        <span className="font-medium text-ink">{set}</span>: {originLabel(info)},{" "}
        {lang === "all"
          ? languages.map((l) => `${info?.documents[l] ?? "?"} ${languageName(l)}`).join(" + ") + " documents"
          : `${documentCount(info, lang) ?? "?"} ${languageName(lang)} documents`}
        . Small sets: a few points of difference is noise.
      </p>
      {info?.origin === "generated" && (
        <p role="note" className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
          <strong className="font-semibold text-warn">Generated set.</strong> These documents were written by a Muse model, the same family as pii-guard's LLM detector, which flatters
          Muse-based detection, and fine-tuned detectors may have been trained on similar generated text (see the run notes under the
          results). The hand-written set has neither bias.
        </p>
      )}

      {selected.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-muted">Pick at least one system to compare.</p>
      ) : (
        <>
          <Section id="bench-table" title="Results" note="Latest run of each system. Leak = labelled values still readable after masking.">
            <ResultsTable snapshots={snapshots} index={index} lang={lang} />
            <RunNotes key={set} snapshots={snapshots} index={index} open={info?.origin === "generated"} />
          </Section>
          <Section id="bench-scatter" title="Leak rate vs latency" note="Down and left is better. Latency was measured where each system ran, so it is not a like-for-like speed test.">
            <LeakLatencyChart points={snapshots.flatMap((s) => {
              const m = pick(s, lang);
              return m ? [{ key: s.system, info: index.systems[s.system], metrics: m }] : [];
            })} />
          </Section>
          <Section id="bench-lang" title="By language" note="The same fixture set in each language.">
            <LanguageBars snapshots={snapshots} systems={index.systems} languages={languages} />
          </Section>
          <Section id="bench-progress" title="Leak rate over time" note="Each pii-guard configuration, run by run. Dashed: the best result of any configuration so far, so a drop can mean a new configuration rather than an improved one.">
            <ProgressChart history={history} systems={index.systems} lang={lang} />
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              {[...new Set(history.map((h) => h.system))].map((k) => (
                <li key={k} className="flex items-center gap-1.5">
                  <MarkerIcon info={index.systems[k]} />
                  {index.systems[k]?.short_label ?? k}
                </li>
              ))}
            </ul>
          </Section>
          <Section id="bench-types" title="Recall per entity type" note="Share of labelled values of each type found (overlap), in %.">
            <TypeHeatmap snapshots={snapshots} systems={index.systems} types={index.entity_types} lang={lang} />
          </Section>
        </>
      )}

      {index.visual.length > 0 && (
        <Section id="bench-visual" title="Image masking" note="Share of labelled regions on official specimen ID documents masked (IoU ≥ 0.5).">
          <VisualTable index={index} />
        </Section>
      )}

      <details className="group rounded-2xl border border-line bg-surface">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-ink sm:px-5">
          <span className="mr-1.5 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
            ›
          </span>
          Run log ({index.runs.length} runs)
        </summary>
        <RunLog index={index} />
      </details>
      <p className="text-xs text-faint">
        Generated by <code className="font-mono">pii-guard eval report</code> from <code className="font-mono">eval/results/runs/</code>. Add a run with{" "}
        <code className="font-mono">pii-guard eval --record &lt;slug&gt;</code>.
      </p>
    </>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col-reverse">
      <dt className="text-[10px] tracking-wide text-faint uppercase">{label}</dt>
      <dd className="font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string; hint?: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs font-semibold tracking-[0.08em] text-faint uppercase">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <label
            key={o.id}
            className={[
              "inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink",
              value === o.id ? "border-ink bg-ink text-canvas" : "border-line text-ink hover:border-line-strong",
            ].join(" ")}
          >
            <input type="radio" className="sr-only" name={label} checked={value === o.id} onChange={() => onChange(o.id)} />
            {o.label}
            {o.hint && <span className={["text-xs", value === o.id ? "opacity-75" : "text-faint"].join(" ")}>{o.hint}</span>}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Section({ id, title, note, children }: { id: string; title: string; note: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-title`} className="rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <h2 id={`${id}-title`} className="text-base font-semibold tracking-tight text-ink">
        {title}
      </h2>
      <p className="mt-0.5 mb-4 text-sm text-muted">{note}</p>
      {children}
    </section>
  );
}

type SortKey = "f1" | "leak" | "partial_leak" | "over_masking" | "detect_p50_ms" | "precision" | "recall" | "roundtrip";

const COLUMNS: { key: SortKey; label: string; better: "high" | "low" }[] = [
  { key: "leak", label: "Leak", better: "low" },
  { key: "partial_leak", label: "Partial leak", better: "low" },
  { key: "f1", label: "F1", better: "high" },
  { key: "precision", label: "Precision", better: "high" },
  { key: "recall", label: "Recall", better: "high" },
  { key: "over_masking", label: "Over-masking", better: "low" },
  { key: "roundtrip", label: "Round trip", better: "high" },
  { key: "detect_p50_ms", label: "Latency p50", better: "low" },
];

function ResultsTable({ snapshots, index, lang }: { snapshots: Snapshot[]; index: BenchmarkIndex; lang: LanguageFilter }) {
  // Each column first sorts best-first (lowest leak, highest F1); clicking again reverses.
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "leak", dir: "asc" });
  const onSort = (c: (typeof COLUMNS)[number]) =>
    setSort((prev) =>
      prev.key === c.key ? { key: c.key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: c.better === "low" ? "asc" : "desc" },
    );
  const rows = snapshots
    .map((s) => ({ s, m: pick(s, lang) }))
    .sort((a, b) => {
      const va = a.m?.[sort.key] ?? null;
      const vb = b.m?.[sort.key] ?? null;
      if (va === null) return vb === null ? 0 : 1; // not run / not measured: always last
      if (vb === null) return -1;
      return sort.dir === "asc" ? va - vb : vb - va;
    });
  const best = (key: keyof Metrics, dir: "high" | "low") => {
    const vals = rows.map((r) => r.m?.[key]).filter((v): v is number => typeof v === "number");
    return vals.length ? (dir === "low" ? Math.min(...vals) : Math.max(...vals)) : null;
  };

  return (
    <div
      role="region"
      aria-label="Results table, scrolls sideways"
      tabIndex={0}
      className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0"
    >
      <table className="w-full min-w-max text-sm">
        <caption className="sr-only">
          Results per system, sorted by {COLUMNS.find((c) => c.key === sort.key)!.label}, {sort.dir === "asc" ? "lowest" : "highest"} first
        </caption>
        <thead>
          <tr className="border-b border-line text-left text-xs text-faint">
            <th scope="col" className="sticky left-0 z-10 bg-surface py-2 pr-3 font-semibold">
              System
            </th>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                className="px-2 py-2 text-right font-semibold whitespace-nowrap"
                aria-sort={c.key === sort.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                <button
                  type="button"
                  onClick={() => onSort(c)}
                  className={["inline-flex items-center gap-1 rounded hover:text-ink", c.key === sort.key ? "text-ink" : ""].join(" ")}
                >
                  {c.label}
                  <span aria-hidden="true" className={["w-2.5 text-[10px]", c.key === sort.key ? "" : "opacity-0"].join(" ")}>
                    {sort.dir === "asc" ? "▲" : "▼"}
                  </span>
                </button>
              </th>
            ))}
            <th scope="col" className="px-2 py-2 text-left font-semibold">
              Run
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ s, m }) => {
            const sys = index.systems[s.system];
            return (
              <tr key={s.system} className="border-b border-line last:border-0">
                <th scope="row" className="sticky left-0 z-10 bg-surface py-2 pr-3 text-left font-medium whitespace-nowrap text-ink">
                  <span className="flex items-center gap-1.5">
                    <MarkerIcon info={sys} />
                    {sys?.short_label ?? s.system}
                    {sys?.default && <span className="sr-only"> (default pipeline)</span>}
                  </span>
                </th>
                {COLUMNS.map((c) => {
                  const v = m?.[c.key] ?? null;
                  const top = v !== null && v === best(c.key, c.better) && rows.length > 1;
                  return (
                    <td key={c.key} className={["px-2 py-2 text-right tabular-nums whitespace-nowrap", top ? "font-semibold text-guard-ink" : "text-ink"].join(" ")}>
                      {m === null ? <span className="text-faint">not run</span> : c.key === "detect_p50_ms" ? formatMs(v) + (m.latency_pooled ? "*" : "") : formatPct(v)}
                    </td>
                  );
                })}
                <td className="px-2 py-2 text-xs whitespace-nowrap text-muted">
                  {s.dates.join(", ")} <code className="font-mono">{s.commits.map((c) => c.slice(0, 7)).join(", ")}</code>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-faint">
        Click a column to sort; click again to reverse. – means not measured (a tool that can’t unmask has no round trip).
        {rows.some((r) => r.m?.latency_pooled) && " * averaged over several runs (percentiles can’t be pooled exactly)."}
      </p>
    </div>
  );
}

/** Where each result ran and what to keep in mind (training data overlap, remote API …). */
function RunNotes({ snapshots, index, open }: { snapshots: Snapshot[]; index: BenchmarkIndex; open: boolean }) {
  const runs = new Map(index.runs.map((r) => [r.run_id, r]));
  const items = snapshots
    .map((s) => {
      const rs = s.run_ids.map((id) => runs.get(id)).filter((r) => r !== undefined);
      const hardware = [...new Set(rs.map((r) => r.hardware).filter((h): h is string => !!h))];
      const notes = [...new Set(rs.flatMap((r) => r.notes))];
      return { s, hardware, notes };
    })
    .filter((i) => i.hardware.length || i.notes.length);
  if (!items.length) return null;
  return (
    <details open={open} className="mt-4 rounded-xl border border-line bg-surface-2">
      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">Where these ran, and caveats</summary>
      <ul className="space-y-2 border-t border-line px-3 py-3 text-xs">
        {items.map(({ s, hardware, notes }) => (
          <li key={s.system}>
            <p className="flex items-center gap-1.5 font-medium text-ink">
              <MarkerIcon info={index.systems[s.system]} />
              {index.systems[s.system]?.short_label ?? s.system}
              {hardware.length > 0 && <span className="font-normal text-muted">· {hardware.join("; ")}</span>}
            </p>
            {notes.length > 0 && <p className="mt-0.5 pl-5 text-muted">{notes.join(" ")}</p>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function VisualTable({ index }: { index: BenchmarkIndex }) {
  const types = [...new Set(index.visual.flatMap((r) => Object.keys(r.by_region_type)))];
  return (
    <div
      role="region"
      aria-label="Image masking table, scrolls sideways"
      tabIndex={0}
      className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0"
    >
      <table className="w-full min-w-max text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-faint">
            <th scope="col" className="py-2 pr-3 font-semibold">
              Run
            </th>
            <th scope="col" className="px-2 py-2 text-right font-semibold">
              Images
            </th>
            {types.map((t) => (
              <th key={t} scope="col" className="px-2 py-2 text-right font-semibold">
                {t}
              </th>
            ))}
            <th scope="col" className="px-2 py-2 text-right font-semibold">
              All regions
            </th>
          </tr>
        </thead>
        <tbody>
          {index.visual.map((r) => (
            <tr key={r.run_id} className="border-b border-line last:border-0">
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                <span className="block font-medium text-ink">{r.run_id.replace(`${r.date}-`, "").replace(/-/g, " ")}</span>
                <span className="text-xs text-muted">
                  {r.date} · {r.countries} countries
                </span>
              </th>
              <td className="px-2 py-2 text-right tabular-nums">{r.specimens}</td>
              {types.map((t) => (
                <td key={t} className="px-2 py-2 text-right tabular-nums">
                  {formatPct(r.by_region_type[t]?.recall_iou50, 0)}
                </td>
              ))}
              <td className="px-2 py-2 text-right font-semibold tabular-nums">{formatPct(r.overall.recall_iou50, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunLog({ index }: { index: BenchmarkIndex }) {
  return (
    <ol className="divide-y divide-line border-t border-line">
      {[...index.runs].reverse().map((r) => (
        <li key={r.run_id} className="px-4 py-3 text-sm sm:px-5">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium text-ink">{index.systems[r.system]?.label ?? r.system}</span>
            <span className="text-muted">on {r.fixture_set}</span>
            {r.languages.length > 0 && <span className="text-muted">({r.languages.join(", ")})</span>}
            <span
              className={[
                "rounded px-1.5 text-[10px] font-semibold uppercase",
                r.source === "imported" ? "bg-surface-2 text-muted ring-1 ring-line" : "bg-guard-soft text-guard-ink",
              ].join(" ")}
            >
              {r.source}
            </span>
          </p>
          <p className="mt-0.5 text-xs break-words text-muted">
            {r.date} · <code className="font-mono">{r.commit.slice(0, 7)}</code>
            {r.dirty ? " (uncommitted changes)" : ""}
            {r.hardware ? ` · ${r.hardware}` : ""}
            {r.cost?.usd != null ? ` · ${r.cost.estimated ? "≈ " : ""}$${r.cost.usd.toFixed(2)}` : ""}
            {r.cost?.gpu_minutes != null ? ` · ${r.cost.gpu_minutes} GPU-min` : ""}
          </p>
          {r.notes.length > 0 && <p className="mt-1 text-xs break-words text-faint">{r.notes.join(" ")}</p>}
        </li>
      ))}
    </ol>
  );
}
