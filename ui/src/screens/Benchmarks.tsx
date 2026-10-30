import { useEffect, useMemo, useRef, useState } from "react";
import {
  FAST_MODE_SYSTEM,
  benchmarkSource,
  coverageTag,
  documentCount,
  groupOf,
  headline,
  languageName,
  originKind,
  originLabel,
  pick,
  snapshotsFor,
  sourceOf,
  systemsOn,
  textSets,
  tidyLabels,
  type BenchmarkIndex,
  type BenchmarkLoader,
  type BenchmarkSource,
  type FixtureSetInfo,
  type LanguageFilter,
  type SetResults,
  type Snapshot,
  type SystemGroup,
} from "../api/benchmarks";
import { Button, Notice, PageHeader, Select } from "../components/ui";
import { SOURCE } from "../hosted/session";
import type { EvaluationParams } from "../lib/routes";
import { LanguageBars, LeakLatencyChart, MarkerIcon, ProgressChart, TypeHeatmap } from "./BenchmarksCharts";
import {
  AcrossSets,
  FastModeTag,
  Headline,
  ResultsTable,
  RunLog,
  RunNotes,
  Section,
  Segmented,
  SystemChip,
  VisualTable,
  type AcrossRow,
  type SortKey,
  type SortState,
} from "./BenchmarksTables";

export { AcrossSets, FastModeTag, Headline, ResultsTable, RunLog, RunNotes, Section, Segmented, SystemChip, VisualTable };

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
const DISPLAY_LABEL: Record<string, string> = { [FAST_MODE_SYSTEM]: "rules + NER v4.2" };

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
export function Benchmarks({ load = benchmarkSource, initial, onParams }: { load?: BenchmarkLoader; initial?: EvaluationParams | null; onParams?: (params: EvaluationParams) => void }) {
  const source = useMemo(() => sourceOf(load), [load]);
  const [data, setData] = useState<Load>({ state: "loading" });
  const [runs, setRuns] = useState<RunsLoad>(null);
  const [summaryAttempt, retrySummary] = useState(0);
  const [runsAttempt, retryRuns] = useState(0);
  useEffect(() => {
    let live = true;
    source.summary().then(
      (index) => live && setData({ state: "ready", index: withoutTickets(tidyLabels(index)) }),
      (err: unknown) => live && setData({ state: "error", message: messageOf(err) }),
    );
    return () => {
      live = false;
    };
  }, [source, summaryAttempt]);
  useEffect(() => {
    let live = true;
    source.runs?.().then(
      (part) => live && setRuns(part.runs),
      (err: unknown) => live && setRuns({ error: messageOf(err) }),
    );
    return () => {
      live = false;
    };
  }, [source, runsAttempt]);
  // A source without `runs()` puts the run log in the summary.
  const runLog = source.runs ? runs : data.state === "ready" ? data.index.runs : null;

  return (
    <div className="min-h-screen space-y-6">
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
          <p>Check your connection and try again.</p>
          <Button
            size="sm"
            onClick={() => {
              setData({ state: "loading" });
              retrySummary((n) => n + 1);
            }}
          >
            Retry benchmark results
          </Button>
        </Notice>
      )}
      {data.state === "ready" && (
        <Explorer
          summary={data.index}
          runLog={runLog}
          source={source}
          retryRuns={() => {
            setRuns(null);
            retryRuns((n) => n + 1);
          }}
          initial={initial}
          onParams={onParams}
        />
      )}
    </div>
  );
}

const GROUPS: { id: SystemGroup; label: string; hint?: string }[] = [
  { id: "ours", label: "PII Guard" },
  { id: "other-model", label: "Other open models", hint: "Someone else's model in PII Guard's pipeline" },
  { id: "tool", label: "Open-source tools" },
];

const DEFAULT_SORT: SortState = { key: "leak", dir: "asc" };
const SORT_DEFAULT_DIR: Record<SortKey, "asc" | "desc"> = {
  leak: "asc",
  partial_leak: "asc",
  f1: "desc",
  precision: "desc",
  recall: "desc",
  over_masking: "asc",
  roundtrip: "desc",
  detect_p50_ms: "asc",
};

