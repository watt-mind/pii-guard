import { useMemo, useRef, useState, type ReactNode } from "react";
import { LABELLED_SCENARIOS, labelledScenarioFor, sendDemoTraffic, type DemoProgress, type LabelledMatch } from "../api/demoTraffic";
import { ApiError } from "../api/http";
import type { TrafficConnectOptions, TrafficEvent, TrafficStatus } from "../api/traffic";
import type { EntityType } from "../api/types";
import { MaskedText } from "../components/MaskedText";
import { RestoredText } from "../components/RestoredText";
import { Pane } from "../components/Pane";
import { Button, Card, Checkbox, Metric, PageHeader, Select } from "../components/ui";
import { errorCopy } from "../lib/errorCopy";
import { useTraffic, type TrafficHandle, type TrafficSource } from "../hooks/useTraffic";
import { ENTITY_META, metaFor } from "../lib/entities";
import { tokenize } from "../lib/placeholders";
import {
  OUTCOME_LABEL,
  SESSION_SOURCE_LABEL,
  alignValues,
  canShowOriginals,
  clock,
  detectorName,
  formatMsShort,
  maskedCounts,
  modeOrder,
  percentile,
  requestExtras,
  requestMessages,
  requestTools,
  responseChoices,
  refusalReason,
  totalMasked,
  type Message,
} from "../lib/traffic";
import { NerHint } from "../components/NerHint";
import { TimingWaterfall } from "./TrafficCharts";

export interface TrafficProps {
  /** Replay the recorded demo traffic (the header's engine is set to Demo engine). */
  forceFixture?: boolean;
  /** Injectable for tests. */
  connect?: (o: TrafficConnectOptions) => { close(): void };
  sendDemo?: typeof sendDemoTraffic;
  fixtureIntervalMs?: number;
  /** The page's host name (originals are shown only on localhost). */
  pageHost?: string;
}

export interface LogsProps extends Omit<TrafficProps, "connect" | "fixtureIntervalMs"> {
  t: TrafficHandle;
  /** The server's upstream is the offline mock (`/v1/status`): its "model" only echoes. */
  mockUpstream?: boolean;
  /** Open this call (from an Overview chart); a new nonce re-opens the same one. */
  focus?: { id: string; nonce: number } | null;
  /** Open a call's vault session in the Vault screen (by its `session_ref`). */
  onOpenSession?: (ref: string) => void;
  /** Offer "Send demo traffic" (`offersDemoTraffic`); off where the server has accounts. */
  demoTraffic?: boolean;
}


type Filters = { mode: string; type: EntityType | "all"; problems: boolean };

/** The Logs screen with its own traffic connection (tests, and embedding on its own). */
export function Traffic({ forceFixture = false, connect, fixtureIntervalMs, ...rest }: TrafficProps & Pick<LogsProps, "demoTraffic">) {
  const t = useTraffic({ forceFixture, connect, fixtureIntervalMs });
  return <Logs t={t} forceFixture={forceFixture} {...rest} />;
}

