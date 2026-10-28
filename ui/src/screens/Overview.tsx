import { useMemo, type ReactNode } from "react";
import { sendDemoTraffic } from "../api/demoTraffic";
import type { ServerStatus } from "../api/status";
import type { TrafficEvent } from "../api/traffic";
import type { EntityType } from "../api/types";
import { NerHint } from "../components/NerHint";
import { Button } from "../components/ui";
import { useNow } from "../hooks/useNow";
import type { ServerStatusState } from "../hooks/useServerStatus";
import type { TrafficHandle } from "../hooks/useTraffic";
import { metaFor } from "../lib/entities";
import { OWN_STAGES, STAGE_HINT, STAGE_LABEL, clock, detectorName, formatMsShort, maskedCounts, modeNote, percentile, totalMasked } from "../lib/traffic";
import { ChartCard, DemoButton } from "./Traffic";
import { EntitiesChart, ModeChart, OverheadChart, StageChart } from "./TrafficCharts";

export interface OverviewProps {
  t: TrafficHandle;
  status: ServerStatusState;
  /** The header's engine is set to Demo engine: the recorded traffic plays, not the API's. */
  forced: boolean;
  /** Open one call on the Logs screen. */
  onOpenCall: (id: string) => void;
  sendDemo?: typeof sendDemoTraffic;
}

const BLOCKED = new Set(["blocked", "refused"]);

/** Counters from the events this page holds: every number here is a count of real calls. */
function summarize(events: readonly TrafficEvent[]) {
  const types = new Map<EntityType, number>();
  for (const e of events) for (const [k, n] of Object.entries(maskedCounts(e)) as [EntityType, number][]) if (n > 0) types.set(k, (types.get(k) ?? 0) + n);
  const stages = OWN_STAGES.map((k) => {
    const values = events.map((e) => e.timing.stages_ms[k] ?? 0).filter((v) => v > 0);
    return { key: k, calls: values.length, p50: percentile(values, 50), p95: percentile(values, 95) };
  }).filter((s) => s.calls > 0);
  const overhead = events.map((e) => e.timing.overhead_ms);
  const forwarded = events.filter((e) => e.upstream?.status != null);
  return {
    calls: events.length,
    masked: events.reduce((n, e) => n + totalMasked(e), 0),
    blocked: events.filter((e) => BLOCKED.has(e.outcome)).length,
    failed: events.filter((e) => e.outcome !== "ok" && !BLOCKED.has(e.outcome)).length,
    upstreamErrors: events.filter((e) => e.outcome === "upstream_error").length,
    types: [...types.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    stages,
    overhead: { p50: percentile(overhead, 50), p95: percentile(overhead, 95) },
    lastForwarded: forwarded[forwarded.length - 1] ?? null,
    since: events[0]?.time ?? null,
  };
}

export function Overview({ t, status, forced, onOpenCall, sendDemo = sendDemoTraffic }: OverviewProps) {
  const s = useMemo(() => summarize(t.events), [t.events]);
  const now = useNow();
  const lastTime = t.events.length ? Date.parse(t.events[t.events.length - 1]!.time) : 0;
  const server = status.state === "ok" ? status.status : null;
  const recorded = t.source === "fixture";
  const empty = t.events.length === 0;

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-medium text-balance text-ink">Overview</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          pii-guard masks personal data before a request reaches the model and puts it back in the answer. This page counts what it protected: every call through the
          gateway, from its traffic log. Values never appear here, only their types and counts.
        </p>
      </div>

      <ScopeNote t={t} forced={forced} since={s.since} />

      {empty && !recorded ? (
        <EmptyOverview t={t} server={server} sendDemo={sendDemo} />
      ) : (
        <>
          <dl aria-label={recorded ? "Counters of the recorded demo traffic" : "Counters"} className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
            <Counter label="Requests" value={s.calls} note={`${s.calls === 1 ? "call" : "calls"} through the gateway`} />
            <Counter label="Values masked" value={s.masked} note="replaced by placeholders before the model saw them" />
            <Counter label="Requests blocked" value={s.blocked} note="failed closed: nothing was sent" tone={s.blocked ? "blocked" : undefined} />
            <Counter label="pii-guard overhead" value={formatMsShort(s.overhead.p50)} note={`p50 · p95 ${formatMsShort(s.overhead.p95)}`} />
          </dl>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Top entity types" note="Values masked, by type, across the calls counted above.">
              <TopTypes types={s.types} />
            </Panel>
            <Panel title="Latency per stage" note="pii-guard's own stages; the model's time is not included. p50 and p95 over the calls that ran the stage.">
              <StageTable stages={s.stages} />
            </Panel>
          </div>
        </>
      )}

      {/* Your server's setup, never mixed into the recorded demo's numbers. */}
      {!recorded && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="Upstream" note="Where the gateway forwards masked requests.">
            <Upstream server={server} status={status} last={s.lastForwarded} errors={s.upstreamErrors} />
          </Panel>
          <Panel title="Mode and detectors" note="What runs on each gateway call.">
            <Detectors server={server} status={status} />
          </Panel>
        </div>
      )}

      {!empty && (
        <section aria-labelledby="latency-title" className="space-y-4">
          <div>
            <h2 id="latency-title" className="text-lg font-normal text-ink">
              Latency, live
            </h2>
            <p className="text-sm text-muted">From the timing block of each call: the overhead is the call's total time minus the time spent waiting on the model.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <ChartCard id="chart-overhead" title="Overhead per call" note="What pii-guard added to each call, with the rolling p50 and p95.">
              <OverheadChart events={t.events} />
            </ChartCard>
            <ChartCard id="chart-mode" title="Overhead by mode" note={modeNote(t.events)}>
              <ModeChart events={t.events} />
            </ChartCard>
            <ChartCard
              id="chart-stages"
              title="Where the time goes"
              note="pii-guard's own stages, last 30 calls. Forward is serialising the masked body and opening the HTTP connection to the model. Pick a column to open that call in Logs."
            >
              <StageChart events={t.events} onSelect={onOpenCall} />
            </ChartCard>
            <ChartCard id="chart-entities" title="Values masked per minute" note="Text values and image regions by kind, last 10 minutes. Hover or tap a column for the exact types.">
              <EntitiesChart events={t.events} now={Math.max(now, lastTime)} />
            </ChartCard>
          </div>
        </section>
      )}
    </div>
  );
}

