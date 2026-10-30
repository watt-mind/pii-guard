import { useState } from "react";
import type { TrafficEvent } from "../api/traffic";
import type { EntityType } from "../api/types";
import { ENTITY_GROUPS, groupOf, metaFor } from "../lib/entities";
import {
  OWN_STAGES,
  STAGE_HINT,
  STAGE_LABEL,
  entitiesPerMinute,
  formatMsShort,
  overheadByMode,
  percentile,
  rollingOverhead,
  waterfall,
  type OwnStage,
} from "../lib/traffic";
import { useWidth } from "../hooks/useWidth";
import { clockMinutes, clockTime } from "../lib/time";
import { Metric } from "../components/ui";
import { ChartEmpty } from "./BenchmarksCharts";

/* Charts for the Live traffic screen, following the Benchmarks conventions: drawn at the
 * container's real width (text stays 12 px+ on a phone), a text alternative for every
 * chart (aria-label summary plus the request list, which holds every number), colour never
 * the only cue (every stage is labelled in the waterfall and the legend). */

const FONT = 12;

const STAGE_COLOR: Record<OwnStage | "upstream" | "other", string> = {
  parse: "var(--stage-parse)",
  detect: "var(--stage-detect)",
  image: "var(--stage-image)",
  mask: "var(--stage-mask)",
  forward: "var(--stage-forward)",
  unmask: "var(--stage-unmask)",
  response: "var(--stage-response)",
  upstream: "var(--stage-upstream)",
  other: "var(--stage-other)",
};

// The waterfall labels every row, so pii-guard's own stages share one neutral bar and only the
// model's time (hatched) stands apart: no hue here that could be read as masked or restored.
const OWN_BAR = "color-mix(in oklab, var(--ink) 58%, var(--surface))";

