import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { LABELLED_SCENARIOS, labelledScenarioFor, sendDemoTraffic, type DemoProgress } from "../api/demoTraffic";
import { ApiError } from "../api/http";
import type { TrafficConnectOptions, TrafficEvent, TrafficStatus } from "../api/traffic";
import type { EntityType } from "../api/types";
import { Button, Card, Checkbox, Metric, PageHeader, Select } from "../components/ui";
import { useHostedSession } from "../hosted/session";
import { useTraffic, type TrafficHandle, type TrafficSource } from "../hooks/useTraffic";
import { UNKNOWN_META, metaFor } from "../lib/entities";
import { clock, formatMsShort, maskedCounts, modeOrder, percentile, requestTools, totalMasked } from "../lib/traffic";
import { useSelectedEndpoint } from "../projects/selection";
import { CallDetail, EntityChips, LabelTag, OutcomeBadge } from "./TrafficDetail";

export { CallDetail, EntityChips, LabelTag, OutcomeBadge };

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

function entityOptionLabel(ty: EntityType | string): string {
  const meta = metaFor(ty);
  return meta === UNKNOWN_META ? ty : meta.label;
}

function matchesLogFilters(e: TrafficEvent, filters: Filters): boolean {
  if (filters.mode !== "all" && e.mode !== filters.mode) return false;
  if (filters.type !== "all" && (maskedCounts(e)[filters.type] ?? 0) === 0 && (e.entities?.detected[filters.type] ?? 0) === 0) return false;
  return !filters.problems || e.outcome !== "ok";
}

function PauseResumeButton({ t }: { t: TrafficHandle }) {
  const doneAndRunning = t.replayDone && !t.paused;
  return (
    <Button
      variant={t.paused ? "primary" : "secondary"}
      onClick={() => t.setPaused(!t.paused)}
      aria-pressed={t.paused}
      disabled={doneAndRunning}
      title={doneAndRunning ? "The recorded replay has finished" : undefined}
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
  );
}

interface LogControlsBarProps {
  t: TrafficHandle;
  demoTraffic: boolean;
  sendDemo: typeof sendDemoTraffic;
  cleared: number;
  onClear: () => void;
  modes: string[];
  types: EntityType[];
  filters: Filters;
  onFilters: (f: Filters) => void;
}

function LogControlsBar({ t, demoTraffic, sendDemo, cleared, onClear, modes, types, filters, onFilters }: LogControlsBarProps) {
  const showDemo = t.source === "api" && t.status.state === "live" && demoTraffic;
  return (
    <section aria-label="Controls" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 sm:p-5 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <PauseResumeButton t={t} />
        <Button onClick={onClear} disabled={!t.events.length && !t.held} title="Clears this page only; the server keeps its log">
          Clear view
        </Button>
        {showDemo && <DemoButton key={cleared} send={sendDemo} />}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <label className="flex items-center gap-2 text-muted">
          Mode
          <span className="w-32">
            <Select value={filters.mode} onChange={(e) => onFilters({ ...filters, mode: e.target.value })}>
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
            <Select value={filters.type} onChange={(e) => onFilters({ ...filters, type: e.target.value as Filters["type"] })}>
              <option value="all">All types</option>
              {types.map((ty) => (
                <option key={ty} value={ty}>
                  {entityOptionLabel(ty)}
                </option>
              ))}
            </Select>
          </span>
        </label>
        <Checkbox label="Blocked or failed only" checked={filters.problems} onChange={(e) => onFilters({ ...filters, problems: e.target.checked })} />
      </div>
    </section>
  );
}

/**
 * "Open session in <endpoint>" re-scopes the console, which remounts it (LAB-1619): the call
 * to reopen, and to put focus back on, once the endpoint's log has it.
 */
let reopenAfterSwitch: string | null = null;

/** The Logs screen with its own traffic connection (tests, and embedding on its own). */
export function Traffic({ forceFixture = false, connect, fixtureIntervalMs, ...rest }: TrafficProps & Pick<LogsProps, "demoTraffic" | "onOpenSession" | "focus">) {
  const t = useTraffic({ forceFixture, connect, fixtureIntervalMs });
  return <Logs t={t} forceFixture={forceFixture} {...rest} />;
}

function useReopenFocus(selectedId: string | undefined) {
  useEffect(() => {
    if (!reopenAfterSwitch || selectedId !== reopenAfterSwitch) return;
    reopenAfterSwitch = null;
    (document.getElementById("open-session") ?? document.getElementById("detail-title"))?.focus();
  }, [selectedId]);
}

