import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  documentCount,
  formatMs,
  formatPct,
  groupOf,
  headline,
  type Headline as HeadlineResult,
  type HeadlineSide,
  languageName,
  originKind,
  type SystemGroup,
  coverageTag,
  FAST_MODE_SYSTEM,
  tidyLabels,
  benchmarkSource,
  sourceOf,
  originLabel,
  pick,
  snapshotsFor,
  systemsOn,
  textSets,
  type BenchmarkIndex,
  type BenchmarkLoader,
  type BenchmarkSource,
  type SetResults,
  readerNote,
  visualRunLabel,
  type LanguageFilter,
  type Metrics,
  type Snapshot,
  type SystemInfo,
} from "../api/benchmarks";
import { SOURCE } from "../hosted/session";
import { Button, Notice, PageHeader, SegmentedControl, Select } from "../components/ui";
import { LanguageBars, LeakLatencyChart, MarkerIcon, ProgressChart, TypeHeatmap } from "./BenchmarksCharts";

/** Internal ticket ids ("(LAB-1150)", ", LAB-1128)") are maintainer context, not reader copy. */
function stripTickets(text: string): string {
  return text
    .replace(/,\s*LAB-\d+(?=\))/g, "")
    .replace(/\s*\(LAB-\d+\)/g, "")
    .replace(/\bLAB-\d+:?\s*/g, "")
    .replace(/\bpii-guard(?= (?:NER|rules|fast|audit|LLM|gateway)\b)/g, "PII Guard")
    .trim();
}

/**
 * Short names the screen shows in place of a run record's own short label, which for the
 * production system spells out the Hugging Face id and wraps in every table header and chart
 * label. The full label stays in tooltips and the run log (LAB-1531).
 */
const DISPLAY_LABEL: Record<string, string> = { [FAST_MODE_SYSTEM]: "rules + NER v2.0" };

/** "rules + X in place of PII Guard NER": the "rules +" already says it, and the label wraps. */
const shortLabel = (text: string) => stripTickets(text).replace(/ in place of PII Guard NER\b/, "");

/**
 * Green belongs to the production system: other systems the palette gave a green are drawn in
 * the palette's other colors, in a stable order (LAB-1533). The stored colors don't change.
 */
const GREENS = new Set(["#009E73", "#117733"]);
const NOT_GREEN = ["#0072B2", "#E69F00", "#CC79A7", "#D55E00", "#AA4499", "#999933", "#882255", "#332288"];

function displayColors(systems: BenchmarkIndex["systems"]): Record<string, string> {
  const production = systems[FAST_MODE_SYSTEM]?.color.toUpperCase();
  const greens = production && GREENS.has(production) ? GREENS : new Set(production ? [production] : []);
  const moved = Object.keys(systems)
    .filter((k) => k !== FAST_MODE_SYSTEM && greens.has(systems[k]!.color.toUpperCase()))
    .sort();
  return Object.fromEntries(moved.map((k, i) => [k, NOT_GREEN[i % NOT_GREEN.length]!]));
}

function withoutTickets(index: BenchmarkIndex): BenchmarkIndex {
  const recolored = displayColors(index.systems);
  const systems = Object.fromEntries(
    Object.entries(index.systems).map(([k, v]) => [
      k,
      { ...v, color: recolored[k] ?? v.color, label: stripTickets(v.label), short_label: DISPLAY_LABEL[k] ?? (v.short_label && shortLabel(v.short_label)) },
    ]),
  );
  return { ...index, systems };
}

type Load = { state: "loading" } | { state: "ready"; index: BenchmarkIndex } | { state: "error"; message: string };
type SetLoad = { state: "ready"; data: SetResults } | { state: "error"; message: string };
/** The run log, when the source sends it apart from the summary: null while it loads. */
type RunsLoad = BenchmarkIndex["runs"] | null | { error: string };

const messageOf = (err: unknown) => (err instanceof Error ? err.message : String(err));