function niceCeil(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

// --- Waterfall ----------------------------------------------------------------------------

export function TimingWaterfall({ event }: { event: TrafficEvent }) {
  const w = waterfall(event.timing);
  if (!w.rows.length) return <ChartEmpty>No timing was recorded for this call.</ChartEmpty>;
  const pct = (ms: number) => `${(ms / w.span) * 100}%`;
  // Its own size container: the figures and rows follow the card's width, not the viewport's.
  return (
    <div className="@container">
      <dl className="mb-4 grid grid-cols-2 gap-x-6 gap-y-3 @xl:grid-cols-4">
        <Figure label="PII Guard added" value={formatMsShort(w.overhead)} strong testId="wf-overhead" />
        <Figure label="Model (upstream)" value={w.upstream > 0 ? formatMsShort(w.upstream) : "not called"} testId="wf-upstream" />
        <Figure label="Total" value={formatMsShort(w.total)} testId="wf-total" />
        {w.addedTtft !== null ? (
          <Figure label="Added to first token" value={formatMsShort(w.addedTtft)} testId="wf-ttft" />
        ) : (
          <Figure label="Streamed" value="no" />
        )}
      </dl>
      <ol aria-label="Timing waterfall, stages in pipeline order" className="space-y-1.5" data-testid="waterfall">
        {w.rows.map((r) => (
          <li key={r.key} className="grid grid-cols-[5.5rem_1fr_4.25rem] items-center gap-2 text-xs @md:grid-cols-[8.5rem_1fr_5rem]">
            <span className="flex min-w-0 items-center gap-1.5 text-ink">
              <span className="truncate" title={STAGE_HINT[r.key]}>
                {r.label}
              </span>
            </span>
            <span aria-hidden="true" className="relative h-3.5 rounded-sm bg-surface-2">
              <span
                className="absolute inset-y-0.5 min-w-[3px] rounded-sm"
                title={`${r.label}: ${formatMsShort(r.ms)}, from ${formatMsShort(r.start)}`}
                style={{
                  left: pct(r.start),
                  width: pct(r.ms),
                  background:
                    r.kind === "upstream"
                      ? `repeating-linear-gradient(135deg, color-mix(in srgb, var(--ink) 22%, transparent) 0 3px, transparent 3px 6px), ${STAGE_COLOR.upstream}`
                      : r.kind === "other"
                        ? `repeating-linear-gradient(45deg, ${STAGE_COLOR.other} 0 2px, transparent 2px 5px)`
                        : OWN_BAR,
                }}
              />
              {r.kind === "upstream" && r.ttfbMs ? (
                <span
                  className="absolute inset-y-0 w-0.5 bg-ink/70"
                  style={{ left: pct(r.start + Math.min(r.ttfbMs, r.ms)) }}
                  title={`Response headers after ${formatMsShort(r.ttfbMs)}`}
                />
              ) : null}
            </span>
            <span className="text-right tabular-nums text-muted" data-stage={r.key} data-ms={r.ms}>
              {formatMsShort(r.ms)}
              <span className="sr-only">
                {" "}
                {r.kind === "upstream" ? "waiting on the model" : r.kind === "other" ? "not in any stage" : "PII Guard"}
                {r.ttfbMs ? `, headers after ${formatMsShort(r.ttfbMs)}` : ""}
              </span>
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-muted">
        <span className="tabular-nums">
          {formatMsShort(w.total)} total = {formatMsShort(w.upstream)} model + {formatMsShort(w.overhead)} PII Guard ({formatMsShort(w.own)} in stages
          {w.other > 0 ? ` + ${formatMsShort(w.other)} other` : ""}).
        </span>{" "}
        {w.rows.find((r) => r.key === "forward" && r.ms >= w.own / 2)
          ? "Forward (most of PII Guard's time here) is serializing the masked body and opening the HTTP connection to the model. "
          : ""}
        {event.stream
          ? `Streamed: unmasking runs between upstream reads and is shown summed after it${w.ttft !== null ? `; first token to the client after ${formatMsShort(w.ttft)}` : ""}.`
          : w.upstream > 0
            ? "The tick on the upstream bar is when the model's response headers arrived."
            : "The model was never called."}
      </p>
    </div>
  );
}

function Figure({ label, value, strong, testId }: { label: string; value: string; strong?: boolean; testId?: string }) {
  return (
    <Metric
      label={label}
      value={
        <span data-testid={testId} className={["whitespace-nowrap", strong ? "text-guard" : ""].join(" ")}>
          {value}
        </span>
      }
    />
  );
}

// --- Overhead over time -------------------------------------------------------------------

export function OverheadChart({ events }: { events: TrafficEvent[] }) {
  const [ref, width] = useWidth(560);
  const [hover, setHover] = useState<number | null>(null);
  const pts = rollingOverhead(events).slice(-60);
  if (pts.length < 2) return <ChartEmpty>The chart starts with the second call.</ChartEmpty>;
  const height = 200;
  const m = { l: 44, r: 40, t: 10, b: 24 };
  // Rolling lines start once a few calls are in (one cold-start call shouldn't set them), and
  // the axis stops at about twice the typical call: slower outliers are drawn as a mark at
  // the top with their value, so a warm-up call can't flatten everything else.
  const WARMUP = Math.min(5, pts.length - 1);
  const values = pts.map((p) => p.overhead);
  const typical = percentile(values, 90) ?? 0;
  const lines = pts.slice(WARMUP);
  const ymax = niceCeil(Math.max(typical * 2, ...lines.map((p) => p.p50)) * 1.05);
  const clip = (v: number) => Math.min(v, ymax);
  const sx = (i: number) => m.l + (i / (pts.length - 1)) * (width - m.l - m.r);
  const sy = (v: number) => height - m.b - (v / ymax) * (height - m.t - m.b);
  const line = (key: "p50" | "p95") =>
    lines.map((p, i) => `${i ? "L" : "M"}${sx(p.index - pts[0]!.index).toFixed(1)},${sy(clip(p[key])).toFixed(1)}`).join("");
  const outliers = pts.filter((p) => p.overhead > ymax);
  // One label for the slowest outlier only, so several don't collide on a phone.
  const top = outliers.reduce<(typeof pts)[number] | null>((a, p) => (!a || p.overhead > a.overhead ? p : a), null);
  const ticks = [0, ymax / 2, ymax];
  const last = pts[pts.length - 1]!;
  const h = hover !== null ? pts[hover] : null;
  const pick = (clientX: number, rect: DOMRect) => {
    const i = Math.round(((clientX - rect.left - m.l) / (width - m.l - m.r)) * (pts.length - 1));
    setHover(Math.max(0, Math.min(pts.length - 1, i)));
  };
  return (
    <div ref={ref} className="relative w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`PII Guard overhead per call, last ${pts.length} calls: now p50 ${formatMsShort(last.p50)}, p95 ${formatMsShort(last.p95)} over the last 20 calls.`}
        className="block touch-none overflow-visible font-sans"
        onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} stroke="var(--line)" />
            <text x={m.l - 6} y={sy(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)" className="tabular-nums">
              {t === 0 ? "0" : `${+t.toPrecision(3)} ms`}
            </text>
          </g>
        ))}
        <text x={m.l} y={height - 6} fontSize={FONT} fill="var(--faint)">
          older
        </text>
        <text x={width - m.r} y={height - 6} fontSize={FONT} fill="var(--faint)" textAnchor="end">
          latest call
        </text>
        {pts.map((p, i) =>
          p.overhead > ymax ? (
            <g key={p.id}>
              <path d={`M${sx(i)},${m.t - 2}l4,7h-8z`} fill="var(--ink)">
                <title>{formatMsShort(p.overhead)}</title>
              </path>
            </g>
          ) : (
            <circle key={p.id} cx={sx(i)} cy={sy(p.overhead)} r={2.5} fill="var(--faint)" opacity={0.7} />
          ),
        )}
        <path d={line("p95")} fill="none" stroke="var(--stage-detect)" strokeWidth={2} strokeLinejoin="round" strokeDasharray={lines.some((p) => p.p95 > ymax) ? "5 3" : undefined} />
        <path d={line("p50")} fill="none" stroke="var(--stage-parse)" strokeWidth={2} strokeLinejoin="round" />
        <text x={sx(pts.length - 1) + 6} y={sy(clip(last.p95)) + 4} fontSize={FONT} fill="var(--ink)">
          p95
        </text>
        <text x={sx(pts.length - 1) + 6} y={sy(clip(last.p50)) + (Math.abs(sy(clip(last.p50)) - sy(clip(last.p95))) < 14 ? 16 : 4)} fontSize={FONT} fill="var(--ink)">
          p50
        </text>
        {h && hover !== null && (
          <g pointerEvents="none">
            <line x1={sx(hover)} x2={sx(hover)} y1={m.t} y2={height - m.b} stroke="var(--line-strong)" />
            <circle cx={sx(hover)} cy={sy(clip(h.overhead))} r={4} fill="var(--ink)" stroke="var(--surface)" strokeWidth={2} />
          </g>
        )}
      </svg>
      {h && hover !== null && (
        <div
          role="presentation"
          className="pointer-events-none absolute top-0 z-10 rounded-lg border border-field bg-surface px-2.5 py-1.5 text-xs"
          style={{ left: Math.min(Math.max(sx(hover) - 70, 0), width - 150) }}
        >
          <p className="font-medium text-ink tabular-nums">This call {formatMsShort(h.overhead)}</p>
          <p className="text-muted tabular-nums">
            p50 {formatMsShort(h.p50)} · p95 {formatMsShort(h.p95)}
          </p>
        </div>
      )}
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <LegendSwatch color="var(--faint)" dot label="one call" />
        <LegendSwatch color="var(--stage-parse)" label="p50, last 20 calls" />
        <LegendSwatch color="var(--stage-detect)" label="p95, last 20 calls" />
        {top && <li>▲ above the scale: {outliers.length === 1 ? formatMsShort(top.overhead) : `${outliers.length} calls, slowest ${formatMsShort(top.overhead)}`}{lines.some((p) => p.p95 > ymax) ? "; dashed p95: capped at the scale" : ""}</li>}
      </ul>
    </div>
  );
}

function LegendSwatch({ color, label, dot }: { color: string; label: string; dot?: boolean }) {
  return (
    <li className="flex items-center gap-1.5">
      <span aria-hidden="true" className={dot ? "size-2 rounded-full" : "h-0.5 w-4 rounded"} style={{ background: color }} />
      {label}
    </li>
  );
}

// --- Overhead by mode ---------------------------------------------------------------------

export function ModeChart({ events }: { events: TrafficEvent[] }) {
  const rows = overheadByMode(events);
  if (!rows.length) return <ChartEmpty>No calls yet.</ChartEmpty>;
  const max = niceCeil(Math.max(...rows.map((r) => r.p95)) * 1.1);
  return (
    <div>
      <ul className="space-y-3" aria-label="PII Guard overhead by gateway mode">
        {rows.map((r) => (
          <li key={r.mode}>
            <p className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium text-ink capitalize">{r.mode}</span>
              <span className="text-xs tabular-nums text-muted">
                p50 {formatMsShort(r.p50)} · p95 {formatMsShort(r.p95)} · {r.n} {r.n === 1 ? "call" : "calls"}
              </span>
            </p>
            <div aria-hidden="true" className="relative h-3 rounded-sm bg-surface-2 ring-1 ring-line ring-inset">
              <span className="absolute inset-y-0 left-0 rounded-sm" style={{ width: `${(r.p50 / max) * 100}%`, background: "var(--stage-parse)" }} />
              <span className="absolute -inset-y-0.5 w-0.5 bg-[var(--stage-detect)]" style={{ left: `${(r.p95 / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex flex-wrap gap-x-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-2.5 w-4 rounded-sm bg-[var(--stage-parse)]" /> p50
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="h-3 w-0.5 bg-[var(--stage-detect)]" /> p95
        </span>
        <span>Scale 0 to {formatMsShort(max)}.</span>
      </p>
    </div>
  );
}

// --- Stage breakdown ----------------------------------------------------------------------

/** A column button is at least 24 px wide (44 px on a touch screen): fewer, wider columns on a phone. */
const COLUMN_MIN = { fine: 24, coarse: 44 } as const;
const isCoarse = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(pointer: coarse)").matches);

export function StageChart({ events, onSelect }: { events: TrafficEvent[]; onSelect?: (id: string) => void }) {
  const [ref, width] = useWidth(560);
  const [coarse] = useState(isCoarse);
  // The y axis takes about 40 px; each column keeps a 2 px gap.
  const fit = Math.floor((width - 40) / ((coarse ? COLUMN_MIN.coarse : COLUMN_MIN.fine) + 2));
  const recent = events.slice(-Math.max(5, Math.min(30, fit)));
  if (!recent.length) return <ChartEmpty>No calls yet.</ChartEmpty>;
  const max = niceCeil(Math.max(...recent.map((e) => OWN_STAGES.reduce((s, k) => s + (e.timing.stages_ms[k] ?? 0), 0))));
  const used = OWN_STAGES.filter((k) => recent.some((e) => (e.timing.stages_ms[k] ?? 0) > 0));
  return (
    <div ref={ref}>
      <div className="flex gap-2">
        <div aria-hidden="true" className="flex h-40 flex-col justify-between text-right text-xs tabular-nums text-muted">
          <span>{formatMsShort(max)}</span>
          <span>0</span>
        </div>
        <ol aria-label={`PII Guard's own stages per call, last ${recent.length} calls`} className="flex h-40 flex-1 items-end gap-[2px] border-b border-line">
          {recent.map((e) => {
            const parts = OWN_STAGES.map((k) => [k, e.timing.stages_ms[k] ?? 0] as const).filter(([, v]) => v > 0);
            const label = parts.map(([k, v]) => `${STAGE_LABEL[k]} ${formatMsShort(v)}`).join(", ");
            const time = clockTime(e.time);
            return (
              <li key={e.id} className="flex h-full min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => onSelect?.(e.id)}
                  title={`${time}: ${label}`}
                  aria-label={`Call at ${time}: ${label}. Show this call.`}
                  className="flex h-full w-full flex-col-reverse gap-px rounded-t-sm hover:bg-surface-2"
                >
                  {parts.map(([k, v]) => (
                    <span key={k} className="w-full shrink-0 first:rounded-b-none last:rounded-t-[3px]" style={{ height: `${(v / max) * 100}%`, background: STAGE_COLOR[k] }} />
                  ))}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Stages">
        {used.map((k) => (
          <li key={k} className="flex items-center gap-1.5" title={STAGE_HINT[k]}>
            <span aria-hidden="true" className="size-2.5 rounded-sm" style={{ background: STAGE_COLOR[k] }} />
            {STAGE_LABEL[k]}
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- Entities per minute ------------------------------------------------------------------

export function EntitiesChart({ events, now }: { events: TrafficEvent[]; now: number }) {
  const buckets = entitiesPerMinute(events, now);
  const total = buckets.reduce((s, b) => s + b.total, 0);
  if (!total) return <ChartEmpty>No values masked in the last 10 minutes.</ChartEmpty>;
  const max = niceCeil(Math.max(...buckets.map((b) => b.total)));
  // Seventeen entity types fold into five fixed families, so each keeps one categorical slot.
  const byGroup = (counts: Partial<Record<EntityType, number>>) => {
    const out = new Map<string, number>();
    for (const [t, n] of Object.entries(counts) as [EntityType, number][]) {
      if (n) out.set(groupOf(t).id, (out.get(groupOf(t).id) ?? 0) + n);
    }
    return out;
  };
  const present = new Set(buckets.flatMap((b) => [...byGroup(b.counts).keys()]));
  const groups = ENTITY_GROUPS.filter((g) => present.has(g.id));
  const hhmm = clockMinutes;
  return (
    <div>
      <div className="flex gap-2">
        <div aria-hidden="true" className="flex h-40 flex-col justify-between text-right text-xs tabular-nums text-muted">
          <span>{max}</span>
          <span>0</span>
        </div>
        <ol aria-label={`Values masked per minute by kind, last 10 minutes: ${total} in total`} className="flex h-40 flex-1 items-end gap-0.5 border-b border-line-strong">
          {buckets.map((b) => {
            const g = byGroup(b.counts);
            const types = (Object.keys(b.counts) as EntityType[]).filter((t) => b.counts[t]).sort();
            const label = b.total ? types.map((t) => `${metaFor(t).label} ${b.counts[t]}`).join(", ") : "none";
            return (
              <li key={b.minute} className="flex h-full min-w-0 flex-1 flex-col-reverse gap-0.5" title={`${hhmm(b.minute)}: ${label}`}>
                <span className="sr-only">
                  {hhmm(b.minute)}: {label}
                </span>
                {groups
                  .filter((grp) => g.get(grp.id))
                  .map((grp) => (
                    <span
                      key={grp.id}
                      aria-hidden="true"
                      className="w-full shrink-0 last:rounded-t-sm"
                      style={{ height: `${((g.get(grp.id) ?? 0) / max) * 100}%`, background: grp.color }}
                    />
                  ))}
              </li>
            );
          })}
        </ol>
      </div>
      <div aria-hidden="true" className="mt-1 flex justify-between pl-8 text-xs text-faint tabular-nums">
        <span>{hhmm(buckets[0]!.minute)}</span>
        <span>{hhmm(buckets[buckets.length - 1]!.minute)}</span>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Kinds of value">
        {groups.map((grp) => (
          <li key={grp.id} className="flex items-center gap-1.5">
            <span aria-hidden="true" className="size-2.5 rounded-sm" style={{ background: grp.color }} />
            {grp.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
