import { Fragment, useState, type ReactNode } from "react";
import {
  FAST_MODE_SYSTEM,
  coverageTag,
  documentCount,
  formatMs,
  formatPct,
  headline,
  languageName,
  originKind,
  pick,
  readerNote,
  visualRunLabel,
  type BenchmarkIndex,
  type FixtureSetInfo,
  type Headline as HeadlineResult,
  type HeadlineSide,
  type LanguageFilter,
  type Metrics,
  type RunInfo,
  type Snapshot,
  type SystemInfo,
} from "../api/benchmarks";
import { Button, SegmentedControl } from "../components/ui";
import { MarkerIcon } from "./BenchmarksCharts";

/** Internal ticket ids ("(LAB-1150)", ", LAB-1128)") are maintainer context, not reader copy. */
function stripTickets(text: string): string {
  return text
    .replace(/,\s*LAB-\d+(?=\))/g, "")
    .replace(/\s*\(LAB-\d+\)/g, "")
    .replace(/\bLAB-\d+:?\s*/g, "")
    .replace(/\bpii-guard(?= (?:NER|rules|fast|audit|LLM|gateway)\b)/g, "PII Guard")
    .trim();
}

const datasetLabels: Record<string, string> = {
  "gretel-finance": "Gretel",
  "gretel-finance-corrected": "Gretel fixed",
  "nemotron-pii": "Nemotron",
  "mapa-eur-lex": "MAPA",
  "pl-pii-bench": "PL PII",
};

export type AcrossRow = { set: string; h: HeadlineResult | null | undefined };

export type SortKey = "f1" | "leak" | "partial_leak" | "over_masking" | "detect_p50_ms" | "precision" | "recall" | "roundtrip";

export type SortState = { key: SortKey; dir: "asc" | "desc" };

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

function nextSortState(prev: SortState, c: (typeof COLUMNS)[number]): SortState {
  if (prev.key === c.key) return { key: c.key, dir: prev.dir === "asc" ? "desc" : "asc" };
  return { key: c.key, dir: c.better === "low" ? "asc" : "desc" };
}

export function SystemChip({ id, info, on, onToggle }: { id: string; info: SystemInfo | undefined; on: boolean; onToggle: () => void }) {
  const tone = on ? "border-ink bg-surface-2 text-ink" : "border-line text-muted hover:border-line-strong";
  return (
    <label
      title={info?.label}
      className={`relative inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink ${tone}`}
    >
      <input type="checkbox" className="sr-only" checked={on} onChange={onToggle} />
      <MarkerIcon info={info} />
      {info?.short_label ?? id}
      {id === FAST_MODE_SYSTEM && <FastModeTag />}
    </label>
  );
}

export function FastModeTag() {
  return (
    <span
      title="Rules + the published on-device NER v4.2: the gateway's fast mode, its production path. Without a NER checkpoint, fast mode runs the rules alone."
      className="rounded-sm bg-guard-soft px-1 font-mono text-2xs whitespace-nowrap text-guard-ink ring-1 ring-guard/40"
    >
      fast mode
    </span>
  );
}

function datasetDisplayLabel(set: string): string {
  return datasetLabels[set] ?? set.replace(/-/g, " ");
}

function AcrossSetHeaderCell({ set, info, isHeadline, on, onPick }: { set: string; info: FixtureSetInfo | undefined; isHeadline: boolean; on: boolean; onPick: (set: string) => void }) {
  if (!info) {
    return (
      <th scope="row" className="py-1.5 pr-3 text-left font-normal">
        <span className="block h-4 w-28 animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
      </th>
    );
  }
  const label = datasetDisplayLabel(set);
  const langs = info.languages.map((l) => l.toUpperCase()).join(" ");
  return (
    <th scope="row" className="py-1.5 pr-3 text-left font-normal">
      <button
        type="button"
        onClick={() => onPick(set)}
        title={set}
        aria-label={`${label} (${set})`}
        aria-current={on ? "true" : undefined}
        className="rounded text-left font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
      >
        <span className="block max-w-28 truncate sm:max-w-none">{label}</span>
      </button>
      <span className="block text-xs text-muted sm:ml-2 sm:inline">
        {originKind(info)} · {langs}
        {isHeadline ? " · our regression set" : ""}
      </span>
    </th>
  );
}