export function Logs({ t, forceFixture = false, sendDemo = sendDemoTraffic, pageHost = globalThis.location?.hostname ?? "", mockUpstream = false, focus = null, onOpenSession, demoTraffic = true }: LogsProps) {
  const [filters, setFilters] = useState<Filters>({ mode: "all", type: "all", problems: false });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cleared, setCleared] = useState(0);
  const detailRef = useRef<HTMLDivElement>(null);
  const lastTime = t.events.length ? Date.parse(t.events[t.events.length - 1]!.time) : 0;

  const filtered = useMemo(
    () =>
      t.events.filter(
        (e) =>
          (filters.mode === "all" || e.mode === filters.mode) &&
          (filters.type === "all" || (maskedCounts(e)[filters.type] ?? 0) > 0 || (e.entities?.detected[filters.type] ?? 0) > 0) &&
          (!filters.problems || e.outcome !== "ok"),
      ),
    [t.events, filters],
  );
  const modes = useMemo(() => modeOrder([...new Set(t.events.map((e) => e.mode ?? "unknown"))]), [t.events]);
  const types = useMemo(
    () => [...new Set(t.events.flatMap((e) => [...Object.keys(e.entities?.detected ?? {}), ...Object.keys(maskedCounts(e))]))].sort() as EntityType[],
    [t.events],
  );

  // Follow the latest call until one is picked; keep the pick while it's still in the list.
  const selected = (selectedId && filtered.find((e) => e.id === selectedId)) || filtered[filtered.length - 1] || null;
  const following = !selectedId || !filtered.some((e) => e.id === selectedId);

  const pick = (id: string, scroll = false) => {
    setSelectedId(id);
    if (scroll && window.matchMedia?.("(max-width: 1023px)").matches) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // A call opened from the Overview: select it, with the filters cleared so it is in the list.
  const [focused, setFocused] = useState<number | null>(null);
  if (focus && focus.nonce !== focused) {
    setFocused(focus.nonce);
    setSelectedId(focus.id);
    setFilters({ mode: "all", type: "all", problems: false });
  }

  const overheads = filtered.map((e) => e.timing.overhead_ms);
  const p50 = percentile(overheads, 50);
  const p95 = percentile(overheads, 95);
  const masked = filtered.reduce((n, e) => n + totalMasked(e), 0);
  const problems = filtered.filter((e) => e.outcome !== "ok").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Logs"
        lead={
          <>
            {t.source === "fixture" ? "Recorded calls, replayed in your browser." : "Every call through the gateway, live."} Pick one to see what your client sent, what the model
            received, and what your client got back with the values restored.
          </>
        }
      />

      <SourceBanner source={t.source} status={t.status} apiStatus={t.apiStatus} forced={forceFixture} paused={t.paused} onFixture={t.showFixture} onRetry={t.retryApi} replayDone={t.replayDone} onReplay={t.replay} />

      <section aria-label="Controls" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={t.paused ? "primary" : "secondary"}
            onClick={() => t.setPaused(!t.paused)}
            aria-pressed={t.paused}
            disabled={t.replayDone && !t.paused}
            title={t.replayDone && !t.paused ? "The recorded replay has finished" : undefined}
          >
            {t.paused ? (
              <>
                <PlayIcon /> Resume{t.held ? ` (${t.held} new)` : ""}
              </>
            ) : (
              <>
                <PauseIcon /> Pause
              </>
            )}
          </Button>
          <Button
            onClick={() => {
              t.clear();
              setSelectedId(null);
              setCleared((n) => n + 1);
            }}
            disabled={!t.events.length && !t.held}
            title="Clears this page only; the server keeps its log"
          >
            Clear view
          </Button>
          {t.source === "api" && t.status.state === "live" && demoTraffic && <DemoButton key={cleared} send={sendDemo} />}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <label className="flex items-center gap-2 text-muted">
            Mode
            <span className="w-32">
              <Select value={filters.mode} onChange={(e) => setFilters({ ...filters, mode: e.target.value })}>
                <option value="all">All</option>
                {modes.map((m) => (
                  <option key={m} value={m}>
                    {m.charAt(0).toUpperCase() + m.slice(1)}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          <label className="flex items-center gap-2 text-muted">
            Entity
            <span className="w-44">
              <Select value={filters.type} onChange={(e) => setFilters({ ...filters, type: e.target.value as Filters["type"] })}>
                <option value="all">All types</option>
                {types.map((ty) => (
                  <option key={ty} value={ty}>
                    {ENTITY_META[ty]?.label ?? ty}
                  </option>
                ))}
              </Select>
            </span>
          </label>
          <Checkbox label="Blocked or failed only" checked={filters.problems} onChange={(e) => setFilters({ ...filters, problems: e.target.checked })} />
        </div>
      </section>

      <dl className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:gap-x-8" aria-label="Summary of the calls shown">
        <Metric label={filtered.length === t.events.length ? "Calls" : `Calls (of ${t.events.length}, filtered)`} value={filtered.length} />
        <Metric label="Overhead p50, all shown" value={formatMsShort(p50)} />
        <Metric label="Overhead p95, all shown" value={formatMsShort(p95)} />
        <Metric label="Values masked" value={masked} />
        <Metric label="Blocked or failed" value={problems} />
      </dl>

      <div className="grid gap-6 lg:grid-cols-[minmax(19rem,25rem)_minmax(0,1fr)]">
        <section aria-labelledby="calls-title" className="flex min-w-0 flex-col rounded-xl border border-line bg-surface">
          <header className="flex items-start justify-between gap-2 border-b border-line p-4 sm:p-5">
            <div className="min-w-0">
              <h2 id="calls-title" className="text-lg font-normal text-ink">
                Calls
              </h2>
              <p className="mt-0.5 text-sm text-muted">Newest first</p>
            </div>
            <span aria-live="polite" className="pt-1.5 text-xs whitespace-nowrap text-muted tabular-nums">
              {t.paused ? "paused" : lastTime ? `last ${clock(new Date(lastTime).toISOString())}` : ""}
            </span>
          </header>
          {filtered.length === 0 ? (
            <div className="p-4 sm:p-5">
              <EmptyCalls hasAny={t.events.length > 0} source={t.source} status={t.status} replayDone={t.replayDone} demoTraffic={demoTraffic} />
            </div>
          ) : (
            <ul aria-label="Calls through the gateway" className="relative max-h-[26rem] divide-y divide-line overflow-y-auto lg:max-h-[46rem]" data-testid="call-list">
              {[...filtered].reverse().map((e) => (
                <li key={e.id}>
                  <CallRow event={e} selected={selected?.id === e.id} onSelect={() => pick(e.id, true)} mockUpstream={mockUpstream} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <div ref={detailRef} className="min-w-0 scroll-mt-4 space-y-6">
          {selected ? (
            <CallDetail event={selected} following={following} source={t.source} pageHost={pageHost} onFollow={() => setSelectedId(null)}
              mockUpstream={mockUpstream}
              onOpenSession={t.source === "api" ? onOpenSession : undefined}
            />
          ) : (
            <div className="flex min-h-[14rem] flex-col items-center justify-center rounded-xl border border-line px-6 py-10 text-center">
              <p className="text-sm font-medium text-ink">No call selected</p>
              <p className="mt-1 max-w-sm text-sm text-muted">Calls appear here as they go through the gateway. Pick one to see what the model received.</p>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}

// --- Source / status ----------------------------------------------------------------------

function SourceBanner({
  source,
  status,
  apiStatus,
  forced,
  paused,
  onFixture,
  onRetry,
  replayDone,
  onReplay,
}: {
  source: TrafficSource;
  status: TrafficStatus;
  apiStatus: TrafficStatus;
  forced: boolean;
  paused: boolean;
  onFixture: () => void;
  onRetry: () => void;
  replayDone: boolean;
  onReplay: () => void;
}) {
  const code = (s: string) => <code className="rounded bg-surface px-1 font-mono text-xs">{s}</code>;
  if (source === "fixture") {
    return (
      <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
        <p className="min-w-0 flex-1">
          <strong className="font-medium text-warn">Recorded demo traffic.</strong>{" "}
          {forced
            ? "The engine is set to Demo engine, so these are calls recorded from the demo stack, replayed in your browser. Switch the engine to Auto or Live API to follow the gateway."
            : apiStatus.state === "disabled"
              ? "The API's traffic log is off, so these are calls recorded from the demo stack, replayed in your browser."
              : apiStatus.state === "offline"
                ? "The API isn't reachable, so these are calls recorded from the demo stack, replayed in your browser."
                : "You picked the recorded demo: these are calls recorded from the demo stack, replayed in your browser. Your server's own log is one click away."}{" "}
          Recorded at level {code("masked")}: they hold only what the model received.
        </p>
        {!forced && (
          <Button size="sm" onClick={onRetry}>
            Back to the live log
          </Button>
        )}
        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 border-t border-warn/30 pt-2">
          <p className="min-w-0 flex-1 font-medium" data-testid="replay-state">
            {replayDone
              ? "Replay finished: every recorded call was played once."
              : paused
                ? "Replay paused. Press Resume to continue."
                : "Replaying the recorded calls once…"}
          </p>
          {/* Always rendered (aria-disabled while playing) so focus stays on it after a replay. */}
          <Button
            size="sm"
            onClick={() => replayDone && onReplay()}
            aria-disabled={!replayDone}
            title={replayDone ? "Play the recorded calls again from the start" : "Available when the replay has finished"}
          >
            Replay again
          </Button>
        </div>
      </div>
    );
  }
  if (status.state === "disabled") {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink">
        <p className="min-w-0 flex-1">
          <strong className="font-medium">The traffic log is off on this server.</strong>{" "}
          {status.reason === "off" ? (
            <>
              Restart the API with its traffic log on ({code("PII_GUARD_TRAFFIC_LOG=masked")}; {code("make demo")} does this). On localhost, level {code("full")} also shows
              the original values.
            </>
          ) : (
            <>{status.message}.</>
          )}
        </p>
        <Button size="sm" onClick={onFixture}>
          Show recorded demo traffic
        </Button>
      </div>
    );
  }
  if (status.state === "offline") {
    return (
      <div role="alert" className="rounded-xl border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-ink">
        <strong className="font-medium text-danger">Lost the connection to the API.</strong> Retrying every few seconds; the calls already shown stay. ({status.message})
      </div>
    );
  }
  if (status.state === "limited") {
    const wait = status.retryAfterMs ? ` in about ${Math.ceil(status.retryAfterMs / 1000)} s` : " shortly";
    return (
      <div role="status" className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
        <strong className="font-medium text-warn">Too many requests just now.</strong> The API is up but asked this page to slow down; it retries{wait}. The calls already shown stay.
      </div>
    );
  }
  if (status.state === "denied") {
    return (
      <div role="alert" className="rounded-xl border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-ink">
        {status.reason === "signed_out" ? (
          <>
            <strong className="font-medium text-danger">You're signed out.</strong> The API is up but answered 401. Sign in again; this page reconnects by itself.
          </>
        ) : (
          <>
            <strong className="font-medium text-danger">This account can't read this traffic log.</strong> The API is up but answered 403. Check the selected project, or sign in with the account
            that owns it.
          </>
        )}
      </div>
    );
  }
  return (
    <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted">
      {status.state === "connecting" ? (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-faint motion-safe:animate-pulse" /> Connecting…
        </span>
      ) : (
        <>
          {paused ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/40 bg-warn-soft px-2.5 py-1 text-xs font-medium text-warn">
              <PauseIcon /> Paused · new calls are held
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-guard/40 bg-guard-soft px-2.5 py-1 text-xs font-medium text-guard-ink">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-guard motion-safe:animate-pulse" />
              Live · {status.via === "sse" ? "streaming" : "polling every 2 s"}
            </span>
          )}
          <span title={`Traffic log level: ${status.level}`} className="inline-flex items-center rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium text-ink">
            {status.level === "full" ? "Originals logged" : "Placeholders only"}
          </span>
          <span className="text-xs">
            {status.level === "full" ? "Originals are kept in memory on this machine only." : "Only what left the machine is logged: placeholders, never values."}
          </span>
        </>
      )}
    </div>
  );
}

function EmptyCalls({ hasAny, source, status, replayDone, demoTraffic }: { hasAny: boolean; source: TrafficSource; status: TrafficStatus; replayDone: boolean; demoTraffic: boolean }) {
  if (hasAny) return <p className="py-6 text-center text-sm text-muted">No call matches these filters.</p>;
  if (source === "fixture" && replayDone)
    return (
      <p className="py-6 text-center text-sm text-muted">
        The recorded replay has finished. Press <strong className="text-ink">Replay again</strong> to watch it from the start.
      </p>
    );
  if (status.state === "disabled") return <p className="py-6 text-center text-sm text-muted">Nothing to show while the traffic log is off.</p>;
  return (
    <div className="py-6 text-center text-sm text-muted">
      <p className="font-medium text-ink">{status.state === "connecting" ? "Connecting…" : "Waiting for the first call"}</p>
      {source === "api" && status.state === "live" && !demoTraffic && <p className="mt-1">Connect a client to one of your endpoints (Connect), or mask a text in the Playground.</p>}
      {source === "api" && status.state === "live" && demoTraffic && (
        <p className="mt-1">
          Press <strong className="text-ink">Send demo traffic</strong>, run <code className="font-mono text-xs">make demo-traffic</code>, or point an OpenAI client at{" "}
          <code className="font-mono text-xs">/v1</code> of the gateway.
        </p>
      )}
    </div>
  );
}

const LABELLED_NOTE = LABELLED_SCENARIOS.length
  ? `; ${LABELLED_SCENARIOS.length} labelled “${LABELLED_SCENARIOS[0]!.label}”: in rules-only mode its name is an expected miss`
  : "";

export function DemoButton({ send }: { send: typeof sendDemoTraffic }) {
  const [state, setState] = useState<{ running: boolean; progress: DemoProgress | null; error: string | null }>({ running: false, progress: null, error: null });
  const run = async () => {
    setState({ running: true, progress: null, error: null });
    try {
      const p = await send({ onProgress: (progress) => setState((s) => ({ ...s, progress })) });
      setState({ running: false, progress: p, error: null });
    } catch (err) {
      setState({
        running: false,
        progress: null,
        error: err instanceof ApiError ? err.message : "the gateway could not be reached",
      });
    }
  };
  const p = state.progress;
  return (
    <>
      <Button variant="primary" onClick={() => void run()} busy={state.running}>
        <SendIcon /> {state.running ? "Sending…" : "Send demo traffic"}
      </Button>
      <span aria-live="polite" className="text-xs text-muted tabular-nums">
        {state.running && p ? `${p.done} of ${p.total} sent` : null}
        {!state.running && p
          ? `Sent ${p.done} fictional calls${p.refused ? `; ${p.refused} refused (an image without SAM is refused: fail closed)` : ""}${LABELLED_NOTE}.`
          : null}
        {state.error ? <span className="text-danger">Could not send: {state.error}.</span> : null}
      </span>
    </>
  );
}

// --- List ---------------------------------------------------------------------------------

function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "ok") return null;
  const blocked = outcome === "blocked" || outcome === "refused";
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset",
        blocked ? "bg-warn-soft text-warn ring-warn/40" : "bg-danger-soft text-danger ring-danger/40",
      ].join(" ")}
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="8" cy="8" r="6" />
        <path d="M4 12 12 4" />
      </svg>
      {OUTCOME_LABEL[outcome] ?? outcome}
    </span>
  );
}

/**
 * A labelled demo scenario: its name needs the NER. When the name went through, that is a leak,
 * shown with the leak treatment even though it is expected; when the NER caught it, a neutral tag.
 */
function LabelTag({ match }: { match: LabelledMatch }) {
  const missed = match.missed.length > 0;
  return (
    <span
      title={`Demo scenario labelled “${match.scenario.label}”${missed ? ": in rules-only mode its name is an expected miss" : ""}`}
      className={[
        "rounded-sm px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap ring-1 ring-inset",
        missed ? "bg-leak-soft text-leak ring-leak/40" : "text-muted ring-line-strong",
      ].join(" ")}
    >
      needs NER{missed ? <span className="font-normal"> · leaked, expected</span> : null}
    </span>
  );
}

/** Why the labelled demo call's name reached the model as written (or that the NER caught it). */
function LabelledNote({ match }: { match: LabelledMatch }) {
  const missed = match.missed.length > 0;
  return (
    <div role="note" className={["mt-3 rounded-lg border p-3 text-sm", missed ? "border-leak/40 bg-leak-soft" : "border-line bg-surface-2"].join(" ")}>
      <p className={["font-medium", missed ? "text-leak" : "text-ink"].join(" ")}>
        Demo scenario {match.scenario.name}: {match.scenario.label}.{" "}
        {missed ? "Expected miss in rules-only mode." : "The NER ran and masked the name."}
      </p>
      <p className="mt-1 text-ink">
        {missed ? (
          <>
            This call names a person in free text, with no pre-loaded known value and nothing a rule can recognise, so the name ({match.missed.join(", ")}) reached the
            mock model as written. Every other demo call masks its names, because they are pre-loaded as session known values. This one is kept on purpose, to show what
            the NER adds. With <NerHint />, it is masked too.
          </>
        ) : (
          <>Without the NER this free-text name would reach the model as written: no known value and no rule covers it.</>
        )}
      </p>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="rounded px-1.5 py-0.5 text-2xs font-medium text-muted ring-1 ring-line ring-inset">{children}</span>;
}

function EntityChips({ counts }: { counts: Partial<Record<EntityType, number>> }) {
  const entries = (Object.entries(counts) as [EntityType, number][]).filter(([, n]) => n > 0);
  if (!entries.length) return <span className="text-xs text-faint">nothing masked</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([type, n]) => (
        <span key={type} title={`${metaFor(type).label}: ${n} masked`} className={["rounded-md px-1.5 py-px font-mono text-2xs font-medium ring-1 ring-inset", metaFor(type).chip].join(" ")}>
          {metaFor(type).short} {n}
          <span className="sr-only"> {metaFor(type).label}</span>
        </span>
      ))}
    </span>
  );
}

/** The model a call went to; the offline mock upstream only echoes, whatever model was asked for (LAB-1264). */
function modelOf(e: TrafficEvent, mockUpstream: boolean): string {
  if (e.outcome === "blocked" || e.outcome === "refused") return "not forwarded";
  if (mockUpstream) return "mock upstream (echo)";
  return e.upstream?.model ?? e.model ?? "–";
}

function CallRow({ event: e, selected, onSelect, mockUpstream }: { event: TrafficEvent; selected: boolean; onSelect: () => void; mockUpstream: boolean }) {
  const hasTools = requestTools(e.request?.masked ?? e.request?.original).length > 0;
  const hasImage = (e.entities?.images?.count ?? 0) > 0;
  const labelled = labelledScenarioFor(e);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={[
        "flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors sm:px-5",
        selected ? "bg-model-soft/70 shadow-[inset_3px_0_0_var(--model)]" : "hover:bg-surface-2",
      ].join(" ")}
    >
      <span className="flex w-full items-center gap-2 text-xs">
        <span className="font-mono whitespace-nowrap text-muted tabular-nums">{clock(e.time)}</span>
        {e.mode && <Tag>{e.mode}</Tag>}
        {e.stream && <Tag>stream</Tag>}
        {hasTools && <Tag>tools</Tag>}
        {hasImage && <Tag>image</Tag>}
        {labelled && <LabelTag match={labelled} />}
        <OutcomeBadge outcome={e.outcome} />
        <span className="ml-auto font-medium whitespace-nowrap text-ink tabular-nums" title="pii-guard overhead">
          +{formatMsShort(e.timing.overhead_ms)}
        </span>
      </span>
      <span className="flex w-full items-start justify-between gap-2">
        {labelled && labelled.missed.length > 0 && totalMasked(e) === 0 ? (
          <span className="text-xs text-leak">
            {labelled.missed.length} name reached the model: expected, needs NER
          </span>
        ) : (
          <EntityChips counts={maskedCounts(e)} />
        )}
        <span className="shrink-0 truncate text-xs text-faint">{e.outcome === "blocked" || e.outcome === "refused" ? "not forwarded" : mockUpstream ? "mock upstream" : (e.model ?? "")}</span>
      </span>
    </button>
  );
}