/** A `sort` hash value (`key` or `key:dir`) as sort state, or the default (LAB-1133). */
function parseSort(value: string | undefined): SortState {
  const [key, dir] = value?.split(":") ?? [];
  const defaultDir = key ? SORT_DEFAULT_DIR[key as SortKey] : undefined;
  if (!defaultDir) return DEFAULT_SORT;
  const validDir = dir === "asc" || dir === "desc" ? dir : defaultDir;
  return { key: key as SortKey, dir: validDir };
}

function resolveInitialSet(wanted: string | undefined, sets: string[]): string {
  return wanted && sets.includes(wanted) ? wanted : (sets[0] ?? "");
}

function resolveInitialLang(wanted: LanguageFilter | undefined, nextLangs: string[]): LanguageFilter {
  if (wanted && (wanted === "all" || nextLangs.includes(wanted))) return wanted;
  return "all";
}

function resolveInitialParams(raw: EvaluationParams | null, sets: string[], index: BenchmarkIndex) {
  const params = raw ?? {};
  const nextSet = resolveInitialSet(params.set, sets);
  const nextLang = resolveInitialLang(params.lang, index.fixture_sets[nextSet]?.languages ?? []);
  const nextAvailable = systemsOn(index, nextSet);
  const nextChosen = params.systems === undefined ? null : params.systems.filter((id) => nextAvailable.includes(id));
  return { nextSet, nextLang, nextChosen, nextSort: parseSort(params.sort) };
}

function groupSetsByKind(sets: string[], summary: BenchmarkIndex): [string, string[]][] {
  const kinds = new Map<string, string[]>();
  for (const s of sets) {
    const k = originKind(summary.fixture_sets[s]);
    kinds.set(k, [...(kinds.get(k) ?? []), s]);
  }
  const order = ["hand-written", "mixed origin", "generated"];
  return [...kinds.entries()].sort(([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
}

function findComparedSets(runsReady: boolean, summary: BenchmarkIndex, sets: string[]): string[] | null {
  if (!runsReady) return null;
  const fast = new Set<string>();
  const tool = new Set<string>();
  for (const r of summary.runs) {
    if (r.system === FAST_MODE_SYSTEM) fast.add(r.fixture_set);
    if (summary.systems[r.system]?.family === "comparison") tool.add(r.fixture_set);
  }
  return sets.filter((s) => fast.has(s) && tool.has(s) && summary.fixture_sets[s]?.origin !== "generated");
}

function useSetResults(source: BenchmarkSource, set: string, summary: BenchmarkIndex, runsReady: boolean, sets: string[]) {
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

  const opened = Object.values(loaded).some((p) => p.state === "ready");
  // Every set with both fast mode and an open-source tool on it, read from the run log, so the
  // screen fetches only those sets' results. Model-generated sets are left out: a Muse model wrote
  // them, which flatters Muse-based detection (LAB-1531).
  const compared = useMemo(() => findComparedSets(runsReady, summary, sets), [runsReady, summary, sets]);
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

  const across = useMemo<AcrossRow[] | null>(
    () =>
      compared?.map((s) => {
        const p = loaded[s];
        if (!p) return { set: s, h: undefined };
        return { set: s, h: p.state === "ready" ? headline({ ...summary, ...p.data }, s, "all") : null };
      }) ?? null,
    [compared, loaded, summary],
  );
  const retryCurrentSet = () =>
    setLoaded((m) => {
      const next = { ...m };
      delete next[set];
      return next;
    });
  return { part, ready: part?.state === "ready", opened, across, retryCurrentSet };
}

function useUrlParamReporting(
  sets: string[],
  set: string,
  lang: LanguageFilter,
  chosen: string[] | null,
  sort: SortState,
  onParams?: (params: EvaluationParams) => void,
) {
  // Every filter change rewrites the hash (replaced, not pushed), so the URL stays shareable.
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (!sets.length || !onParams) return;
    const params: EvaluationParams = {
      set,
      lang,
      ...(chosen !== null ? { systems: chosen } : {}),
      sort: `${sort.key}:${sort.dir}`,
    };
    const key = JSON.stringify(params);
    if (reported.current === key) return;
    reported.current = key;
    onParams(params);
  }, [sets, set, lang, chosen, sort, onParams]);
}

function ExplorerFiltersSection({
  set,
  setsByKind,
  summary,
  lang,
  languages,
  onPickSet,
  onLang,
  ready,
  index,
  available,
  selected,
  shown,
  hiddenCount,
  allSystems,
  onToggleAllSystems,
  onChosen,
  onToggleSystem,
}: {
  set: string;
  setsByKind: [string, string[]][];
  summary: BenchmarkIndex;
  lang: LanguageFilter;
  languages: string[];
  onPickSet: (s: string) => void;
  onLang: (l: LanguageFilter) => void;
  ready: boolean;
  index: BenchmarkIndex;
  available: string[];
  selected: string[];
  shown: string[];
  hiddenCount: number;
  allSystems: boolean;
  onToggleAllSystems: () => void;
  onChosen: (c: string[] | null) => void;
  onToggleSystem: (k: string) => void;
}) {
  const noComparisonToolsOnSet =
    ready && Object.values(index.systems).some((v) => v.family === "comparison") && !available.some((k) => index.systems[k]?.family === "comparison");
  return (
    <section aria-label="Filters" className="space-y-4 rounded-xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="min-w-0">
          <label htmlFor="bench-set" className="mb-2 block text-xs font-medium text-muted">
            Fixture set
          </label>
          <Select id="bench-set" value={set} className="w-full sm:w-auto sm:min-w-[18rem]" onChange={(e) => onPickSet(e.target.value)}>
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
          onChange={onLang}
        />
      </div>
      <fieldset className="min-w-0">
        <legend className="mb-2 flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium text-muted">
          Systems
          <span className="font-normal">
            {selected.length} of {available.length} shown
          </span>
          <span className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => onChosen(null)}>
              Select featured
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onChosen(available)}>
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
                      <SystemChip key={k} id={k} info={index.systems[k]} on={selected.includes(k)} onToggle={() => onToggleSystem(k)} />
                    ))}
                  </div>
                </div>
              );
            })}
          {ready && (hiddenCount > 0 || allSystems) && (
            <Button variant="ghost" size="sm" className="-ml-2" aria-expanded={allSystems} onClick={onToggleAllSystems}>
              {allSystems ? "Show featured systems only" : `More systems (${hiddenCount})`}
            </Button>
          )}
          {noComparisonToolsOnSet && <p className="text-xs text-muted">The open-source tools weren’t run on this set; pick another set to compare with them.</p>}
        </div>
      </fieldset>
    </section>
  );
}