const code = (s: string) => <code className="rounded-sm bg-surface-2 px-1 font-mono text-xs">{s}</code>;

/** What the numbers count: the server's log, the recorded demo, or nothing yet. */
function ScopeNote({ t, forced, since }: { t: TrafficHandle; forced: boolean; since: string | null }) {
  if (t.source === "fixture") {
    return (
      <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
        <p className="min-w-0 flex-1">
          <strong className="font-medium text-warn">Recorded demo traffic, not your server.</strong>{" "}
          {forced
            ? "The engine is set to Demo engine, so these numbers count calls recorded from the demo stack, replayed in your browser."
            : t.apiStatus.state === "disabled"
              ? "The server's traffic log is off, so these numbers count calls recorded from the demo stack, replayed in your browser."
              : "These numbers count calls recorded from the demo stack, replayed in your browser."}
        </p>
        {!forced && (
          <Button className="h-8" onClick={t.retryApi}>
            Back to the live API
          </Button>
        )}
      </div>
    );
  }
  if (t.status.state === "live" && t.events.length) {
    return (
      <p className="text-xs text-muted">
        Counting {t.events.length} {t.events.length === 1 ? "call" : "calls"}
        {since ? ` since ${clock(since)}` : ""}: the server's traffic log (it keeps the last {t.status.size} in memory) plus every new call while this page is open. Log level{" "}
        {code(t.status.level)}.
      </p>
    );
  }
  return null;
}