function AcrossSetRow({ row, summary, current, onPick }: { row: AcrossRow; summary: BenchmarkIndex; current: string; onPick: (set: string) => void }) {
  const { set, h } = row;
  const info = summary.fixture_sets[set];
  const on = set === current;
  return (
    <tr className={`border-b border-line last:border-0 ${on ? "bg-surface-2" : ""}`}>
      <AcrossSetHeaderCell set={set} info={info} isHeadline={set === summary.headline_set} on={on} onPick={onPick} />
      <td className="hidden px-2 py-1.5 text-right tabular-nums text-muted sm:table-cell">{info ? documentCount(info, "all") : ""}</td>
      {h ? (
        <>
          <td className="px-2 py-1.5 text-right font-medium tabular-nums text-ink">{formatPct(h.ours.leak)}</td>
          <td className="px-2 py-1.5 text-right tabular-nums text-muted">
            {formatPct(h.theirs.leak)} <span className="block text-xs sm:inline">({h.theirs.label})</span>
          </td>
          <td className="hidden px-2 py-1.5 text-right tabular-nums text-ink md:table-cell">{formatPct(h.ours.f1)}</td>
          <td className="hidden px-2 py-1.5 text-right tabular-nums text-muted md:table-cell">{formatPct(h.theirs.f1)}</td>
        </>
      ) : (
        <td colSpan={4} className="px-2 py-1.5">
          <span role={info ? "status" : undefined} aria-label={info ? `Loading ${set}` : undefined} className="ml-auto block h-4 w-3/4 animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
        </td>
      )}
    </tr>
  );
}

const LOADING_ACROSS_ROWS: AcrossRow[] = Array.from({ length: 6 }, (_, i) => ({ set: `loading-${i}`, h: undefined }));

/**
 * Fast mode against the lowest-leak open-source tool on every set both were run on, all
 * languages pooled: the "on which data, and how does it compare" answer in one table, so the
 * smoke headline isn't the only number a first-time reader sees (LAB-1531). A row picks its set.
 */