function SetOverviewNotes({ set, info, lang, languages }: { set: string; info: FixtureSetInfo | undefined; lang: LanguageFilter; languages: string[] }) {
  const docSummary =
    lang === "all"
      ? languages.map((l) => `${info?.documents[l] ?? "?"} ${languageName(l)}`).join(" + ") + " documents"
      : `${documentCount(info, lang) ?? "?"} ${languageName(lang)} documents`;
  const smallSet = (documentCount(info, lang) ?? 0) < 200;
  return (
    <>
      <p className="text-sm text-muted">
        <span className="font-medium text-ink">{set}</span>: {originLabel(info)}, {docSummary}.
        {smallSet ? " Small set: a few points of difference is noise." : ""}
      </p>
      {info?.origin === "generated" && (
        <p role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
          <strong className="font-medium text-warn">Generated set.</strong> These documents were written by a Muse model, the same family as PII Guard's LLM detector, which flatters
          Muse-based detection, and fine-tuned detectors may have been trained on similar generated text (see the run notes under the
          results). The hand-written set has neither bias.
        </p>
      )}
    </>
  );
}

function SetChartsSections({
  set,
  snapshots,
  index,
  lang,
  languages,
  sort,
  onSortChange,
  info,
  runsReady,
  selected,
}: {
  set: string;
  snapshots: Snapshot[];
  index: BenchmarkIndex;
  lang: LanguageFilter;
  languages: string[];
  sort: SortState;
  onSortChange: (next: SortState) => void;
  info: FixtureSetInfo | undefined;
  runsReady: boolean;
  selected: string[];
}) {
  if (selected.length === 0) {
    return <p className="rounded-xl border border-dashed border-line px-4 py-10 text-center text-sm text-muted">Pick at least one system to compare.</p>;
  }
  const history = index.history.filter((h) => h.fixture_set === set && selected.includes(h.system) && groupOf(index.systems[h.system]) === "ours");
  const scatterPoints = snapshots.flatMap((s) => {
    const m = pick(s, lang);
    return m ? [{ key: s.system, info: index.systems[s.system], metrics: m, note: lang === "all" ? coverageTag(index, s) : null }] : [];
  });
  return (
    <>
      <Section id="bench-table" title="Results" note="Latest run of each system. Leak = labeled values still readable after masking. Underlined: the best value among systems run on every language.">
        <ResultsTable snapshots={snapshots} index={index} lang={lang} sort={sort} onSortChange={onSortChange} />
        <RunNotes key={set} snapshots={snapshots} index={index} open={info?.origin === "generated"} loading={!runsReady} />
      </Section>
      <Section id="bench-scatter" title="Leak rate vs latency" note="Down and left is better. Latency was measured where each system ran, so it is not a like-for-like speed test.">
        <LeakLatencyChart points={scatterPoints} highlight={FAST_MODE_SYSTEM} />
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
  );
}