function EmptyOverview({ t, server, sendDemo }: { t: TrafficHandle; server: ServerStatus | null; sendDemo: typeof sendDemoTraffic }) {
  const status = t.status;
  const gateway = server?.gateway.url ?? "/v1";
  const title =
    status.state === "connecting"
      ? "Connecting to the gateway's traffic log…"
      : status.state === "disabled"
        ? "The traffic log is off on this server, so there is nothing to count."
        : status.state === "offline"
          ? "The pii-guard API isn't reachable."
          : "Nothing has gone through the gateway yet.";
  return (
    <section aria-labelledby="empty-title" className="rounded-xl border border-line bg-surface px-5 py-8 sm:px-8">
      <h2 id="empty-title" className="text-lg font-normal text-ink">
        {title}
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        {status.state === "disabled" ? (
          status.reason === "off" ? (
            <>
              Restart with {code("PII_GUARD_TRAFFIC_LOG=masked")} ({code("pii-guard up")} and {code("make demo")} turn it on). The counters here are read from that log; nothing is
              estimated.
            </>
          ) : (
            <>{status.message}.</>
          )
        ) : (
          <>
            The counters fill in as calls arrive. Point a client at the gateway ({code(gateway)}), or send a few fictional calls through it to see what happens to each one.
          </>
        )}
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <a href="#connect" className="inline-flex h-9 items-center justify-center rounded-lg bg-primary px-3 text-sm text-on-primary transition-colors hover:bg-primary-hover">
          Connect a client
        </a>
        <a href="#playground/text" className="inline-flex h-9 items-center justify-center rounded-lg border border-line px-3.5 text-sm font-medium text-ink transition-colors hover:border-line-strong">
          Try it in the Playground
        </a>
        {status.state === "live" && <DemoButton send={sendDemo} />}
        <Button variant="ghost" onClick={t.showFixture}>
          Watch a recorded demo
        </Button>
      </div>
      <p className="mt-3 text-xs text-faint">The recorded demo replays calls captured from the demo stack, in your browser, and is labelled as recorded wherever it shows.</p>
    </section>
  );
}

function Counter({ label, value, note, tone }: { label: string; value: number | string; note: string; tone?: "blocked" }) {
  return (
    <div className="flex flex-col-reverse justify-end bg-surface px-4 py-4 sm:px-5">
      <dt className="mt-1 text-xs text-muted">
        <span className="block font-medium text-ink">{label}</span>
        {note}
      </dt>
      <dd className={["font-mono text-2xl leading-none font-medium tabular-nums", tone === "blocked" ? "text-blocked" : "text-ink"].join(" ")}>{value}</dd>
    </div>
  );
}

