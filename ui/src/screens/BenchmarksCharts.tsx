import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  formatMs,
  formatPct,
  languageName,
  pick,
  type HistoryPoint,
  type LanguageFilter,
  type Metrics,
  type Snapshot,
  type SystemInfo,
} from "../api/benchmarks";

/* Charts for the Benchmarks screen. SVG charts are drawn at the container's real pixel width
 * (measured with a ResizeObserver), so text stays 12 px+ on a phone instead of shrinking with
 * a viewBox. Every chart has a text alternative: the tables on the screen hold the same data. */

const FONT = 12;

function useWidth(fallback = 720) {
  // A callback ref: the observer attaches whenever the chart's container mounts, even if the
  // first render returned the empty state.
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  const ref = useCallback((node: HTMLDivElement | null) => {
    setEl(node);
    if (node && node.clientWidth > 0) setWidth(Math.floor(node.clientWidth)); // first paint, before any resize event
  }, []);
  return [ref, width] as const;
}

// Palette colours too dark to tell apart on the dark canvas get a theme variable (index.css).
const DARK_ADJUSTED = new Set(["#882255", "#332288"]);

/** Comparison tools are drawn in the theme's muted ink (hollow), pii-guard in its own colour. */
function colorOf(info: SystemInfo | undefined): string {
  if (!info || info.family === "comparison") return "var(--muted)";
  const c = info.color.toUpperCase();
  return DARK_ADJUSTED.has(c) ? `var(--sys-${c.slice(1).toLowerCase()}, ${c})` : info.color;
}

export function Marker({ info, x = 0, y = 0, r = 6 }: { info: SystemInfo | undefined; x?: number; y?: number; r?: number }) {
  const color = colorOf(info);
  const hollow = info?.family === "comparison";
  const fill = hollow ? "var(--surface)" : color;
  // Filled markers get a faint ink ring so dark colours (indigo, wine) stay visible on a dark surface.
  const stroke = hollow ? { stroke: color, strokeWidth: 2 } : { stroke: "var(--ink)", strokeOpacity: 0.45, strokeWidth: 1.25 };
  switch (info?.shape) {
    case "square":
      return <rect x={x - r * 0.85} y={y - r * 0.85} width={r * 1.7} height={r * 1.7} fill={fill} {...stroke} />;
    case "triangle":
      return <path d={`M${x},${y - r}L${x + r},${y + r * 0.8}L${x - r},${y + r * 0.8}Z`} fill={fill} {...stroke} />;
    case "diamond":
      return <path d={`M${x},${y - r}L${x + r},${y}L${x},${y + r}L${x - r},${y}Z`} fill={fill} {...stroke} />;
    case "cross":
      return (
        <path
          d={`M${x - r * 0.8},${y - r * 0.8}L${x + r * 0.8},${y + r * 0.8}M${x - r * 0.8},${y + r * 0.8}L${x + r * 0.8},${y - r * 0.8}`}
          stroke={color}
          strokeWidth={2.5}
        />
      );
    default:
      return <circle cx={x} cy={y} r={r} fill={fill} {...stroke} />;
  }
}

export function MarkerIcon({ info }: { info: SystemInfo | undefined }) {
  return (
    <svg aria-hidden="true" viewBox="-8 -8 16 16" className="size-3.5 shrink-0">
      <Marker info={info} r={6} />
    </svg>
  );
}

function niceMax(v: number): number {
  return Math.min(1, Math.max(0.1, Math.ceil((v + 0.04) * 10) / 10));
}