export function AcrossSets({ rows, summary, current, onPick }: { rows: AcrossRow[] | null; summary: BenchmarkIndex; current: string; onPick: (set: string) => void }) {
  // Rows whose results came back without fast mode or a tool on them are dropped.
  const shown = rows?.filter((r) => r.h !== null && (r.h === undefined || r.h.fastMode)) ?? null;
  if (shown && !shown.length) return null;
  const head = "px-2 py-2 text-right font-medium";
  return (
    <section aria-labelledby="bench-across-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <h2 id="bench-across-title" className="text-lg font-normal text-ink">
        Every test set, at a glance
      </h2>
      <p className="mt-0.5 mb-4 text-sm text-muted">
        PII Guard’s fast mode against the lowest-leak open-source tool on each set both were run on, all languages pooled. Lower leak is safer; F1 shows the
        price in precision and recall. Model-generated sets are left out. Pick a set to see it in detail.
      </p>
      <div
        role="region"
        aria-label="Results by test set, scrolls sideways"
        tabIndex={0}
        className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0"
      >
        <table className="w-full text-sm sm:min-w-max">
          <caption className="sr-only">Leak and F1 of PII Guard fast mode and the best open-source tool, per test set</caption>
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th scope="col" className="py-2 pr-3 font-medium">
                Test set
              </th>
              <th scope="col" className={`${head} hidden sm:table-cell`}>
                Docs
              </th>
              <th scope="col" className={`${head} text-ink`}>
                Leak, fast mode
              </th>
              <th scope="col" className={head}>
                Leak, best open-source tool
              </th>
              <th scope="col" className={`${head} hidden text-ink md:table-cell`}>
                F1, fast mode
              </th>
              <th scope="col" className={`${head} hidden md:table-cell`}>
                F1, that tool
              </th>
            </tr>
          </thead>
          <tbody>
            {(shown ?? LOADING_ACROSS_ROWS).map((row) => (
              <AcrossSetRow key={row.set} row={row} summary={summary} current={current} onPick={onPick} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function dateSpan(dates: string[]): string {
  const ds = [...new Set(dates)].sort();
  return ds.length > 1 ? `${ds[0]} to ${ds[ds.length - 1]}` : (ds[0] ?? "–");
}

function formatLanguageList(info: FixtureSetInfo | undefined, lang: LanguageFilter): string | undefined {
  const where = lang === "all" ? (info?.languages ?? []).map(languageName) : [languageName(lang)];
  return where.length > 1 ? `${where.slice(0, -1).join(", ")} and ${where[where.length - 1]}` : where[0];
}

function headlineScope(info: FixtureSetInfo | undefined, lang: LanguageFilter): string {
  const docs = documentCount(info, lang) ?? "?";
  const kind = originKind(info);
  const kindWord = kind === "generated" ? "model-generated" : kind.replace(" ", "-");
  return `${docs} ${kindWord} ${formatLanguageList(info, lang)} documents`;
}

export function Headline({ index, set, lang }: { index: BenchmarkIndex; set: string; lang: LanguageFilter }) {
  const h = headline(index, set, lang);
  const info = index.fixture_sets[set];
  if (!h) return null;
  const kind = originKind(info);
  const scope = headlineScope(info, lang);
  const isRegressionSet = set === index.headline_set && kind === "hand-written";
  const pct = (x: HeadlineSide) => <strong className="font-medium tabular-nums text-ink">{formatPct(x.leak)}</strong>;
  return (
    <div className="border-l-2 border-guard py-1 pl-4" data-testid="bench-headline">
      <p className="text-base text-pretty text-ink sm:text-lg">
        On {scope} ({set}),{" "}
        {h.fastMode ? (
          <>PII Guard’s fast mode lets {pct(h.ours)} of personal values through.</>
        ) : (
          <>
            PII Guard’s best configuration here, {h.ours.label}, lets {pct(h.ours)} of personal values through.
          </>
        )}{" "}
        The best open-source tool, {h.theirs.label}, lets {pct(h.theirs)} through.
      </p>
      <p className="mt-1 max-w-4xl text-xs text-pretty text-muted">
        {h.fastMode ? "Fast mode is the production path: rules + the published on-device NER v4.2. " : "Fast mode wasn’t run on this set. "}
        {isRegressionSet && "This is our own hand-written regression set; the public test sets are in the table below. "}
        F1 {formatPct(h.ours.f1)} against {formatPct(h.theirs.f1)}; over-masking (masked text that wasn’t personal data) {formatPct(h.ours.over_masking)} against{" "}
        {formatPct(h.theirs.over_masking)}.{" "}
        {h.otherModel && (
          <>
            Best other open NER model with the same rules (switch it on under More systems): {h.otherModel.label}, {formatPct(h.otherModel.leak)}.{" "}
          </>
        )}
        Leak = labeled personal values still readable after masking. Runs of {dateSpan(h.ours.dates)} (PII Guard) and {dateSpan(h.theirs.dates)} ({h.theirs.label}); speed was
        measured where each ran, so see the table and “Where these ran” before comparing it.
      </p>
    </div>
  );
}

export function Segmented<T extends string>({
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
    <div className="min-w-0">
      <p aria-hidden="true" className="mb-2 text-xs font-medium text-muted">
        {label}
      </p>
      <SegmentedControl
        label={label}
        value={value}
        onChange={onChange}
        className="flex-wrap"
        options={options.map((o) => ({
          value: o.id,
          label: (
            <>
              {o.label}
              {o.hint && <span className="text-xs text-faint">{o.hint}</span>}
            </>
          ),
        }))}
      />
    </div>
  );
}

export function Section({ id, title, note, children }: { id: string; title: string; note: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-title`} className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <h2 id={`${id}-title`} className="text-lg font-normal text-ink">
        {title}
      </h2>
      <p className="mt-0.5 mb-4 text-sm text-muted">{note}</p>
      {children}
    </section>
  );
}

type SnapshotRow = { s: Snapshot; m: Metrics | null };

function compareNumbers(va: number | null, vb: number | null, dir: "asc" | "desc"): number {
  if (va === null) return vb === null ? 0 : 1; // not run / not measured: always last
  if (vb === null) return -1;
  return dir === "asc" ? va - vb : vb - va;
}

function compareSnapshotRows(index: BenchmarkIndex, lang: LanguageFilter, sort: SortState, a: SnapshotRow, b: SnapshotRow): number {
  // Pooled, a system run on only some languages is listed after those run on all of them:
  // its numbers cover fewer documents, so it doesn't lead the table (LAB-1493).
  if (lang === "all") {
    const pa = coverageTag(index, a.s) ? 1 : 0;
    const pb = coverageTag(index, b.s) ? 1 : 0;
    if (pa !== pb) return pa - pb;
  }
  return compareNumbers(a.m?.[sort.key] ?? null, b.m?.[sort.key] ?? null, sort.dir);
}

function bestMetricValue(rows: SnapshotRow[], index: BenchmarkIndex, lang: LanguageFilter, key: keyof Metrics, dir: "high" | "low"): number | null {
  // Only systems that ran every language compete for "best"; a partial run is not a win.
  const vals = rows
    .filter((r) => lang !== "all" || !coverageTag(index, r.s))
    .map((r) => r.m?.[key])
    .filter((v): v is number => typeof v === "number");
  if (!vals.length) return null;
  return dir === "low" ? Math.min(...vals) : Math.max(...vals);
}

function formatMetricCellValue(m: Metrics, key: SortKey, v: number | null): string {
  if (key === "detect_p50_ms") return formatMs(v) + (m.latency_pooled ? "*" : "");
  return formatPct(v);
}

function ResultMetricCell({ m, col, top, fast }: { m: Metrics | null; col: (typeof COLUMNS)[number]; top: boolean; fast: boolean }) {
  const v = m?.[col.key] ?? null;
  const tone = top ? "font-medium text-ink underline decoration-line-strong decoration-2 underline-offset-4" : fast ? "text-ink" : "text-muted";
  return (
    <td className={`px-2 py-2 text-right tabular-nums whitespace-nowrap ${tone}`}>
      {m === null ? <span className="text-faint">not run</span> : formatMetricCellValue(m, col.key, v)}
    </td>
  );
}

function SystemRowHeaderCell({ systemId, sys, fast, partialTag }: { systemId: string; sys: SystemInfo | undefined; fast: boolean; partialTag: string | null }) {
  const thTone = fast ? "bg-guard-soft pl-2 shadow-[inset_2px_0_0_var(--guard)]" : "bg-surface";
  return (
    <th scope="row" title={sys?.label ?? systemId} className={`sticky left-0 z-10 max-w-[9.5rem] overflow-hidden py-2 pr-3 text-left font-medium text-ink sm:max-w-[17rem] ${thTone}`}>
      <span className="flex items-start gap-1.5">
        <span className="mt-[3px] shrink-0">
          <MarkerIcon info={sys} />
        </span>
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {sys?.short_label ?? systemId}
          {fast && (
            <>
              {" "}
              <FastModeTag />
            </>
          )}
          {partialTag && (
            <>
              {" "}
              <span
                title="Not run on every language of this set, so its pooled numbers cover fewer documents than the other rows."
                className="rounded-sm px-1 font-mono text-2xs whitespace-nowrap text-warn ring-1 ring-warn/40"
              >
                {partialTag}
              </span>
            </>
          )}
        </span>
      </span>
    </th>
  );
}

function ResultSystemRow({
  row,
  index,
  lang,
  rowCount,
  bestOf,
}: {
  row: SnapshotRow;
  index: BenchmarkIndex;
  lang: LanguageFilter;
  rowCount: number;
  bestOf: (key: keyof Metrics, dir: "high" | "low") => number | null;
}) {
  const { s, m } = row;
  const fast = s.system === FAST_MODE_SYSTEM;
  const partialTag = lang === "all" ? coverageTag(index, s) : null;
  const eligibleForBest = rowCount > 1 && !partialTag;
  return (
    <tr className={`border-b border-line last:border-0 ${fast ? "bg-guard-soft" : ""}`}>
      <SystemRowHeaderCell systemId={s.system} sys={index.systems[s.system]} fast={fast} partialTag={partialTag} />
      {COLUMNS.map((c) => {
        const v = m?.[c.key] ?? null;
        const top = eligibleForBest && v !== null && v === bestOf(c.key, c.better);
        return <ResultMetricCell key={c.key} m={m} col={c} top={top} fast={fast} />;
      })}
      <td className="hidden px-2 py-2 text-xs whitespace-nowrap text-muted min-[1400px]:table-cell" title={`Commit ${s.commits.map((c) => c.slice(0, 7)).join(", ")}`}>
        {s.dates.join(", ")}
      </td>
    </tr>
  );
}

export function ResultsTable({
  snapshots,
  index,
  lang,
  sort,
  onSortChange,
}: {
  snapshots: Snapshot[];
  index: BenchmarkIndex;
  lang: LanguageFilter;
  sort: SortState;
  onSortChange: (next: SortState) => void;
}) {
  // Each column first sorts best-first (lowest leak, highest F1); clicking again reverses.
  const rows = snapshots.map((s) => ({ s, m: pick(s, lang) })).sort((a, b) => compareSnapshotRows(index, lang, sort, a, b));
  const bestOf = (key: keyof Metrics, dir: "high" | "low") => bestMetricValue(rows, index, lang, key, dir);

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
          {lang === "all" ? "; systems not run on every language are listed last" : ""}
        </caption>
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th scope="col" className="sticky left-0 z-10 bg-surface py-2 pr-3 font-medium">
              System
            </th>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                className="px-2 py-2 text-right font-medium whitespace-nowrap"
                aria-sort={c.key === sort.key ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                <button
                  type="button"
                  onClick={() => onSortChange(nextSortState(sort, c))}
                  className={`group inline-flex items-center gap-1 rounded hover:text-ink ${c.key === sort.key ? "text-ink" : ""}`}
                >
                  {c.label}
                  <SortIcon state={c.key === sort.key ? sort.dir : null} />
                </button>
              </th>
            ))}
            <th scope="col" className="hidden px-2 py-2 text-left font-medium min-[1400px]:table-cell">
              Run
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ResultSystemRow key={row.s.system} row={row} index={index} lang={lang} rowCount={rows.length} bestOf={bestOf} />
          ))}
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
export function RunNotes({ snapshots, index, open, loading = false }: { snapshots: Snapshot[]; index: BenchmarkIndex; open: boolean; loading?: boolean }) {
  // While the run log loads, the disclosure keeps its place so the charts below don't move.
  if (loading) {
    return (
      <details className="mt-4 rounded-xl border border-line bg-surface-2">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">Where these ran, and caveats</summary>
        <p role="status" className="border-t border-line px-3 py-3 text-xs text-muted">
          Loading the run log…
        </p>
      </details>
    );
  }
  const runs = new Map(index.runs.map((r) => [r.run_id, r]));
  const items = snapshots
    .map((s) => {
      const rs = s.run_ids.map((id) => runs.get(id)).filter((r) => r !== undefined);
      const hardware = [...new Set(rs.map((r) => r.hardware).filter((h): h is string => !!h).map(readerNote))];
      const notes = [...new Set(rs.flatMap((r) => r.notes).map(readerNote))];
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

/** Collapsed, the image table shows the best runs of each set. */
const VISUAL_ROWS = 4;
const imageSetOf = (r: { fixture_set: string | null }) => r.fixture_set ?? "specimens";
const REGION_TYPE_LABEL: Record<string, string> = { portrait: "Portrait", signature: "Signature", mrz: "MRZ", text: "Printed text" };

export function VisualTable({ index }: { index: BenchmarkIndex }) {
  const [all, setAll] = useState(false);
  const types = [...new Set(index.visual.flatMap((r) => Object.keys(r.by_region_type)))];
  // Best runs first within each set, so the short view is the useful one.
  const sorted = [...index.visual].sort(
    (a, b) => (a.fixture_set ?? "").localeCompare(b.fixture_set ?? "") || (b.overall.recall_iou50 ?? 0) - (a.overall.recall_iou50 ?? 0),
  );
  const rank = new Map<string, number>();
  const shown = all
    ? sorted
    : sorted.filter((r) => {
        const n = rank.get(imageSetOf(r)) ?? 0;
        rank.set(imageSetOf(r), n + 1);
        return n < VISUAL_ROWS;
      });
  return (
    <>
      <div
        role="region"
        aria-label="Image masking table, scrolls sideways"
        tabIndex={0}
        className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0"
      >
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th scope="col" className="py-2 pr-3 font-medium">
                Run
              </th>
              <th scope="col" className="px-2 py-2 text-right font-medium">
                Images
              </th>
              {types.map((t) => (
                <th key={t} scope="col" className="px-2 py-2 text-right font-medium">
                  {REGION_TYPE_LABEL[t] ?? t}
                </th>
              ))}
              <th scope="col" className="px-2 py-2 text-right font-medium">
                All regions
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <Fragment key={r.run_id}>
                {/* One heading row per image set: official specimens and fictional documents don't compare. */}
                {(i === 0 || imageSetOf(shown[i - 1]!) !== imageSetOf(r)) && (
                  <tr className="border-b border-line">
                    <th scope="colgroup" colSpan={types.length + 3} className="bg-surface-2 px-2 py-1.5 text-left text-xs font-medium text-ink">
                      {imageSetOf(r)}{" "}
                      <span className="font-normal text-muted">· {sorted.filter((x) => imageSetOf(x) === imageSetOf(r)).length} runs</span>
                    </th>
                  </tr>
                )}
                <tr className="border-b border-line last:border-0">
                  <th scope="row" className="py-2 pr-3 text-left font-normal">
                    <span className="block font-medium text-ink">{visualRunLabel(r.system)}</span>
                    <span className="text-xs text-muted">
                      {r.date} · {r.countries} countries · <code className="font-mono text-2xs" title="Run record id">{r.run_id.replace(`${r.date}-`, "")}</code>
                    </span>
                  </th>
                  <td className="px-2 py-2 text-right tabular-nums">{r.specimens}</td>
                  {types.map((t) => (
                    <td key={t} className="px-2 py-2 text-right tabular-nums">
                      {formatPct(r.by_region_type[t]?.recall_iou50, 0)}
                    </td>
                  ))}
                  <td className="px-2 py-2 text-right font-medium tabular-nums">{formatPct(r.overall.recall_iou50, 0)}</td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > shown.length || all ? (
        <Button variant="ghost" className="mt-2 -ml-3" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? `Show the best ${VISUAL_ROWS} of each set` : `Show all ${sorted.length} runs`}
        </Button>
      ) : null}
    </>
  );
}

const RUN_LOG_ROWS = 25;

function runCostSuffix(cost: RunInfo["cost"]): string {
  if (!cost) return "";
  const usd = cost.usd != null ? ` · ${cost.estimated ? "≈ " : ""}$${cost.usd.toFixed(2)}` : "";
  const gpu = cost.gpu_minutes != null ? ` · ${cost.gpu_minutes} GPU-min` : "";
  return usd + gpu;
}

function runMetaSuffix(r: RunInfo): string {
  const dirty = r.dirty ? " (uncommitted changes)" : "";
  const hw = r.hardware ? ` · ${stripTickets(r.hardware)}` : "";
  return `${dirty}${hw}${runCostSuffix(r.cost)}`;
}

function RunLogEntry({ run: r, systemLabel }: { run: RunInfo; systemLabel: string }) {
  const sourceTone = r.source === "imported" ? "bg-surface-2 text-muted ring-1 ring-line" : "text-muted ring-1 ring-line-strong";
  return (
    <li className="px-4 py-3 text-sm sm:px-5">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium text-ink">{systemLabel}</span>
        <span className="text-muted">on {r.fixture_set}</span>
        {r.languages.length > 0 && <span className="text-muted">({r.languages.join(", ")})</span>}
        <span className={`rounded-sm px-1.5 font-mono text-2xs ${sourceTone}`}>{r.source}</span>
      </p>
      <p className="mt-0.5 text-xs break-words text-muted">
        {r.date} · <code className="font-mono">{r.commit.slice(0, 7)}</code>
        {runMetaSuffix(r)}
      </p>
      {r.notes.length > 0 && <p className="mt-1 text-xs break-words text-faint">{r.notes.map(stripTickets).join(" ")}</p>}
    </li>
  );
}

export function RunLog({ index }: { index: BenchmarkIndex }) {
  // Opened in full, the log was about 70,000 px tall: the latest runs first, the rest on request.
  const [all, setAll] = useState(false);
  const latest = [...index.runs].reverse();
  const shown = all ? latest : latest.slice(0, RUN_LOG_ROWS);
  return (
    <>
      <ol className="divide-y divide-line border-t border-line">
        {shown.map((r) => (
          <RunLogEntry key={r.run_id} run={r} systemLabel={index.systems[r.system]?.label ?? r.system} />
        ))}
      </ol>
      {latest.length > RUN_LOG_ROWS && (
        <div className="border-t border-line px-2 py-2 sm:px-3">
          <Button variant="ghost" size="sm" aria-expanded={all} onClick={() => setAll((v) => !v)}>
            {all ? `Show the latest ${RUN_LOG_ROWS}` : `Show all ${latest.length} runs`}
          </Button>
        </div>
      )}
    </>
  );
}

/** Sort state of a column: an up or down chevron when sorted, a faint up-down pair otherwise. */
function SortIcon({ state }: { state: "asc" | "desc" | null }) {
  const tone = state ? "" : "opacity-40 group-hover:opacity-80";
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={`size-3 shrink-0 ${tone}`} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {state === "asc" ? <path d="m4 10 4-4 4 4" /> : state === "desc" ? <path d="m4 6 4 4 4-4" /> : <path d="m5 6 3-3 3 3M5 10l3 3 3-3" />}
    </svg>
  );
}