function RunLogDetails({ index, setsCount, runLog, runsReady, retryRuns }: { index: BenchmarkIndex; setsCount: number; runLog: RunsLoad; runsReady: boolean; retryRuns: () => void }) {
  const lastRun = runsReady && index.runs.length ? index.runs[index.runs.length - 1]!.date : "–";
  const visualSetsCount = Object.values(index.fixture_sets).filter((f) => f.kind === "visual").length;
  return (
    <details className="group rounded-xl border border-line bg-surface">
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-ink sm:px-5">
        <span className="mr-1.5 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
          ›
        </span>
        Run log
        <span className="ml-2 font-normal text-muted">
          {runsReady ? `${index.runs.length} runs` : "runs loading"} · {Object.keys(index.systems).length} systems · {setsCount} text + {visualSetsCount} image sets · latest {lastRun}
        </span>
      </summary>
      <p className="px-4 pb-3 text-xs text-muted sm:px-5">
        Audit mode used to be called <code className="font-mono">strict</code>: runs recorded before the rename keep that name in their IDs and keys.
      </p>
      {runsReady ? (
        <RunLog index={index} />
      ) : runLog && "error" in runLog ? (
        <div className="px-4 pb-3 sm:px-5">
          <Notice tone="danger" live title="The run log could not be loaded.">
            <p>Check your connection and try again.</p>
            <Button size="sm" onClick={retryRuns}>
              Retry run log
            </Button>
          </Notice>
        </div>
      ) : (
        <p role="status" className="px-4 pb-3 text-sm text-muted sm:px-5">
          Loading the run log…
        </p>
      )}
    </details>
  );
}

function resolveShownSystems(available: string[], featured: string[], chosen: string[] | null, allSystems: boolean) {
  const fallback = featured.length ? featured : available;
  const selected = (chosen ?? fallback).filter((k) => available.includes(k));
  // Collapsed, the picker shows the featured systems and whatever else is selected.
  const shown = allSystems ? available : available.filter((k) => featured.includes(k) || selected.includes(k));
  return { selected, shown, hiddenCount: available.length - shown.length };
}

function toggleSystemSelection(k: string, selected: string[], available: string[]): string[] {
  if (selected.includes(k)) return selected.filter((x) => x !== k);
  return available.filter((x) => selected.includes(x) || x === k);
}

interface ExplorerProps {
  summary: BenchmarkIndex;
  runLog: RunsLoad;
  source: BenchmarkSource;
  retryRuns: () => void;
  initial?: EvaluationParams | null;
  onParams?: (params: EvaluationParams) => void;
}

function useInitialParamsSync(
  initial: EvaluationParams | null | undefined,
  sets: string[],
  index: BenchmarkIndex,
  apply: (resolved: ReturnType<typeof resolveInitialParams>) => void,
) {
  // A shared link's filters (the URL hash) land once the sets are known, and again when
  // the link changes under the open screen (Back/forward, LAB-1133). While another section
  // is open `initial` is undefined and the kept state is left alone; a plain `#evaluation`
  // link (`initial` null) resets to the defaults.
  const initialKey = initial === undefined ? undefined : JSON.stringify(initial);
  const [appliedKey, setAppliedKey] = useState<string | null>(null);
  if (initialKey !== undefined && sets.length && initialKey !== appliedKey) {
    setAppliedKey(initialKey);
    apply(resolveInitialParams(JSON.parse(initialKey) as EvaluationParams | null, sets, index));
  }
}