// --- Detail -------------------------------------------------------------------------------

function CallDetail({
  event: e,
  following,
  source,
  pageHost,
  onFollow,
  mockUpstream,
  onOpenSession,
}: {
  event: TrafficEvent;
  following: boolean;
  source: TrafficSource;
  pageHost: string;
  onFollow: () => void;
  mockUpstream: boolean;
  onOpenSession?: (ref: string) => void;
}) {
  const showOriginals = canShowOriginals(e, pageHost, source);
  const maskedBody = e.request?.masked;
  const forwarded = maskedBody !== undefined && maskedBody !== null;
  const labelled = labelledScenarioFor(e);
  // An upstream refusal reached the model's provider (masked); everything else here stopped in pii-guard (LAB-1335).
  const failCode = e.error?.code ?? (e.outcome === "upstream_error" ? "upstream_error" : e.outcome === "stream_error" ? "stream_failed" : undefined);
  const upstreamCopy = errorCopy(failCode, e.error?.status ?? e.upstream?.status ?? null);
  const upstreamSide = upstreamCopy.kind === "upstream" || upstreamCopy.kind === "stream";
  return (
    <>
      <section aria-labelledby="detail-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 id="detail-title" className="flex flex-wrap items-center gap-2 text-lg font-normal text-ink">
              Call at {clock(e.time)} <OutcomeBadge outcome={e.outcome} />
            </h2>
            <p className="mt-0.5 font-mono text-xs break-all text-faint">{e.id}</p>
          </div>
          {following ? (
            <span className="rounded-full bg-surface-2 px-2.5 py-1 text-xs text-muted ring-1 ring-line">Following the latest call</span>
          ) : (
            <Button size="sm" onClick={onFollow}>
              Follow the latest call
            </Button>
          )}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <Meta label="Mode" value={e.mode ?? "–"} />
          <Meta label="Model" value={modelOf(e, mockUpstream)} />
          <Meta label="Language" value={e.language ?? "auto"} />
          <Meta label="Session" value={e.session_ref ? `${e.session_new ? "new" : "continued"} · ${e.session_ref}` : "–"} />
          <Meta label="Session from" value={e.session_source ? (SESSION_SOURCE_LABEL[e.session_source] ?? e.session_source) : "–"} />
          <Meta label="Detectors" value={e.detectors.length ? e.detectors.map((d) => detectorName(d)).join(", ") : "–"} />
          <Meta label="Upstream" value={e.upstream?.status ? `HTTP ${e.upstream.status}` : "not called"} />
          <Meta label="Tokens" value={e.usage?.total_tokens !== undefined ? `${e.usage.prompt_tokens ?? "?"} in · ${e.usage.completion_tokens ?? "?"} out` : "–"} />
          <Meta label="Detection cache" value={e.cache ? `${e.cache.hits} hit · ${e.cache.misses} miss` : "–"} />
        </dl>
        {e.session_ref && onOpenSession && (
          <Button size="sm" className="mt-3" onClick={() => onOpenSession(e.session_ref!)}>
            Open session <span className="font-mono">{e.session_ref}</span> in Vault
          </Button>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>Masked:</span>
          <EntityChips counts={maskedCounts(e)} />
          {labelled && labelled.missed.length > 0 ? <span className="text-leak">· {labelled.missed.length} name reached the model (expected, needs NER)</span> : null}
          {e.upstream?.unresolved_placeholders ? (
            <span className="rounded-sm bg-leak-soft px-2 py-0.5 font-medium text-leak ring-1 ring-leak/40">
              {e.upstream.unresolved_placeholders} placeholder{e.upstream.unresolved_placeholders === 1 ? "" : "s"} the model invented (not restored)
            </span>
          ) : null}
        </div>
        {labelled && <LabelledNote match={labelled} />}
      </section>

      {e.outcome !== "ok" && (!forwarded || upstreamSide) && (
        <div role="note" data-error-kind={upstreamSide ? upstreamCopy.kind : e.outcome === "blocked" ? "policy" : "fail_closed"} className="rounded-xl border border-warn/40 bg-warn-soft p-4 text-sm">
          <p className="font-medium text-warn">
            {upstreamSide ? upstreamCopy.title : `${e.outcome === "blocked" ? "Blocked by policy." : "Refused."} Nothing was sent to the model.`}
          </p>
          <p className="mt-1 text-ink">
            <code className="font-mono text-xs">{e.error?.code ?? e.outcome}</code>
            {e.error?.status ? ` · HTTP ${e.error.status}` : ""}
            {e.error?.entity_types ? ` · ${Object.entries(e.error.entity_types).map(([k, n]) => `${metaFor(k as EntityType).label} ×${n}`).join(", ")}` : ""}
          </p>
          <p className="mt-2 text-muted">
            {upstreamSide ? upstreamCopy.body : refusalReason(e.error?.code, Boolean(e.entities?.images))}
          </p>
        </div>
      )}

      <section aria-labelledby="timing-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <h2 id="timing-title" className="mb-4 text-lg font-normal text-ink">
          Timing
        </h2>
        <TimingWaterfall event={e} />
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <DetailPane id="log-original" eyebrow="Your app sent" title="Original request" side="you">
          {showOriginals && e.request?.original ? (
            <OriginalView original={e.request.original} masked={maskedBody} />
          ) : (
            <Quiet>
              {source === "fixture" ? (
                <>Recorded demo traffic never holds original values.</>
              ) : e.level === "full" ? (
                <>The server logged originals, but they are only shown on a page served from localhost.</>
              ) : (
                <>
                  Not kept: the traffic log holds only what left the machine (level <code className="font-mono">masked</code>). To see originals here, run the API on localhost
                  with its traffic log at level full, with fictional data only (<code className="font-mono">PII_GUARD_TRAFFIC_LOG=full</code>).
                </>
              )}
            </Quiet>
          )}
        </DetailPane>
        <DetailPane id="log-masked" eyebrow="The model received" title="Masked request, as sent upstream" side="model">
          {forwarded ? <MaskedRequestView body={maskedBody} event={e} /> : <Quiet>Nothing was forwarded.</Quiet>}
        </DetailPane>
        <DetailPane id="log-response" eyebrow="The model answered" title="Response, masked → restored" side="model" wide>
          <ResponseView event={e} showOriginals={showOriginals} />
        </DetailPane>
      </div>
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="truncate text-ink" title={value}>
        {value}
      </dd>
    </div>
  );
}

/** A request or response pane: the shared `Pane`, its body capped and scrolled. */
function DetailPane({ id, eyebrow, title, side, wide, children }: { id: string; eyebrow: string; title: string; side: "you" | "model"; wide?: boolean; children: ReactNode }) {
  return (
    <Pane id={id} eyebrow={eyebrow} title={title} side={side} scroll className={wide ? "md:col-span-2" : ""}>
      <div className="space-y-3">{children}</div>
    </Pane>
  );
}

/** A quiet note inside a pane (no card inside a card). */
function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}

function Role({ role }: { role: string }) {
  return <p className="mb-1 font-mono text-2xs text-muted">{role}</p>;
}

function ImagePart({ summary, event }: { summary: string; event?: TrafficEvent }) {
  const img = event?.entities?.images;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-field bg-surface-2 p-3 text-xs text-muted">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-8 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <rect x="6" y="8" width="5" height="5" fill="currentColor" />
        <path d="M13 9h5M13 12h5M6 16h12" />
      </svg>
      <p>
        <span className="font-medium text-ink">Image</span> <span className="font-mono">{summary}</span>
        <br />
        {img
          ? `${Object.values(img.masked).reduce((a, b) => a + (b ?? 0), 0)} regions blacked out, ${Object.values(img.kept).reduce((a, b) => a + (b ?? 0), 0)} kept, OCR ${img.ocr ? "on" : "off"}. `
          : ""}
        The log keeps a summary of each image, not its pixels.
      </p>
    </div>
  );
}