function useExternalLogFocus(focus: { id: string; nonce: number } | null, selectedId: string | undefined, onFocusCall: (id: string) => void) {
  const [focused, setFocused] = useState<number | null>(null);
  // Focus follows to the call once it is in the list (Connect's test request, LAB-1626), never to <body>.
  const [focusTo, setFocusTo] = useState<{ id: string; nonce: number } | null>(null);
  const focusedFor = useRef<number | null>(null);
  if (focus && focus.nonce !== focused) {
    setFocused(focus.nonce);
    setFocusTo(focus);
    onFocusCall(focus.id);
  }
  useEffect(() => {
    if (!focusTo || focusedFor.current === focusTo.nonce || selectedId !== focusTo.id) return;
    focusedFor.current = focusTo.nonce;
    document.getElementById("detail-title")?.focus();
  }, [focusTo, selectedId]);
}

function resolveSelectedCall(filtered: TrafficEvent[], selectedId: string | null): { selected: TrafficEvent | null; following: boolean } {
  const matched = selectedId ? filtered.find((e) => e.id === selectedId) : undefined;
  const selected = matched ?? filtered[filtered.length - 1] ?? null;
  return { selected, following: !matched };
}

function CallListHeader({ paused, events }: { paused: boolean; events: TrafficEvent[] }) {
  const lastTime = events.length ? Date.parse(events[events.length - 1]!.time) : 0;
  const statusText = paused ? "paused" : lastTime ? `last ${clock(new Date(lastTime).toISOString())}` : "";
  return (
    <header className="flex items-start justify-between gap-2 border-b border-line p-4 sm:p-5">
      <div className="min-w-0">
        <h2 id="calls-title" tabIndex={-1} className="text-lg font-normal text-ink focus:outline-none">
          Calls
        </h2>
        <p className="mt-0.5 text-sm text-muted">Newest first</p>
      </div>
      <span aria-live="polite" className="pt-1.5 text-xs whitespace-nowrap text-muted tabular-nums">
        {statusText}
      </span>
    </header>
  );
}

function CallsSummaryMetrics({ filtered, totalCount }: { filtered: TrafficEvent[]; totalCount: number }) {
  const overheads = filtered.map((e) => e.timing.overhead_ms);
  const p50 = percentile(overheads, 50);
  const p95 = percentile(overheads, 95);
  const masked = filtered.reduce((n, e) => n + totalMasked(e), 0);
  const problems = filtered.filter((e) => e.outcome !== "ok").length;
  const callsLabel = filtered.length === totalCount ? "Calls" : `Calls (of ${totalCount}, filtered)`;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:gap-x-8" aria-label="Summary of the calls shown">
      <Metric label={callsLabel} value={filtered.length} />
      <Metric label="Overhead p50, all shown" value={formatMsShort(p50)} />
      <Metric label="Overhead p95, all shown" value={formatMsShort(p95)} />
      <Metric label="Values masked" value={masked} />
      <Metric label="Blocked or failed" value={problems} />
    </dl>
  );
}

function normalizeLogsProps(props: LogsProps) {
  return {
    t: props.t,
    forceFixture: props.forceFixture ?? false,
    sendDemo: props.sendDemo ?? sendDemoTraffic,
    pageHost: props.pageHost ?? globalThis.location?.hostname ?? "",
    mockUpstream: props.mockUpstream ?? false,
    focus: props.focus ?? null,
    onOpenSession: props.onOpenSession,
    demoTraffic: props.demoTraffic ?? true,
  };
}

interface CallListSectionProps {
  t: TrafficHandle;
  filtered: TrafficEvent[];
  selectedId: string | undefined;
  onPick: (id: string) => void;
  mockUpstream: boolean;
  endpointSelected: boolean;
  demoTraffic: boolean;
  onClearFilters: () => void;
}