function Explorer({ summary: base, runLog, source, retryRuns, initial, onParams }: ExplorerProps) {
  const runsReady = Array.isArray(runLog);
  const summary = useMemo(() => (Array.isArray(runLog) ? { ...base, runs: runLog } : base), [base, runLog]);
  const sets = useMemo(() => textSets(summary), [summary]);
  const [set, setSet] = useState(sets[0] ?? "");
  const { part, ready, opened, across, retryCurrentSet } = useSetResults(source, set, summary, runsReady, sets);
  const index = useMemo(() => (part?.state === "ready" ? { ...summary, ...part.data } : summary), [summary, part]);
  const [lang, setLang] = useState<LanguageFilter>("all");
  const available = useMemo(() => systemsOn(index, set), [index, set]);
  const featured = useMemo(() => available.filter((k) => index.systems[k]?.featured), [available, index]);
  const [chosen, setChosen] = useState<string[] | null>(null); // null: the featured systems
  const [allSystems, setAllSystems] = useState(false);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);

  useInitialParamsSync(initial, sets, index, (resolved) => {
    setSet(resolved.nextSet);
    setLang(resolved.nextLang);
    setChosen(resolved.nextChosen);
    setSort(resolved.nextSort);
  });
  useUrlParamReporting(sets, set, lang, chosen, sort, onParams);

  const { selected, shown, hiddenCount } = resolveShownSystems(available, featured, chosen, allSystems);
  const info = index.fixture_sets[set];
  const languages = info?.languages ?? [];
  const snapshots = snapshotsFor(index, set, selected);
  const setsByKind = useMemo(() => groupSetsByKind(sets, summary), [sets, summary]);

  const pickSet = (s: string) => {
    setSet(s);
    if (lang !== "all" && !index.fixture_sets[s]?.languages.includes(lang)) setLang("all");
  };

  return (
    <>
      {ready ? <Headline index={index} set={set} lang={lang} /> : <SetStatus set={set} part={part} retry={retryCurrentSet} />}

      {/* Until the first set's results land, only the headline placeholder shows: nothing below it
          jumps when they arrive (layout shift, LAB-1493). */}
      {opened && (
        <>
          <AcrossSets rows={across} summary={summary} current={set} onPick={pickSet} />
          <ExplorerFiltersSection
            set={set}
            setsByKind={setsByKind}
            summary={summary}
            lang={lang}
            languages={languages}
            onPickSet={pickSet}
            onLang={setLang}
            ready={ready}
            index={index}
            available={available}
            selected={selected}
            shown={shown}
            hiddenCount={hiddenCount}
            allSystems={allSystems}
            onToggleAllSystems={() => setAllSystems((v) => !v)}
            onChosen={setChosen}
            onToggleSystem={(k) => setChosen(toggleSystemSelection(k, selected, available))}
          />
          <SetOverviewNotes set={set} info={info} lang={lang} languages={languages} />
          {ready && (
            <SetChartsSections
              set={set}
              snapshots={snapshots}
              index={index}
              lang={lang}
              languages={languages}
              sort={sort}
              onSortChange={setSort}
              info={info}
              runsReady={runsReady}
              selected={selected}
            />
          )}
          {index.visual.length > 0 && (
            <Section
              id="bench-visual"
              title="Image masking"
              note="Share of labeled image regions masked (IoU ≥ 0.5). Official specimen IDs and fictional Muse Image documents are different sets: compare runs within a set."
            >
              <VisualTable index={index} />
            </Section>
          )}
          <RunLogDetails index={index} setsCount={sets.length} runLog={runLog} runsReady={runsReady} retryRuns={retryRuns} />
        </>
      )}
      <p className="text-xs text-faint">
        Generated by <code className="font-mono">pii-guard eval report</code> from <code className="font-mono">eval/results/runs/</code>. Add a run with{" "}
        <code className="font-mono">pii-guard eval --record &lt;slug&gt;</code>.
      </p>
    </>
  );
}

/** In place of a set's results while they load, or when they could not be loaded. */
function SetStatus({ set, part, retry }: { set: string; part: SetLoad | undefined; retry: () => void }) {
  if (part?.state === "error") {
    return (
      <Notice tone="danger" live title={`The results for ${set} could not be loaded.`}>
        <p>Check your connection and try again.</p>
        <Button size="sm" onClick={retry}>
          Retry dataset results
        </Button>
      </Notice>
    );
  }
  return (
    <div role="status" aria-label={`Loading results for ${set}`} className="space-y-2 border-l-2 border-line py-1 pl-4">
      <div className="h-5 w-3/4 max-w-2xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
      <div className="h-3 w-1/2 max-w-xl animate-pulse rounded bg-surface-2 motion-reduce:animate-none" />
    </div>
  );
}