function MessageList({ messages, event }: { messages: Message[]; event?: TrafficEvent }) {
  return (
    <>
      {messages.map((m, i) => (
        <div key={i}>
          <Role role={m.role} />
          <div className="space-y-2">
            {m.parts.map((p, j) => (p.kind === "text" ? <MaskedText key={j} text={p.text} /> : <ImagePart key={j} summary={p.summary} event={event} />))}
            {m.toolCalls.map((c, j) => (
              <ToolCallView key={`t${j}`} name={c.name}>
                <MaskedText text={c.arguments} />
              </ToolCallView>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ToolCallView({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-line p-2">
      <p className="mb-1 font-mono text-2xs text-muted">
        tool call · <span className="text-ink">{name}</span>
      </p>
      {children}
    </div>
  );
}

function MaskedRequestView({ body, event }: { body: unknown; event: TrafficEvent }) {
  const tools = requestTools(body);
  const extras = requestExtras(body);
  return (
    <div data-testid="masked-request" className="space-y-3">
      <DetectorCaveat event={event} />
      <MessageList messages={requestMessages(body)} event={event} />
      {tools.length > 0 && (
        <details className="rounded-lg border border-line p-2" open>
          <summary className="cursor-pointer text-xs font-medium text-ink">
            Tools ({tools.length}) <span className="font-normal text-muted">definitions are masked like messages</span>
          </summary>
          <div className="mt-2 space-y-2">
            {tools.map((tool, i) => (
              <MaskedText key={i} text={tool.json} />
            ))}
          </div>
        </details>
      )}
      {extras && (
        <details className="rounded-lg border border-line p-2">
          <summary className="cursor-pointer text-xs font-medium text-ink">Other fields</summary>
          <div className="mt-2">
            <MaskedText text={extras} />
          </div>
        </details>
      )}
    </div>
  );
}

function AlignedText({ masked, value, outgoing }: { masked: string; value: string; outgoing?: boolean }) {
  const segments = alignValues(masked, value);
  if (!segments) return <div className="doc text-ink">{value}</div>;
  return <RestoredText segments={segments} outgoing={outgoing} />;
}

function OriginalView({ original, masked }: { original: unknown; masked: unknown }) {
  const orig = requestMessages(original);
  const mask = requestMessages(masked);
  return (
    <div data-testid="original-request" className="space-y-3">
      {orig.map((m, i) => (
        <div key={i}>
          <Role role={m.role} />
          <div className="space-y-2">
            {m.parts.map((p, j) => {
              const mp = mask[i]?.parts[j];
              if (p.kind === "image") return <ImagePart key={j} summary={p.summary} />;
              return mp?.kind === "text" ? <AlignedText key={j} masked={mp.text} value={p.text} outgoing /> : <div key={j} className="doc text-ink">{p.text}</div>;
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Which detectors ran, in words, and what they can't find: the Mask screen's caveat, per call. */
function DetectorCaveat({ event: e }: { event: TrafficEvent }) {
  const free = e.detectors.some((d) => d === "ner" || d === "llm");
  return (
    <p className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-muted">
      Only highlighted values were replaced; anything else reached the model as written.{" "}
      {free ? null : e.detectors.includes("known") ? (
        <>
          This call ran {e.detectors.map((d) => detectorName(d)).join(", ")}: pre-loaded known values (names included) and structured values (e-mail, phone, IBAN, IDs) are
          masked; other names need <NerHint />.
        </>
      ) : (
        <>
          This call ran {e.detectors.length ? e.detectors.map((d) => detectorName(d)).join(", ") : "no detector"} only, which finds structured values (e-mail, phone, IBAN, IDs) but{" "}
          <strong className="font-medium text-ink">not names</strong>: names need <NerHint />.
        </>
      )}
    </p>
  );
}

const placeholdersIn = (text: string) => tokenize(text).filter((t) => t.kind === "placeholder").length;

function ResponseView({ event: e, showOriginals }: { event: TrafficEvent; showOriginals: boolean }) {
  const masked = responseChoices(e.response?.masked);
  const unmasked = showOriginals ? responseChoices(e.response?.unmasked) : [];
  if (!e.response) return <Quiet>{e.outcome === "ok" ? "No answer was logged." : "No answer: the call did not reach the model."}</Quiet>;
  const nothing = masked.every((c) => !c.content && !c.toolCalls.length);
  const streamedTool = nothing && e.stream && e.outcome === "ok";
  const count = masked.reduce((n, c) => n + placeholdersIn(c.content ?? "") + c.toolCalls.reduce((k, t) => k + placeholdersIn(t.arguments), 0), 0);
  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
      <div data-testid="masked-response" className="min-w-0 space-y-2">
        <p className="mb-1 text-xs font-medium text-model">From the model{e.stream ? ` (streamed, ${e.response.chunks ?? "?"} chunks)` : ""}</p>
        {nothing ? (
          <Quiet>{e.stream ? "A streamed tool call: the log keeps streamed text, not tool-call arguments." : "Empty answer."}</Quiet>
        ) : (
          masked.map((c) => (
            <div key={c.index} className="space-y-2">
              {c.content !== null && <MaskedText text={c.content} />}
              {c.toolCalls.map((t, j) => (
                <ToolCallView key={j} name={t.name}>
                  <MaskedText text={t.arguments} />
                </ToolCallView>
              ))}
            </div>
          ))
        )}
      </div>
      <div aria-hidden="true" className="flex items-center gap-2 font-mono text-2xs text-guard md:flex-col md:justify-center">
        <span className="h-px flex-1 bg-guard/40 md:h-auto md:w-px" />
        <span className="whitespace-nowrap">pii-guard</span>
        <span className="text-faint">
          <span className="md:hidden">↓</span>
          <span className="hidden md:inline">→</span>
        </span>
        <span className="h-px flex-1 bg-guard/40 md:h-auto md:w-px" />
      </div>
      <div data-testid="unmasked-response" className="min-w-0 space-y-2">
        <p className="mb-1 text-xs font-medium text-guard">To your app</p>
        {showOriginals && unmasked.length ? (
          unmasked.map((c) => {
            const m = masked.find((x) => x.index === c.index);
            return (
              <div key={c.index} className="space-y-2">
                {c.content !== null && <AlignedText masked={m?.content ?? ""} value={c.content} />}
                {c.toolCalls.map((t, j) => (
                  <ToolCallView key={j} name={t.name}>
                    <AlignedText masked={m?.toolCalls[j]?.arguments ?? ""} value={t.arguments} />
                  </ToolCallView>
                ))}
              </div>
            );
          })
        ) : (
          <Quiet>
            {streamedTool
              ? "The streamed tool-call arguments were restored on the way to your app; the log doesn't keep them. "
              : count
                ? `${count} placeholder${count === 1 ? " was" : "s were"} put back before the answer reached your app. `
                : "Nothing to restore in this answer. "}
            {showOriginals ? "" : "The restored answer holds real values, so it is only logged at level full, on localhost."}
          </Quiet>
        )}
      </div>
    </div>
  );
}

// --- Bits ---------------------------------------------------------------------------------

export function ChartCard({ id, title, note, children }: { id: string; title: string; note: string; children: ReactNode }) {
  return (
    <Card title={title} titleId={`${id}-title`} subtitle={note} headingLevel={3} className="min-w-0">
      {children}
    </Card>
  );
}

const icon = "size-4";
function PauseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={icon} fill="currentColor">
      <rect x="4" y="3" width="3" height="10" rx="1" />
      <rect x="9" y="3" width="3" height="10" rx="1" />
    </svg>
  );
}
function PlayIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={icon} fill="currentColor">
      <path d="M5 3.5v9a.5.5 0 0 0 .77.42l7-4.5a.5.5 0 0 0 0-.84l-7-4.5A.5.5 0 0 0 5 3.5Z" />
    </svg>
  );
}
function SendIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={icon} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
      <path d="M2.5 8 13.5 2.5 11 13.5 8 9.5 2.5 8Z" />
      <path d="M8 9.5 13.5 2.5" />
    </svg>
  );
}