function Panel({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  const id = `panel-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
      <h2 id={id} className="text-lg font-normal text-ink">
        {title}
      </h2>
      <p className="mt-0.5 mb-4 text-sm text-muted">{note}</p>
      {children}
    </section>
  );
}

function TopTypes({ types }: { types: [EntityType, number][] }) {
  if (!types.length) return <p className="text-sm text-muted">No values masked yet.</p>;
  const shown = types.slice(0, 8);
  const max = shown[0]![1];
  return (
    <ol className="space-y-2">
      {shown.map(([type, n]) => (
        <li key={type} className="grid grid-cols-[minmax(7rem,10rem)_minmax(0,1fr)_3rem] items-center gap-3 text-sm">
          <span className="truncate text-ink" title={type}>
            {metaFor(type).label}
          </span>
          <span aria-hidden="true" className="h-2 rounded-full bg-surface-2">
            <span className="block h-2 rounded-full bg-masked" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="text-right font-mono text-xs tabular-nums text-ink">{n}</span>
        </li>
      ))}
      {types.length > shown.length && <li className="text-xs text-muted">and {types.length - shown.length} more types</li>}
    </ol>
  );
}

function StageTable({ stages }: { stages: ReturnType<typeof summarize>["stages"] }) {
  if (!stages.length) return <p className="text-sm text-muted">No timing recorded yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-line text-left text-xs text-muted">
          <th scope="col" className="py-1.5 pr-2 font-medium">
            Stage
          </th>
          <th scope="col" className="px-2 py-1.5 text-right font-medium">
            p50
          </th>
          <th scope="col" className="px-2 py-1.5 text-right font-medium">
            p95
          </th>
          <th scope="col" className="py-1.5 pl-2 text-right font-medium">
            Calls
          </th>
        </tr>
      </thead>
      <tbody>
        {stages.map((st) => (
          <tr key={st.key} className="border-b border-line last:border-0">
            <th scope="row" className="py-1.5 pr-2 text-left font-normal text-ink" title={STAGE_HINT[st.key]}>
              {STAGE_LABEL[st.key]}
            </th>
            <td className="px-2 py-1.5 text-right font-mono text-xs tabular-nums">{formatMsShort(st.p50)}</td>
            <td className="px-2 py-1.5 text-right font-mono text-xs tabular-nums">{formatMsShort(st.p95)}</td>
            <td className="py-1.5 pl-2 text-right font-mono text-xs tabular-nums text-muted">{st.calls}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Unknown({ status }: { status: ServerStatusState }) {
  return (
    <p className="text-sm text-muted">
      {status.state === "loading"
        ? "Asking the server…"
        : status.state === "missing"
          ? "This pii-guard server doesn't report its configuration (it predates /v1/status)."
          : "Unknown: the pii-guard API isn't reachable, so the page can't ask it."}
    </p>
  );
}

function Upstream({ server, status, last, errors }: { server: ServerStatus | null; status: ServerStatusState; last: TrafficEvent | null; errors: number }) {
  if (!server) return <Unknown status={status} />;
  const up = server.upstream;
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      <dt className="text-muted">Model</dt>
      <dd className="min-w-0 text-ink">
        {up.mock ? (
          <>
            <span className="font-medium">Offline mock model</span>: it echoes the masked text it receives, so no model provider is involved.
          </>
        ) : up.origin ? (
          <code className="font-mono text-xs break-all">{up.origin}</code>
        ) : (
          <>Not configured. Chat calls fail until {code("PII_GUARD_UPSTREAM_BASE_URL")} is set.</>
        )}
      </dd>
      <dt className="text-muted">Last call</dt>
      <dd className="text-ink">
        {last ? (
          <>
            {last.upstream?.status ? `HTTP ${last.upstream.status}` : "no answer"} at {clock(last.time)}
            {errors ? <span className="text-danger"> · {errors} upstream {errors === 1 ? "error" : "errors"} in the calls counted</span> : null}
          </>
        ) : (
          <span className="text-muted">No call forwarded yet, so its reachability isn't known.</span>
        )}
      </dd>
    </dl>
  );
}

function Detectors({ server, status }: { server: ServerStatus | null; status: ServerStatusState }) {
  if (!server) return <Unknown status={status} />;
  const { fast, audit } = server.gateway.modes;
  return (
    <div className="space-y-3 text-sm">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2">
        <dt className="text-muted">Default mode</dt>
        <dd className="text-ink">
          <span className="font-medium capitalize">{server.gateway.default_mode}</span>
          <span className="text-muted"> · clients can pick per request with {code("X-PII-Guard-Mode")}</span>
        </dd>
        <dt className="text-muted">Fast</dt>
        <dd className="text-ink">{fast.detectors.map(detectorName).join(" + ") || "none"}</dd>
        <dt className="text-muted">Audit</dt>
        <dd className="text-ink">
          {audit.available ? (
            <>Fast + the LLM detector{audit.model ? ` (${audit.model.split("/").pop()})` : ""}: sends the text to that endpoint, for spot checks.</>
          ) : (
            <span className="text-muted [overflow-wrap:anywhere]">Unavailable: requests get 503 {code("detection_unavailable")}. {audit.reason}</span>
          )}
        </dd>
      </dl>
      {!server.ner.available && (
        <p role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-ink">
          <span className="font-medium text-warn">Rules only: free-text names are not masked.</span> Names need <NerHint />.
        </p>
      )}
    </div>
  );
}