const DOCS = `${SOURCE}/blob/develop/docs`;
const MODEL_CARD = "https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base";

/**
 * Every recorded evaluation run, browsable: the same data as docs/benchmarks.md, read from
 * the index shipped with the page (so it works in demo mode, without the API). The summary
 * loads first; each fixture set's results load when the set is picked (LAB-1454), and the run
 * log arrives on its own without holding up the headline (LAB-1493).
 */
export function Benchmarks({ load = benchmarkSource }: { load?: BenchmarkLoader }) {
  const source = useMemo(() => sourceOf(load), [load]);
  const [data, setData] = useState<Load>({ state: "loading" });
  const [runs, setRuns] = useState<RunsLoad>(null);
  useEffect(() => {
    let live = true;
    source.summary().then(
      (index) => live && setData({ state: "ready", index: withoutTickets(tidyLabels(index)) }),
      (err: unknown) => live && setData({ state: "error", message: messageOf(err) }),
    );
    source.runs?.().then(
      (part) => live && setRuns(part.runs),
      (err: unknown) => live && setRuns({ error: messageOf(err) }),
    );
    return () => {
      live = false;
    };
  }, [source]);
  // A source without `runs()` puts the run log in the summary.
  const runLog = source.runs ? runs : data.state === "ready" ? data.index.runs : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evaluation"
        lead="How much personal data gets through. Every evaluation run of PII Guard, and of the open-source tools it is compared with, is recorded with its commit (and whether the working tree had uncommitted changes), models, fixtures and hardware. All test documents are fictional or come from public test sets."
      >
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <a className="text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink" href={`${DOCS}/evaluation.md`}>
            How we measure
          </a>
          <a className="text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink" href={`${DOCS}/benchmarks.md`}>
            All results and run records
          </a>
          <a className="text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink" href={MODEL_CARD}>
            NER model card
          </a>
        </p>
      </PageHeader>
      {data.state === "loading" && (
        <div role="status" aria-label="Loading benchmark results" className="space-y-2 border-l-2 border-line py-1 pl-4">
          <div className="h-5 w-3/4 max-w-2xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
          <div className="h-3 w-1/2 max-w-xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
        </div>
      )}
      {data.state === "error" && (
        <Notice tone="danger" live title="The benchmark results could not be loaded.">
          <p className="text-muted">{data.message}</p>
        </Notice>
      )}
      {data.state === "ready" && <Explorer summary={data.index} runLog={runLog} source={source} />}
    </div>
  );
}

const GROUPS: { id: SystemGroup; label: string; hint?: string }[] = [
  { id: "ours", label: "PII Guard" },
  { id: "other-model", label: "Other open models", hint: "Someone else's model in PII Guard's pipeline" },
  { id: "tool", label: "Open-source tools" },
];