function textWidth(text: string, size = FONT): number {
  return text.length * size * 0.6; // semibold Instrument Sans averages about 0.58 em
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const overlaps = (a: Box, b: Box) => !(a.x1 < b.x0 || a.x0 > b.x1 || a.y1 < b.y0 || a.y0 > b.y1);

// --- Leak vs latency --------------------------------------------------------------------

export interface ScatterPoint {
  key: string;
  info: SystemInfo | undefined;
  metrics: Metrics;
}

export function LeakLatencyChart({ points }: { points: ScatterPoint[] }) {
  const [ref, width] = useWidth();
  const pts = points.filter((p) => p.metrics.detect_p50_ms);
  if (!pts.length) return <ChartEmpty>No latency was recorded for these runs.</ChartEmpty>;
  const height = Math.round(Math.min(420, Math.max(340, width * 0.55)));
  const m = { l: 44, r: 12, t: 12, b: 40 };
  const lat = pts.flatMap((p) => [p.metrics.detect_p50_ms!, p.metrics.detect_p95_ms ?? p.metrics.detect_p50_ms!]);
  const lo = Math.floor(Math.log10(Math.min(...lat)));
  const hi = Math.max(lo + 1, Math.ceil(Math.log10(Math.max(...lat))));
  const ymax = niceMax(Math.max(...pts.map((p) => p.metrics.leak ?? 0)));
  const pad = ymax * 0.05;
  const sx = (ms: number) => m.l + ((Math.log10(ms) - lo) / (hi - lo)) * (width - m.l - m.r);
  const sy = (v: number) => height - m.b - ((v + pad) / (ymax + pad)) * (height - m.t - m.b);
  const yTicks = Array.from({ length: Math.round(ymax / 0.1) + 1 }, (_, i) => i * 0.1).filter(
    (_, i, all) => all.length <= 6 || i % 2 === 0,
  );
  const decades = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  const showEvery = width < 420 && decades.length > 4 ? 2 : 1;

  // Greedy label placement: above, below, right, left; skip a label that can't fit (the
  // legend under the chart names every point anyway).
  const taken: Box[] = pts.map((p) => {
    const x = sx(p.metrics.detect_p50_ms!);
    const x95 = sx(p.metrics.detect_p95_ms ?? p.metrics.detect_p50_ms!);
    const y = sy(p.metrics.leak ?? 0);
    return { x0: x - 8, y0: y - 8, x1: Math.max(x, x95) + 8, y1: y + 8 };
  });
  // Labels may run into the y-axis gutter on a narrow chart, but not over its tick labels.
  for (const t of yTicks) taken.push({ x0: 0, y0: sy(t) - 9, x1: m.l - 4, y1: sy(t) + 7 });
  // Best (lowest leak) first, so it wins its label spot; drawn last, so it sits on top.
  // Ties (several systems at 0.0 %) go to the featured / default systems, then the faster one.
  const rank = (p: ScatterPoint) => (p.info?.default ? 0 : p.info?.featured ? 1 : 2);
  const byLeak = [...pts].sort(
    (a, b) =>
      (a.metrics.leak ?? 1) - (b.metrics.leak ?? 1) ||
      rank(a) - rank(b) ||
      (a.metrics.detect_p50_ms ?? 0) - (b.metrics.detect_p50_ms ?? 0),
  );
  // Dense charts label only the featured systems in the plot; the legend below names the rest.
  const dense = pts.length > 7;
  const labels = byLeak.map((p) => {
    if (dense && !p.info?.featured && !p.info?.default) return null;
    const text = `${p.info?.short_label ?? p.key} ${formatPct(p.metrics.leak)}`;
    const x = sx(p.metrics.detect_p50_ms!);
    const y = sy(p.metrics.leak ?? 0);
    const tries: [number, number, "start" | "end"][] = [
      [x - 4, y - 12, "start"],
      [x - 4, y + 22, "start"],
      [x + 4, y - 12, "end"],
      [x + 4, y + 22, "end"],
      [x + 12, y + 4, "start"],
      [x - 12, y + 4, "end"],
      [x - 4, y - 30, "end"],
      [x + 4, y - 30, "start"],
      [x - 4, y - 46, "end"],
      [x + 4, y - 46, "start"],
      [x - 4, y - 62, "end"],
      [x + 4, y - 62, "start"],
      [x - 4, y - 78, "end"],
      [x + 4, y - 78, "start"],
    ];
    const place = (label: string, lx: number, ly: number, anchor: "start" | "end") => {
      const lw = textWidth(label);
      const left = anchor === "start" ? lx : lx - lw;
      const box = { x0: left - 2, y0: ly - FONT, x1: left + lw + 2, y1: ly + 3 };
      if (box.x0 < 2 || box.x1 > width - 2 || box.y0 < 0 || box.y1 > height - m.b) return false;
      if (taken.some((t) => overlaps(t, box))) return false;
      taken.push(box);
      return true;
    };
    for (const [lx, ly, anchor] of tries) {
      if (place(text, lx, ly, anchor)) return { text, x: lx, y: ly, anchor, px: x, py: y };
    }
    // Crowded: the value alone, beside the marker (the legend below names every point).
    const value = formatPct(p.metrics.leak);
    for (const [lx, ly, anchor] of [
      [x - 12, y + 4, "end"],
      [x + 12, y + 4, "start"],
      [x, y - 12, "start"],
    ] as const) {
      if (place(value, lx, ly, anchor)) return { text: value, x: lx, y: ly, anchor, px: x, py: y };
    }
    return null;
  });

  return (
    <div ref={ref} className="w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`Leak rate against detection latency per document: ${pts
          .map((p) => `${p.info?.label ?? p.key} ${formatPct(p.metrics.leak)} leak at ${formatMs(p.metrics.detect_p50_ms)}`)
          .join("; ")}.`}
        className="block overflow-visible font-sans"
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} stroke="var(--line)" />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        {decades.map((e, i) => (
          <g key={e}>
            <line x1={sx(10 ** e)} x2={sx(10 ** e)} y1={m.t} y2={height - m.b} stroke="var(--line)" />
            {i % showEvery === 0 && (
              <text x={sx(10 ** e)} y={height - m.b + 18} textAnchor="middle" fontSize={FONT} fill="var(--muted)">
                {formatMs(10 ** e).replace(".00 ms", " ms").replace(".0 ", " ")}
              </text>
            )}
          </g>
        ))}
        <line x1={m.l} x2={width - m.r} y1={height - m.b} y2={height - m.b} stroke="var(--line-strong)" />
        <text x={(m.l + width - m.r) / 2} y={height - 4} textAnchor="middle" fontSize={FONT} fill="var(--muted)">
          detection latency per document, p50 to p95 (log scale)
        </text>
        {[...byLeak].reverse().map((p) => {
          const x = sx(p.metrics.detect_p50_ms!);
          const y = sy(p.metrics.leak ?? 0);
          const p95 = p.metrics.detect_p95_ms;
          return (
            <g key={p.key}>
              <title>{`${p.info?.label ?? p.key}: ${formatPct(p.metrics.leak)} leak, p50 ${formatMs(p.metrics.detect_p50_ms)}, p95 ${formatMs(p95)}`}</title>
              {p95 && p95 > p.metrics.detect_p50_ms! && (
                <g stroke={colorOf(p.info)} strokeWidth={2} opacity={0.7}>
                  <line x1={x} x2={sx(p95)} y1={y} y2={y} />
                  <line x1={sx(p95)} x2={sx(p95)} y1={y - 5} y2={y + 5} />
                </g>
              )}
              <Marker info={p.info} x={x} y={y} r={7} />
            </g>
          );
        })}
        {labels.map(
          (l, i) =>
            l && (
              <g key={byLeak[i]!.key}>
                {Math.hypot(l.x - l.px, l.y - l.py) > 22 && <line x1={l.px} y1={l.py - 8} x2={l.x} y2={l.y + 3} stroke="var(--muted)" strokeWidth={1} />}
                <text x={l.x} y={l.y} textAnchor={l.anchor} fontSize={FONT} fontWeight={600} fill="var(--ink)">
                  {l.text}
                </text>
              </g>
            ),
        )}
      </svg>
      {dense && <p className="mt-2 text-xs text-muted">Many systems: only the featured ones are labelled in the chart. Hover a marker, or see the list below.</p>}
      <ul className="mt-3 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
        {pts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <MarkerIcon info={p.info} />
            <span className="min-w-0 flex-1 truncate text-ink">{p.info?.short_label ?? p.key}</span>
            <span className="tabular-nums text-muted">
              {formatPct(p.metrics.leak)} · {formatMs(p.metrics.detect_p50_ms)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- Leak over time ---------------------------------------------------------------------

export function ProgressChart({
  history,
  systems,
  lang,
}: {
  history: HistoryPoint[];
  systems: Record<string, SystemInfo>;
  lang: LanguageFilter;
}) {
  const [ref, width] = useWidth();
  const points = history
    .map((h) => ({ h, m: pick(h, lang) }))
    .filter((p): p is { h: HistoryPoint; m: Metrics } => p.m !== null && p.m.leak !== null);
  if (!points.length) return <ChartEmpty>No pii-guard runs on this set and language yet.</ChartEmpty>;
  const cats: string[] = [];
  for (const { h } of points) {
    const c = `${h.date} ${h.commit.slice(0, 7)}`;
    if (!cats.includes(c)) cats.push(c);
  }
  const height = Math.round(Math.min(360, Math.max(240, width * 0.45)));
  const m = { l: 44, r: 16, t: 12, b: 44 };
  const ymax = niceMax(Math.max(...points.map((p) => p.m.leak ?? 0)));
  const step = (width - m.l - m.r) / cats.length;
  const sx = (c: string) => m.l + (cats.indexOf(c) + 0.5) * step;
  const sy = (v: number) => height - m.b - (v / ymax) * (height - m.t - m.b);
  const bySystem = new Map<string, { x: number; y: number; h: HistoryPoint; m: Metrics }[]>();
  for (const { h, m: mm } of points) {
    const list = bySystem.get(h.system) ?? [];
    list.push({ x: sx(`${h.date} ${h.commit.slice(0, 7)}`), y: sy(mm.leak!), h, m: mm });
    bySystem.set(h.system, list);
  }
  // Best pii-guard result so far, as a step line across the categories.
  let best = Infinity;
  const steps: string[] = [];
  cats.forEach((c, i) => {
    const here = points.filter((p) => `${p.h.date} ${p.h.commit.slice(0, 7)}` === c).map((p) => p.m.leak!);
    if (here.length) best = Math.min(best, ...here);
    if (best === Infinity) return;
    const x0 = m.l + i * step;
    steps.push(`${steps.length ? "L" : "M"}${x0},${sy(best)}L${x0 + step},${sy(best)}`);
  });
  const yTicks = Array.from({ length: Math.round(ymax / 0.1) + 1 }, (_, i) => i * 0.1).filter(
    (_, i, all) => all.length <= 6 || i % 2 === 0,
  );
  const labelEvery = Math.max(1, Math.ceil((cats.length * 72) / (width - m.l - m.r)));

  return (
    <div ref={ref} className="w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`Leak rate of each pii-guard configuration over time: ${[...bySystem.entries()]
          .map(([k, list]) => `${systems[k]?.label ?? k} latest ${formatPct(list[list.length - 1]!.m.leak)}`)
          .join("; ")}.`}
        className="block overflow-visible font-sans"
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} stroke="var(--line)" />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end" fontSize={FONT} fill="var(--muted)">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        <line x1={m.l} x2={width - m.r} y1={height - m.b} y2={height - m.b} stroke="var(--line-strong)" />
        {cats.map((c, i) =>
          i % labelEvery === 0 ? (
            <g key={c} fontSize={FONT} fill="var(--muted)" textAnchor="middle">
              <text x={sx(c)} y={height - m.b + 17}>
                {c.split(" ")[0]}
              </text>
              <text x={sx(c)} y={height - m.b + 32} className="font-mono" fontSize={FONT - 1}>
                {c.split(" ")[1]}
              </text>
            </g>
          ) : null,
        )}
        <path d={steps.join("")} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="5 4" />
        {[...bySystem.entries()].map(([k, list]) => (
          <g key={k}>
            {list.length > 1 && (
              <path d={list.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join("")} fill="none" stroke={colorOf(systems[k])} strokeWidth={2.5} />
            )}
            {list.map((p) => (
              <g key={p.h.run_ids.join()}>
                <title>{`${systems[k]?.label ?? k}, ${p.h.date} (${p.h.commit.slice(0, 7)}): ${formatPct(p.m.leak)} leak`}</title>
                <Marker info={systems[k]} x={p.x} y={p.y} r={6} />
              </g>
            ))}
          </g>
        ))}
      </svg>
    </div>
  );
}

// --- By language (HTML bars) ------------------------------------------------------------

export function LanguageBars({
  snapshots,
  systems,
  languages,
}: {
  snapshots: Snapshot[];
  systems: Record<string, SystemInfo>;
  languages: string[];
}) {
  const panels: { key: "f1" | "leak"; title: string }[] = [
    { key: "f1", title: "F1 (higher is better)" },
    { key: "leak", title: "Leak rate (lower is safer)" },
  ];
  return (
    <div className="space-y-4">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Languages">
        {languages.map((lang, i) => (
          <li key={lang} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={["h-2.5 w-4 rounded-sm", LANG_BG[i % LANG_BG.length]].join(" ")} />
            {languageName(lang)}
          </li>
        ))}
      </ul>
      <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
        {panels.map((panel) => (
          <div key={panel.key}>
            <h4 className="mb-2 text-xs font-semibold tracking-wide text-faint uppercase">{panel.title}</h4>
            <ul className="space-y-3">
              {snapshots.map((s) => (
                <li key={s.system}>
                  <p className="mb-1 flex items-center gap-1.5 text-sm font-medium text-ink">
                    <MarkerIcon info={systems[s.system]} />
                    {systems[s.system]?.short_label ?? s.system}
                  </p>
                  {languages.map((lang, i) => {
                    const v = s.languages[lang]?.[panel.key] ?? null;
                    return (
                      <div key={lang} className="flex items-center gap-2 text-xs">
                        <span className="w-6 shrink-0 font-mono text-faint uppercase">{lang}</span>
                        <div className="h-3 flex-1 rounded-sm bg-surface-2 ring-1 ring-line ring-inset">
                          {v !== null && (
                            <div
                              className={["h-full rounded-sm", LANG_BG[i % LANG_BG.length]].join(" ")}
                              style={{ width: v > 0 ? `${Math.max(v * 100, 0.8)}%` : "0%" }}
                            />
                          )}
                        </div>
                        <span className="w-14 shrink-0 text-right tabular-nums text-ink">{v === null ? "not run" : formatPct(v)}</span>
                      </div>
                    );
                  })}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

const LANG_BG = ["bg-model", "bg-guard", "bg-warn", "bg-danger", "bg-ink"];

// --- Recall per entity type (HTML heatmap) ----------------------------------------------

export function TypeHeatmap({
  snapshots,
  systems,
  types,
  lang,
}: {
  snapshots: Snapshot[];
  systems: Record<string, SystemInfo>;
  types: string[];
  lang: LanguageFilter;
}) {
  const cols = snapshots.map((s) => ({ s, m: pick(s, lang) }));
  const rows = types.filter((t) => cols.some(({ m }) => m?.per_type[t]));
  if (!rows.length) return <ChartEmpty>No per-type results for this selection.</ChartEmpty>;
  return (
    <div
      role="region"
      aria-label="Recall per entity type, scrolls sideways"
      tabIndex={0}
      className="-mx-4 overflow-x-auto px-4 focus-visible:outline-2 focus-visible:outline-ink sm:mx-0 sm:px-0"
    >
      <table className="w-full min-w-max border-separate border-spacing-0.5 text-xs">
        <caption className="sr-only">Overlap recall per entity type and system</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 z-10 bg-surface px-2 py-1 text-left font-semibold text-faint">
              Type
            </th>
            {cols.map(({ s }) => (
              <th key={s.system} scope="col" className="max-w-24 px-1 py-1 text-center align-bottom font-medium text-ink">
                {systems[s.system]?.short_label ?? s.system}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const gold = Math.max(...cols.map(({ m }) => m?.per_type[t]?.gold ?? 0));
            return (
              <tr key={t}>
                <th scope="row" className="sticky left-0 z-10 bg-surface px-2 py-1 text-left font-mono font-normal whitespace-nowrap text-ink">
                  {t} <span className="text-faint">n={gold}</span>
                </th>
                {cols.map(({ s, m }) => {
                  const v = m?.per_type[t]?.recall ?? null;
                  return (
                    <td
                      key={s.system}
                      className="min-w-14 rounded px-2 py-1.5 text-center tabular-nums"
                      style={
                        v === null
                          ? undefined
                          : {
                              background: `color-mix(in oklab, var(--model) ${Math.round(v * 92 + 4)}%, var(--surface))`,
                              color: v > 0.55 ? "var(--surface)" : "var(--ink)",
                            }
                      }
                    >
                      {v === null ? <span className="text-faint">–</span> : Math.round(v * 100)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ChartEmpty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-sm text-muted">{children}</p>;
}