function CallListSection({ t, filtered, selectedId, onPick, mockUpstream, endpointSelected, demoTraffic, onClearFilters }: CallListSectionProps) {
  // Backend restarts noticed while these calls arrived: the divider renders above the
  // first call of each new run (LAB-1366). A filtered-out first call hides its divider too.
  const breaksById = useMemo(() => new Map(t.runBreaks.map((b) => [b.beforeId, b])), [t.runBreaks]);
  return (
    <section aria-labelledby="calls-title" className="flex min-w-0 flex-col rounded-xl border border-line bg-surface lg:sticky lg:top-4 lg:self-start">
      <CallListHeader paused={t.paused} events={t.events} />
      {filtered.length === 0 ? (
        <div className="p-4 sm:p-5">
          <EmptyCalls
            hasAny={t.events.length > 0}
            source={t.source}
            status={t.status}
            replayDone={t.replayDone}
            demoTraffic={demoTraffic}
            endpointSelected={endpointSelected}
            onClearFilters={onClearFilters}
          />
        </div>
      ) : (
        <ul aria-label="Calls through the gateway" className="relative max-h-[26rem] divide-y divide-line overflow-y-auto lg:max-h-[calc(100dvh-10rem)]" data-testid="call-list">
          {[...filtered].reverse().map((e) => (
            <Fragment key={e.id}>
              {breaksById.get(e.id) && (
                <li>
                  <RestartDivider at={breaksById.get(e.id)!.time} />
                </li>
              )}
              <li>
                <CallRow event={e} selected={selectedId === e.id} onSelect={() => onPick(e.id)} mockUpstream={mockUpstream} showEndpoint={!endpointSelected} />
              </li>
            </Fragment>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Logs(rawProps: LogsProps) {
  const { t, forceFixture, sendDemo, pageHost, mockUpstream, focus, onOpenSession, demoTraffic } = normalizeLogsProps(rawProps);
  const [filters, setFilters] = useState<Filters>({ mode: "all", type: "all", problems: false });
  const [selectedId, setSelectedId] = useState<string | null>(() => reopenAfterSwitch);
  const [cleared, setCleared] = useState(0);
  const detailRef = useRef<HTMLDivElement>(null);
  // No endpoint picked in the header: the server merges the project's endpoints (LAB-1492),
  // so each call names the endpoint it went through.
  const endpointSelected = useSelectedEndpoint() !== null;

  const filtered = useMemo(() => t.events.filter((e) => matchesLogFilters(e, filters)), [t.events, filters]);
  const modes = useMemo(() => modeOrder([...new Set(t.events.map((e) => e.mode ?? "unknown"))]), [t.events]);
  const types = useMemo(
    () => [...new Set(t.events.flatMap((e) => [...Object.keys(e.entities?.detected ?? {}), ...Object.keys(maskedCounts(e))]))].sort() as EntityType[],
    [t.events],
  );

  // Follow the latest call until one is picked; keep the pick while it's still in the list.
  const { selected, following } = resolveSelectedCall(filtered, selectedId);

  useReopenFocus(selected?.id);
  useExternalLogFocus(focus, selected?.id, (id) => {
    setSelectedId(id);
    setFilters({ mode: "all", type: "all", problems: false });
  });

  const pick = (id: string) => {
    setSelectedId(id);
    if (window.matchMedia?.("(max-width: 1023px)").matches) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

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

      <LogControlsBar
        t={t}
        demoTraffic={demoTraffic}
        sendDemo={sendDemo}
        cleared={cleared}
        onClear={() => {
          t.clear();
          setSelectedId(null);
          setCleared((n) => n + 1);
        }}
        modes={modes}
        types={types}
        filters={filters}
        onFilters={setFilters}
      />

      <CallsSummaryMetrics filtered={filtered} totalCount={t.events.length} />

      <div className="grid gap-6 lg:grid-cols-[minmax(17rem,21rem)_minmax(0,1fr)] xl:grid-cols-[minmax(19rem,25rem)_minmax(0,1fr)]">
        <CallListSection
          t={t}
          filtered={filtered}
          selectedId={selected?.id}
          onPick={pick}
          mockUpstream={mockUpstream}
          endpointSelected={endpointSelected}
          demoTraffic={demoTraffic}
          onClearFilters={() => {
            setFilters({ mode: "all", type: "all", problems: false });
            // The button unmounts with the empty state: put focus on the list it reveals (LAB-1712).
            document.getElementById("calls-title")?.focus();
          }}
        />

        <div ref={detailRef} className="@container min-w-0 scroll-mt-4 space-y-6">
          {selected ? (
            <CallDetail
              event={selected}
              following={following}
              source={t.source}
              pageHost={pageHost}
              onFollow={() => setSelectedId(null)}
              mockUpstream={mockUpstream}
              onOpenSession={t.source === "api" ? onOpenSession : undefined}
              onRememberCall={(id) => {
                reopenAfterSwitch = id;
              }}
              aggregated={!endpointSelected}
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

function fixtureReasonCopy(forced: boolean, apiStatus: TrafficStatus): string {
  if (forced) {
    return "The engine is set to Demo engine, so these are calls recorded from the demo stack, replayed in your browser. Switch the engine to Auto or Live API to follow the gateway.";
  }
  if (apiStatus.state === "disabled") return "The API's traffic log is off, so these are calls recorded from the demo stack, replayed in your browser.";
  if (apiStatus.state === "offline") return "The API isn't reachable, so these are calls recorded from the demo stack, replayed in your browser.";
  return "You picked the recorded demo: these are calls recorded from the demo stack, replayed in your browser. Your server's own log is one click away.";
}

function replayStatusCopy(replayDone: boolean, paused: boolean): string {
  if (replayDone) return "Replay finished: every recorded call was played once.";
  if (paused) return "Replay paused. Press Resume to continue.";
  return "Replaying the recorded calls once…";
}

interface FixtureBannerProps {
  apiStatus: TrafficStatus;
  forced: boolean;
  paused: boolean;
  onRetry: () => void;
  replayDone: boolean;
  onReplay: () => void;
}

function FixtureBanner({ apiStatus, forced, paused, onRetry, replayDone, onReplay }: FixtureBannerProps) {
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm sm:p-4 text-ink">
      <p className="min-w-0 flex-1">
        <strong className="font-medium text-warn">Recorded demo traffic.</strong> {fixtureReasonCopy(forced, apiStatus)} Recorded at level{" "}
        <code className="rounded bg-surface px-1 font-mono text-xs">masked</code>: they hold only what the model received.
      </p>
      {!forced && (
        <Button size="sm" onClick={onRetry}>
          Back to the live log
        </Button>
      )}
      <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 border-t border-warn/30 pt-2">
        <p className="min-w-0 flex-1 font-medium" data-testid="replay-state">
          {replayStatusCopy(replayDone, paused)}
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

function DeniedBanner({ reason, hosted }: { reason: "signed_out" | "forbidden"; hosted: boolean }) {
  if (reason !== "signed_out") {
    return (
      <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm sm:p-4 text-ink">
        <strong className="font-medium text-danger">This account can't read this traffic log.</strong> The API is up but answered 403. Check the selected project, or sign in with the account
        that owns it.
      </div>
    );
  }
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm sm:p-4 text-ink">
      {hosted ? (
        // Hosted: the console only opens signed in, so a 401 means the session ended (LAB-1519).
        <>
          <strong className="font-medium text-danger">Your session ended.</strong> Sign in again; this page reconnects by itself.
        </>
      ) : (
        <>
          <strong className="font-medium text-danger">You're signed out.</strong> The API is up but answered 401. Sign in again; this page reconnects by itself.
        </>
      )}
    </div>
  );
}

function LiveStatusBanner({ status, paused, hosted }: { status: Extract<TrafficStatus, { state: "live" | "connecting" }>; paused: boolean; hosted: boolean }) {
  if (status.state === "connecting") {
    return (
      <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-medium">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-faint motion-safe:animate-pulse" /> Connecting…
        </span>
      </div>
    );
  }
  const retentionCopy = hosted
    ? "Only what was sent to the model is logged: placeholders, never values."
    : status.level === "full"
      ? "Originals are kept in memory on this machine only."
      : "Only what left the machine is logged: placeholders, never values.";
  return (
    <div role="status" className="flex flex-wrap items-center gap-2 text-sm text-muted">
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
      <span className="text-xs">{retentionCopy}</span>
    </div>
  );
}

interface SourceBannerProps {
  source: TrafficSource;
  status: TrafficStatus;
  apiStatus: TrafficStatus;
  forced: boolean;
  paused: boolean;
  onFixture: () => void;
  onRetry: () => void;
  replayDone: boolean;
  onReplay: () => void;
}

function SourceBanner({ source, status, apiStatus, forced, paused, onFixture, onRetry, replayDone, onReplay }: SourceBannerProps) {
  const hosted = useHostedSession() !== null;
  const code = (s: string) => <code className="rounded bg-surface px-1 font-mono text-xs">{s}</code>;
  if (source === "fixture") {
    return <FixtureBanner apiStatus={apiStatus} forced={forced} paused={paused} onRetry={onRetry} replayDone={replayDone} onReplay={onReplay} />;
  }
  if (status.state === "disabled") {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-line bg-surface p-3 text-sm sm:p-4 text-ink">
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
      <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm sm:p-4 text-ink">
        <strong className="font-medium text-danger">Lost the connection to the API.</strong> Retrying every few seconds; the calls already shown stay. ({status.message})
      </div>
    );
  }
  if (status.state === "limited") {
    const wait = status.retryAfterMs ? ` in about ${Math.ceil(status.retryAfterMs / 1000)} s` : " shortly";
    return (
      <div role="status" className="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm sm:p-4 text-ink">
        <strong className="font-medium text-warn">Too many requests just now.</strong> The API is up but asked this page to slow down; it retries{wait}. The calls already shown stay.
      </div>
    );
  }
  if (status.state === "denied") {
    return <DeniedBanner reason={status.reason} hosted={hosted} />;
  }
  return <LiveStatusBanner status={status} paused={paused} hosted={hosted} />;
}

function LiveEmptyCallsHint({ demoTraffic, endpointSelected }: { demoTraffic: boolean; endpointSelected: boolean }) {
  if (demoTraffic) {
    return (
      <p className="mt-1">
        Press <strong className="text-ink">Send demo traffic</strong>, run <code className="font-mono text-xs">make demo-traffic</code>, or point an OpenAI client at{" "}
        <code className="font-mono text-xs">/v1</code> of the gateway.
      </p>
    );
  }
  return (
    <p className="mt-1">
      {endpointSelected
        ? "Only calls through the endpoint picked in the header show here. Pick All endpoints in the header menu to see the whole project."
        : "Calls through any of this project's endpoints show here, each tagged with its endpoint. Connect a client to one (Connect), or mask a text in the Playground."}
    </p>
  );
}

interface EmptyCallsProps {
  hasAny: boolean;
  source: TrafficSource;
  status: TrafficStatus;
  replayDone: boolean;
  demoTraffic: boolean;
  endpointSelected?: boolean;
  onClearFilters: () => void;
}

function EmptyCalls({ hasAny, source, status, replayDone, demoTraffic, endpointSelected = false, onClearFilters }: EmptyCallsProps) {
  if (hasAny)
    return (
      <div className="space-y-3 py-6 text-center">
        <p className="text-sm text-muted">No call matches these filters.</p>
        <Button size="sm" onClick={onClearFilters}>
          Clear filters
        </Button>
      </div>
    );
  if (source === "fixture" && replayDone) {
    return (
      <p className="py-6 text-center text-sm text-muted">
        The recorded replay has finished. Press <strong className="text-ink">Replay again</strong> to watch it from the start.
      </p>
    );
  }
  if (status.state === "disabled") return <p className="py-6 text-center text-sm text-muted">Nothing to show while the traffic log is off.</p>;
  const liveApi = source === "api" && status.state === "live";
  return (
    <div className="py-6 text-center text-sm text-muted">
      <p className="font-medium text-ink">{status.state === "connecting" ? "Connecting…" : "Waiting for the first call"}</p>
      {liveApi && <LiveEmptyCallsHint demoTraffic={demoTraffic} endpointSelected={endpointSelected} />}
    </div>
  );
}

const LABELLED_NOTE = LABELLED_SCENARIOS.length
  ? `; ${LABELLED_SCENARIOS.length} labeled “${LABELLED_SCENARIOS[0]!.label}”: in rules-only mode its name is an expected miss`
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
  const refusedNote = p?.refused ? `; ${p.refused} refused (an image without SAM is refused: fail closed)` : "";
  return (
    <>
      <Button variant="primary" onClick={() => void run()} busy={state.running}>
        <SendIcon /> {state.running ? "Sending…" : "Send demo traffic"}
      </Button>
      <span aria-live="polite" className="text-xs text-muted tabular-nums">
        {state.running && p ? `${p.done} of ${p.total} sent` : null}
        {!state.running && p ? `Sent ${p.done} fictional calls${refusedNote}${LABELLED_NOTE}.` : null}
        {state.error ? <span className="text-danger">Could not send: {state.error}.</span> : null}
      </span>
    </>
  );
}

// --- List ---------------------------------------------------------------------------------

/** A backend restart between two shown runs (LAB-1366): numbering restarts at 1 and
session refs change, because sessions are keyed per server process. */
function RestartDivider({ at }: { at: string }) {
  return (
    <div role="separator" aria-label="Server restarted" className="bg-warn-soft px-4 py-2 text-center sm:px-5">
      <p className="text-xs font-medium text-warn">
        Server restarted{at ? ` · ${clock(new Date(at).toISOString())}` : ""} — calls below are from the new run
      </p>
      <p className="mt-0.5 text-2xs text-muted">Numbering restarts at 1, and session refs changed: sessions are keyed per server process.</p>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="rounded px-1.5 py-0.5 text-2xs font-medium text-muted ring-1 ring-line ring-inset">{children}</span>;
}

function rowModelLabel(e: TrafficEvent, mockUpstream: boolean): string {
  if (e.outcome === "blocked" || e.outcome === "refused") return "not forwarded";
  if (mockUpstream) return "mock upstream";
  return e.model ?? "";
}

function hasRequestTools(e: TrafficEvent): boolean {
  const req = e.request;
  return requestTools(req ? (req.masked ?? req.original) : undefined).length > 0;
}

function hasImageEntities(e: TrafficEvent): boolean {
  return Boolean(e.entities?.images?.count);
}

function callRowBadges(e: TrafficEvent): string[] {
  const tags: string[] = [];
  if (e.mode) tags.push(e.mode);
  if (e.stream) tags.push("stream");
  if (hasRequestTools(e)) tags.push("tools");
  if (hasImageEntities(e)) tags.push("image");
  return tags;
}

function CallRowTags({ event: e, showEndpoint }: { event: TrafficEvent; showEndpoint: boolean }) {
  const labelled = labelledScenarioFor(e);
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-mono whitespace-nowrap text-muted tabular-nums">{clock(e.time)}</span>
      {showEndpoint && e.endpoint && (
        <span className="max-w-[10rem] truncate rounded bg-surface-2 px-1.5 py-0.5 text-2xs font-medium text-ink ring-1 ring-line-strong ring-inset" title={`Endpoint: ${e.endpoint.name}`}>
          <span className="sr-only">Endpoint </span>
          {e.endpoint.name}
        </span>
      )}
      {callRowBadges(e).map((tag) => (
        <Tag key={tag}>{tag}</Tag>
      ))}
      {labelled && <LabelTag match={labelled} />}
      <OutcomeBadge outcome={e.outcome} />
    </span>
  );
}

interface CallRowProps {
  event: TrafficEvent;
  selected: boolean;
  onSelect: () => void;
  mockUpstream: boolean;
  showEndpoint?: boolean;
}

function CallRow({ event: e, selected, onSelect, mockUpstream, showEndpoint = false }: CallRowProps) {
  const labelled = labelledScenarioFor(e);
  const onlyExpectedMiss = Boolean(labelled && labelled.missed.length > 0 && totalMasked(e) === 0);
  const tone = selected ? "bg-surface-2 shadow-[inset_3px_0_0_var(--ink)]" : "hover:bg-surface-2";
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors sm:px-5 ${tone}`}
    >
      <span className="flex w-full items-start gap-2 text-xs">
        <CallRowTags event={e} showEndpoint={showEndpoint} />
        <span className="shrink-0 font-medium whitespace-nowrap text-ink tabular-nums" title="PII Guard overhead">
          +{formatMsShort(e.timing.overhead_ms)}
        </span>
      </span>
      <span className="flex w-full items-start justify-between gap-2">
        {onlyExpectedMiss ? (
          <span className="text-xs text-leak">{labelled!.missed.length} name reached the model: expected, needs NER</span>
        ) : (
          <EntityChips counts={maskedCounts(e)} />
        )}
        <RowModel label={rowModelLabel(e, mockUpstream)} />
      </span>
    </button>
  );
}

/** The row's model: provider ids (`accounts/fireworks/models/…`) show their last segment, truncated. */
function RowModel({ label }: { label: string }) {
  const short = label.includes("/") ? label.slice(label.lastIndexOf("/") + 1) : label;
  return (
    <span className="min-w-0 max-w-[45%] truncate text-right text-xs text-faint" title={label || undefined}>
      {short}
    </span>
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
    <svg aria-hidden="true" viewBox="0 0 16 16" className={icon} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      <path d="M2.5 8 13.5 2.5 11 13.5 8 9.5 2.5 8Z" />
      <path d="M8 9.5 13.5 2.5" />
    </svg>
  );
}