function Explorer({ summary: base, runLog, source }: { summary: BenchmarkIndex; runLog: RunsLoad; source: BenchmarkSource }) {
  const runsReady = Array.isArray(runLog);
  const summary = useMemo(() => (Array.isArray(runLog) ? { ...base, runs: runLog } : base), [base, runLog]);
  const sets = useMemo(() => textSets(summary), [summary]);
  const [set, setSet] = useState(sets[0] ?? "");
  // Each set's results, fetched the first time the set is picked and kept.
  const [loaded, setLoaded] = useState<Record<string, SetLoad>>({});
  const part = loaded[set];
  useEffect(() => {
    if (!set || part) return;
    let live = true;
    source.set(set).then(
      (data) => live && setLoaded((m) => ({ ...m, [set]: { state: "ready", data } })),
      (err: unknown) => live && setLoaded((m) => ({ ...m, [set]: { state: "error", message: messageOf(err) } })),
    );
    return () => {
      live = false;
    };
  }, [source, set, part]);
  const ready = part?.state === "ready";
  const opened = Object.values(loaded).some((p) => p.state === "ready");
  const index = useMemo(() => (part?.state === "ready" ? { ...summary, ...part.data } : summary), [summary, part]);
  const [lang, setLang] = useState<LanguageFilter>("all");
  const available = useMemo(() => systemsOn(index, set), [index, set]);
  const featured = useMemo(() => available.filter((k) => index.systems[k]?.featured), [available, index]);
  const [chosen, setChosen] = useState<string[] | null>(null); // null: the featured systems
  const [allSystems, setAllSystems] = useState(false);
  const selected = (chosen ?? (featured.length ? featured : available)).filter((k) => available.includes(k));
  const info = index.fixture_sets[set];
  const languages = info?.languages ?? [];
  const snapshots = snapshotsFor(index, set, selected);
  const history = index.history.filter(
    (h) => h.fixture_set === set && selected.includes(h.system) && groupOf(index.systems[h.system]) === "ours",
  );
  const lastRun = runsReady && index.runs.length ? index.runs[index.runs.length - 1]!.date : "–";
  // Collapsed, the picker shows the featured systems and whatever else is selected.
  const shown = allSystems ? available : available.filter((k) => featured.includes(k) || selected.includes(k));
  const hiddenCount = available.length - shown.length;
  const setsByKind = useMemo(() => {
    const kinds = new Map<string, string[]>();
    for (const s of sets) {
      const k = originKind(summary.fixture_sets[s]);
      kinds.set(k, [...(kinds.get(k) ?? []), s]);
    }
    const order = ["hand-written", "mixed origin", "generated"];
    return [...kinds.entries()].sort(([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  }, [sets, summary]);

  // Every set with both fast mode and an open-source tool on it, read from the run log, so the
  // screen fetches only those sets' results. Model-generated sets are left out: a Muse model wrote
  // them, which flatters Muse-based detection (LAB-1531).
  const compared = useMemo(() => {
    if (!runsReady) return null;
    const fast = new Set<string>();
    const tool = new Set<string>();
    for (const r of summary.runs) {
      if (r.system === FAST_MODE_SYSTEM) fast.add(r.fixture_set);
      if (summary.systems[r.system]?.family === "comparison") tool.add(r.fixture_set);
    }
    return sets.filter((s) => fast.has(s) && tool.has(s) && summary.fixture_sets[s]?.origin !== "generated");
  }, [runsReady, summary, sets]);
  const requested = useRef(new Set<string>());
  useEffect(() => {
    if (!compared || !opened) return;
    for (const s of compared) {
      if (requested.current.has(s)) continue;
      requested.current.add(s);
      source.set(s).then(
        (data) => setLoaded((m) => (m[s] ? m : { ...m, [s]: { state: "ready", data } })),
        (err: unknown) => setLoaded((m) => (m[s] ? m : { ...m, [s]: { state: "error", message: messageOf(err) } })),
      );
    }
  }, [compared, opened, source]);
  const across = useMemo(
    () =>
      compared?.map((s) => {
        const p = loaded[s];
        if (!p) return { set: s, h: undefined };
        return { set: s, h: p.state === "ready" ? headline({ ...summary, ...p.data }, s, "all") : null };
      }) ?? null,
    [compared, loaded, summary],
  );
  const pickSet = (s: string) => {
    setSet(s);
    if (lang !== "all" && !index.fixture_sets[s]?.languages.includes(lang)) setLang("all");
  };

  const toggle = (k: string) => {
    const now = selected;
    setChosen(now.includes(k) ? now.filter((x) => x !== k) : available.filter((x) => now.includes(x) || x === k));
  };

  return (
    <>
      {ready ? <Headline index={index} set={set} lang={lang} /> : <SetStatus set={set} part={part} />}

      {/* Until the first set's results land, only the headline placeholder shows: nothing below it
          jumps when they arrive (layout shift, LAB-1493). */}
      {!opened ? null : (
      <>
      <AcrossSets rows={across} summary={summary} current={set} onPick={pickSet} />
      <section aria-label="Filters" className="space-y-4 rounded-xl border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <div className="min-w-0">
            <label htmlFor="bench-set" className="mb-2 block text-xs font-medium text-muted">
              Fixture set
            </label>
            <Select
              id="bench-set"
              value={set}
              className="w-full sm:w-auto sm:min-w-[18rem]"
              onChange={(e) => pickSet(e.target.value)}
            >
              {setsByKind.map(([kind, keys]) => (
                <optgroup key={kind} label={kind.charAt(0).toUpperCase() + kind.slice(1)}>
                  {keys.map((s) => (
                    <option key={s} value={s}>
                      {s} · {documentCount(summary.fixture_sets[s], "all") ?? "?"} docs
                      {s === summary.headline_set ? " · headline" : ""}
                    </option>
                  ))}
                </optgroup>
              ))}
            </Select>
          </div>
          <Segmented
            label="Language"
            value={lang}
            options={[{ id: "all", label: "All, pooled" }, ...languages.map((l) => ({ id: l, label: languageName(l) }))]}
            onChange={setLang}
          />
        </div>
        <fieldset className="min-w-0">
          <legend className="mb-2 flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium text-muted">
            Systems
            <span className="font-normal">
              {selected.length} of {available.length} shown
            </span>
            <span className="flex gap-1">
              <Button variant="ghost" size="sm" onClick={() => setChosen(null)}>
                Select featured
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setChosen(available)}>
                Select all
              </Button>
            </span>
          </legend>
          <div className="space-y-2">
            {ready &&
              GROUPS.map((group) => {
                const keys = shown.filter((k) => groupOf(index.systems[k]) === group.id);
                if (!keys.length) return null;
                return (
                  <div key={group.id} className="gap-x-1.5 gap-y-1.5 sm:grid sm:grid-cols-[8rem_1fr] sm:items-start">
                    <span className="mb-1.5 block text-xs text-muted sm:mb-0 sm:pt-2.5" title={group.hint}>
                      {group.label}
                    </span>
                    {/* Wrapped chips line up with the first chip, not under the group name. */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      {keys.map((k) => (
                        <SystemChip key={k} id={k} info={index.systems[k]} on={selected.includes(k)} onToggle={() => toggle(k)} />
                      ))}
                    </div>
                  </div>
                );
              })}
            {ready && (hiddenCount > 0 || allSystems) && (
              <Button variant="ghost" size="sm" className="-ml-2" aria-expanded={allSystems} onClick={() => setAllSystems((v) => !v)}>
                {allSystems ? "Show featured systems only" : `More systems (${hiddenCount})`}
              </Button>
            )}
            {ready && Object.values(index.systems).some((v) => v.family === "comparison") && !available.some((k) => index.systems[k]?.family === "comparison") && (
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
        .{(documentCount(info, lang) ?? 0) < 200 ? " Small set: a few points of difference is noise." : ""}
      </p>
      {info?.origin === "generated" && (
        <p role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
          <strong className="font-medium text-warn">Generated set.</strong> These documents were written by a Muse model, the same family as PII Guard's LLM detector, which flatters
          Muse-based detection, and fine-tuned detectors may have been trained on similar generated text (see the run notes under the
          results). The hand-written set has neither bias.
        </p>
      )}

      {!ready ? null : selected.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-muted">Pick at least one system to compare.</p>
      ) : (
        <>
          <Section id="bench-table" title="Results" note="Latest run of each system. Leak = labeled values still readable after masking. Underlined: the best value among systems run on every language.">
            <ResultsTable snapshots={snapshots} index={index} lang={lang} />
            <RunNotes key={set} snapshots={snapshots} index={index} open={info?.origin === "generated"} loading={!runsReady} />
          </Section>
          <Section id="bench-scatter" title="Leak rate vs latency" note="Down and left is better. Latency was measured where each system ran, so it is not a like-for-like speed test.">
            <LeakLatencyChart points={snapshots.flatMap((s) => {
              const m = pick(s, lang);
              return m ? [{ key: s.system, info: index.systems[s.system], metrics: m, note: lang === "all" ? coverageTag(index, s) : null }] : [];
            })} highlight={FAST_MODE_SYSTEM} />
          </Section>
          <Section id="bench-lang" title="By language" note="The same fixture set in each language.">
            <LanguageBars snapshots={snapshots} systems={index.systems} languages={languages} highlight={FAST_MODE_SYSTEM} />
          </Section>
          <Section id="bench-progress" title="Leak rate over time" note="Each PII Guard configuration, run by run. Dashed: the best result of any configuration so far, so a drop can mean a new configuration rather than an improved one.">
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
          <Section id="bench-types" title="Recall per entity type" note="Share of labeled values of each type found with the right type (overlap), in %. Leak doesn't look at types: a value masked under another type is protected, so it costs recall here but not leak.">
            <TypeHeatmap snapshots={snapshots} systems={index.systems} types={index.entity_types} lang={lang} />
          </Section>
        </>
      )}

      {index.visual.length > 0 && (
        <Section id="bench-visual" title="Image masking" note="Share of labeled image regions masked (IoU ≥ 0.5). Official specimen IDs and fictional Muse Image documents are different sets: compare runs within a set.">
          <VisualTable index={index} />
        </Section>
      )}

      <details className="group rounded-xl border border-line bg-surface">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-ink sm:px-5">
          <span className="mr-1.5 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
            ›
          </span>
          Run log
          <span className="ml-2 font-normal text-muted">
            {runsReady ? `${index.runs.length} runs` : "runs loading"} · {Object.keys(index.systems).length} systems · {sets.length} text +{" "}
            {Object.values(index.fixture_sets).filter((f) => f.kind === "visual").length} image sets · latest {lastRun}
          </span>
        </summary>
        <p className="px-4 pb-3 text-xs text-muted sm:px-5">
          Audit mode used to be called <code className="font-mono">strict</code>: runs recorded before the rename keep that name in their IDs and keys.
        </p>
        {runsReady ? (
          <RunLog index={index} />
        ) : runLog && "error" in runLog ? (
          <p role="alert" className="px-4 pb-3 text-sm text-danger sm:px-5">The run log could not be loaded: {runLog.error}</p>
        ) : (
          <p role="status" className="px-4 pb-3 text-sm text-muted sm:px-5">Loading the run log…</p>
        )}
      </details>
      </>
      )}
      <p className="text-xs text-faint">
        Generated by <code className="font-mono">pii-guard eval report</code> from <code className="font-mono">eval/results/runs/</code>. Add a run with{" "}
        <code className="font-mono">pii-guard eval --record &lt;slug&gt;</code>.
      </p>
    </>
  );
}

function SystemChip({ id, info, on, onToggle }: { id: string; info: SystemInfo | undefined; on: boolean; onToggle: () => void }) {
  return (
    <label
      title={info?.label}
      className={[
        "relative inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink",
        on ? "border-ink bg-surface-2 text-ink" : "border-line text-muted hover:border-line-strong",
      ].join(" ")}
    >
      <input type="checkbox" className="sr-only" checked={on} onChange={onToggle} />
      <MarkerIcon info={info} />
      {info?.short_label ?? id}
      {id === FAST_MODE_SYSTEM && <FastModeTag />}
    </label>
  );
}

function FastModeTag() {
  return (
    <span
      title="Rules + the published on-device NER v2.0: the gateway's fast mode, its production path. Without a NER checkpoint, fast mode runs the rules alone."
      className="rounded-sm bg-guard-soft px-1 font-mono text-2xs whitespace-nowrap text-guard-ink ring-1 ring-guard/40"
    >
      fast mode
    </span>
  );
}

/** In place of a set's results while they load, or when they could not be loaded. */
function SetStatus({ set, part }: { set: string; part: SetLoad | undefined }) {
  if (part?.state === "error")
    return (
      <Notice tone="danger" live title={`The results for ${set} could not be loaded.`}>
        <p className="text-muted">{part.message}</p>
      </Notice>
    );
  return (
    <div role="status" aria-label={`Loading results for ${set}`} className="space-y-2 border-l-2 border-line py-1 pl-4">
      <div className="h-5 w-3/4 max-w-2xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
      <div className="h-3 w-1/2 max-w-xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
    </div>
  );
}

type AcrossRow = { set: string; h: HeadlineResult | null | undefined };

/**
 * Fast mode against the lowest-leak open-source tool on every set both were run on, all
 * languages pooled: the "on which data, and how does it compare" answer in one table, so the
 * smoke headline isn't the only number a first-time reader sees (LAB-1531). A row picks its set.
 */
function AcrossSets({ rows, summary, current, onPick }: { rows: AcrossRow[] | null; summary: BenchmarkIndex; current: string; onPick: (set: string) => void }) {
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
            {(shown ?? Array.from({ length: 6 }, (_, i) => ({ set: `loading-${i}`, h: undefined }))).map(({ set, h }) => {
              const info = summary.fixture_sets[set];
              const on = set === current;
              return (
                <tr key={set} className={["border-b border-line last:border-0", on ? "bg-surface-2" : ""].join(" ")}>
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                    {info ? (
                      <button
                        type="button"
                        onClick={() => onPick(set)}
                        aria-current={on ? "true" : undefined}
                        className="rounded text-left font-medium [overflow-wrap:anywhere] text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
                      >
                        {set}
                      </button>
                    ) : (
                      <span className="block h-4 w-28 animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
                    )}
                    {info && (
                      <span className="block text-xs text-muted sm:ml-2 sm:inline">
                        {originKind(info)} · {info.languages.map((l) => l.toUpperCase()).join(" ")}
                        {set === summary.headline_set ? " · our regression set" : ""}
                      </span>
                    )}
                  </th>
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
            })}
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

function Headline({ index, set, lang }: { index: BenchmarkIndex; set: string; lang: LanguageFilter }) {
  const h = headline(index, set, lang);
  const info = index.fixture_sets[set];
  if (!h) return null;
  const docs = documentCount(info, lang);
  const kind = originKind(info);
  const where = lang === "all" ? (info?.languages ?? []).map(languageName) : [languageName(lang)];
  const inLangs = where.length > 1 ? `${where.slice(0, -1).join(", ")} and ${where[where.length - 1]}` : where[0];
  const scope = `${docs ?? "?"} ${kind === "generated" ? "model-generated" : kind.replace(" ", "-")} ${inLangs} documents`;
  const pct = (x: HeadlineSide) => <strong className="font-medium tabular-nums text-ink">{formatPct(x.leak)}</strong>;
  return (
    <div className="border-l-2 border-guard py-1 pl-4" data-testid="bench-headline">
      <p className="text-base text-pretty text-ink sm:text-lg">
        On {scope} ({set}),{" "}
        {h.fastMode ? (
          <>
            PII Guard’s fast mode lets {pct(h.ours)} of personal values through.
          </>
        ) : (
          <>
            PII Guard’s best configuration here, {h.ours.label}, lets {pct(h.ours)} of personal values through.
          </>
        )}{" "}
        The best open-source tool, {h.theirs.label}, lets {pct(h.theirs)} through.
      </p>
      <p className="mt-1 max-w-4xl text-xs text-pretty text-muted">
        {h.fastMode ? "Fast mode is the production path: rules + the published on-device NER v2.0. " : "Fast mode wasn’t run on this set. "}
        {set === index.headline_set && kind === "hand-written" && "This is our own hand-written regression set; the public test sets are in the table below. "}
        F1 {formatPct(h.ours.f1)} against {formatPct(h.theirs.f1)}; over-masking (masked text that wasn’t personal data) {formatPct(h.ours.over_masking)} against {formatPct(h.theirs.over_masking)}.{" "}
        {h.otherModel && (
          <>
            Best other open NER model with the same rules (switch it on under More systems): {h.otherModel.label}, {formatPct(h.otherModel.leak)}.{" "}
          </>
        )}
        Leak = labeled personal values still readable after masking. Runs of {dateSpan(h.ours.dates)} (PII Guard) and {dateSpan(h.theirs.dates)} ({h.theirs.label}); speed was measured where each ran, so see the
        table and “Where these ran” before comparing it.
      </p>
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

function Section({ id, title, note, children }: { id: string; title: string; note: string; children: ReactNode }) {
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
      // Pooled, a system run on only some languages is listed after those run on all of them:
      // its numbers cover fewer documents, so it doesn't lead the table (LAB-1493).
      if (lang === "all") {
        const pa = coverageTag(index, a.s) ? 1 : 0;
        const pb = coverageTag(index, b.s) ? 1 : 0;
        if (pa !== pb) return pa - pb;
      }
      const va = a.m?.[sort.key] ?? null;
      const vb = b.m?.[sort.key] ?? null;
      if (va === null) return vb === null ? 0 : 1; // not run / not measured: always last
      if (vb === null) return -1;
      return sort.dir === "asc" ? va - vb : vb - va;
    });
  const best = (key: keyof Metrics, dir: "high" | "low") => {
    // Only systems that ran every language compete for "best"; a partial run is not a win.
    const vals = rows
      .filter((r) => lang !== "all" || !coverageTag(index, r.s))
      .map((r) => r.m?.[key])
      .filter((v): v is number => typeof v === "number");
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
                  onClick={() => onSort(c)}
                  className={["group inline-flex items-center gap-1 rounded hover:text-ink", c.key === sort.key ? "text-ink" : ""].join(" ")}
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
          {rows.map(({ s, m }) => {
            const sys = index.systems[s.system];
            const fast = s.system === FAST_MODE_SYSTEM;
            return (
              <tr key={s.system} className={["border-b border-line last:border-0", fast ? "bg-guard-soft" : ""].join(" ")}>
                <th
                  scope="row"
                  title={sys?.label ?? s.system}
                  className={["sticky left-0 z-10 max-w-[9.5rem] overflow-hidden py-2 pr-3 text-left font-medium text-ink sm:max-w-[17rem]", fast ? "bg-guard-soft pl-2 shadow-[inset_2px_0_0_var(--guard)]" : "bg-surface"].join(" ")}
                >
                  <span className="flex items-start gap-1.5">
                    <span className="mt-[3px] shrink-0"><MarkerIcon info={sys} /></span>
                    <span className="min-w-0 [overflow-wrap:anywhere]">
                      {sys?.short_label ?? s.system}
                      {fast && <> <FastModeTag /></>}
                      {lang === "all" && coverageTag(index, s) && (
                        <>
                          {" "}
                          <span
                            title="Not run on every language of this set, so its pooled numbers cover fewer documents than the other rows."
                            className="rounded-sm px-1 font-mono text-2xs whitespace-nowrap text-warn ring-1 ring-warn/40"
                          >
                            {coverageTag(index, s)}
                          </span>
                        </>
                      )}
                    </span>
                  </span>
                </th>
                {COLUMNS.map((c) => {
                  const v = m?.[c.key] ?? null;
                  const top = v !== null && v === best(c.key, c.better) && rows.length > 1 && (lang !== "all" || !coverageTag(index, s));
                  return (
                    <td key={c.key} className={["px-2 py-2 text-right tabular-nums whitespace-nowrap", top ? "font-medium text-ink underline decoration-line-strong decoration-2 underline-offset-4" : fast ? "text-ink" : "text-muted"].join(" ")}>
                      {m === null ? <span className="text-faint">not run</span> : c.key === "detect_p50_ms" ? formatMs(v) + (m.latency_pooled ? "*" : "") : formatPct(v)}
                    </td>
                  );
                })}
                <td className="hidden px-2 py-2 text-xs whitespace-nowrap text-muted min-[1400px]:table-cell" title={`Commit ${s.commits.map((c) => c.slice(0, 7)).join(", ")}`}>
                  {s.dates.join(", ")}
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
function RunNotes({ snapshots, index, open, loading = false }: { snapshots: Snapshot[]; index: BenchmarkIndex; open: boolean; loading?: boolean }) {
  // While the run log loads, the disclosure keeps its place so the charts below don't move.
  if (loading)
    return (
      <details className="mt-4 rounded-xl border border-line bg-surface-2">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">Where these ran, and caveats</summary>
        <p role="status" className="border-t border-line px-3 py-3 text-xs text-muted">Loading the run log…</p>
      </details>
    );
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

function VisualTable({ index }: { index: BenchmarkIndex }) {
  const [all, setAll] = useState(false);
  const types = [...new Set(index.visual.flatMap((r) => Object.keys(r.by_region_type)))];
  // Best runs first within each set, so the short view is the useful one.
  const sorted = [...index.visual].sort(
    (a, b) => (a.fixture_set ?? "").localeCompare(b.fixture_set ?? "") || (b.overall.recall_iou50 ?? 0) - (a.overall.recall_iou50 ?? 0),
  );
  const rank = new Map<string, number>();
  const shown = all ? sorted : sorted.filter((r) => {
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

function RunLog({ index }: { index: BenchmarkIndex }) {
  // Opened in full, the log was about 70,000 px tall: the latest runs first, the rest on request.
  const [all, setAll] = useState(false);
  const latest = [...index.runs].reverse();
  return (
    <>
    <ol className="divide-y divide-line border-t border-line">
      {(all ? latest : latest.slice(0, RUN_LOG_ROWS)).map((r) => (
        <li key={r.run_id} className="px-4 py-3 text-sm sm:px-5">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium text-ink">{index.systems[r.system]?.label ?? r.system}</span>
            <span className="text-muted">on {r.fixture_set}</span>
            {r.languages.length > 0 && <span className="text-muted">({r.languages.join(", ")})</span>}
            <span
              className={[
                "rounded-sm px-1.5 font-mono text-2xs",
                r.source === "imported" ? "bg-surface-2 text-muted ring-1 ring-line" : "text-muted ring-1 ring-line-strong",
              ].join(" ")}
            >
              {r.source}
            </span>
          </p>
          <p className="mt-0.5 text-xs break-words text-muted">
            {r.date} · <code className="font-mono">{r.commit.slice(0, 7)}</code>
            {r.dirty ? " (uncommitted changes)" : ""}
            {r.hardware ? ` · ${stripTickets(r.hardware)}` : ""}
            {r.cost?.usd != null ? ` · ${r.cost.estimated ? "≈ " : ""}$${r.cost.usd.toFixed(2)}` : ""}
            {r.cost?.gpu_minutes != null ? ` · ${r.cost.gpu_minutes} GPU-min` : ""}
          </p>
          {r.notes.length > 0 && <p className="mt-1 text-xs break-words text-faint">{r.notes.map(stripTickets).join(" ")}</p>}
        </li>
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
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={["size-3 shrink-0", state ? "" : "opacity-40 group-hover:opacity-80"].join(" ")} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {state === "asc" ? <path d="m4 10 4-4 4 4" /> : state === "desc" ? <path d="m4 6 4 4 4-4" /> : <path d="m5 6 3-3 3 3M5 10l3 3 3-3" />}
    </svg>
  );
}
