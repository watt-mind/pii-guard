import { useEffect, useId, useRef, useState } from "react";
import { engineReason, type EngineDisplay, type EngineState, type ModePreference } from "../api/engine";
import type { ThemePref } from "../hooks/useTheme";
import { SECTIONS, hashOf, type Route, type Section } from "../lib/routes";

interface Props {
  route: Route;
  /** A section was picked from the menu (links also work without this, through the hash). */
  onSection: (s: Section) => void;
  engineState: EngineState;
  engine: EngineDisplay;
  onPreference: (p: ModePreference) => void;
  onRecheck: () => void;
  theme: ThemePref;
  onTheme: (t: ThemePref) => void;
  /** What the connected server runs, for the status tooltip ("fast mode · rules+ner"). */
  statusDetail?: string | null;
}

/**
 * The console's navigation: a fixed left column from 1024 px, a top bar with a menu below.
 * Sections are plain hash links, so they open in a new tab, can be copied, and keep working
 * with the back button.
 */
export function Sidebar({ route, onSection, engineState, engine, onPreference, onRecheck, theme, onTheme, statusDetail }: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const menuButton = useRef<HTMLButtonElement>(null);

  // Escape closes the phone menu and returns focus to its button.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      menuButton.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const current = SECTIONS.find((s) => s.id === route.section)!;

  return (
    // The column carries the border, so it runs the full page height; the sticky panel inside
    // is only as tall as its content (at most the viewport), so nothing ends up below the fold
    // when something sits above the console, such as the strip pii-guard up injects.
    <div className="relative z-30 border-line bg-canvas lg:border-r">
      <aside className="lg:sticky lg:top-0 lg:flex lg:max-h-dvh lg:flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
          Skip to content
        </a>
        {/* The brand row shares the nav items' gutter (px-2 + px-3), so the mark sits over their icons. */}
        <div className="flex items-center gap-2 px-2 py-2.5 lg:pt-3 lg:pb-2">
          <a href="#overview" className="flex h-9 min-w-0 items-center gap-2.5 rounded-sm px-3 text-ink">
            <Logo />
            <span className="text-base font-medium">pii-guard</span>
          </a>
          <span className="truncate text-sm text-muted lg:hidden">{current.label}</span>
          <span className="flex-1 lg:hidden" />
          <button
            ref={menuButton}
            type="button"
            aria-expanded={open}
            aria-controls={menuId}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-sm font-medium text-ink lg:hidden"
          >
            <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              {open ? <path d="M4 4l8 8M12 4l-8 8" /> : <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />}
            </svg>
            Menu
          </button>
        </div>

        <div id={menuId} className={[open ? "block" : "hidden", "border-t border-line lg:flex lg:min-h-0 lg:flex-col lg:border-t-0"].join(" ")}>
          <nav aria-label="Console" className="px-2 py-2 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:px-2">
            {NAV_GROUPS.map((group, gi) => (
              <div key={group.label ?? "top"} className={group.label ? "mt-4" : undefined}>
                {group.label && (
                  <p id={`${menuId}-group-${gi}`} className="px-3 pb-1.5 text-2xs font-medium tracking-[0.04em] text-faint uppercase">
                    {group.label}
                  </p>
                )}
                <ul className="space-y-0.5" aria-labelledby={group.label ? `${menuId}-group-${gi}` : undefined}>
                  {SECTIONS.filter((s) => group.ids.includes(s.id)).map((s) => {
                    const active = s.id === route.section;
                    return (
                      <li key={s.id}>
                        <a
                          href={hashOf({ section: s.id, tab: route.tab })}
                          aria-current={active ? "page" : undefined}
                          onClick={(e) => {
                            // A plain click navigates here, without a history entry per section;
                            // a modified click (new tab) is left to the browser.
                            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                            e.preventDefault();
                            setOpen(false);
                            onSection(s.id);
                          }}
                          className={[
                            "flex min-h-10 items-center gap-3 rounded-sm px-3 py-2 text-sm text-ink transition-colors lg:min-h-9 lg:py-1.5",
                            active ? "bg-surface-2 font-medium" : "hover:bg-surface-2",
                          ].join(" ")}
                        >
                          <SectionIcon id={s.id} active={active} />
                          <span className="min-w-0">
                            <span className="block">{s.label}</span>
                            <span className="block text-2xs text-faint lg:hidden">{s.hint}</span>
                          </span>
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>

          <div className="space-y-2.5 border-t border-line px-5 py-3">
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted" htmlFor="engine-mode">
                Engine
              </label>
              <select
                id="engine-mode"
                value={engineState.preference}
                onChange={(e) => onPreference(e.target.value as ModePreference)}
                className="h-8 min-w-0 flex-1 rounded-lg border border-field bg-surface px-2 text-xs text-ink"
              >
                <option value="auto">Auto</option>
                <option value="api">Live API</option>
                <option value="mock">Demo engine</option>
              </select>
            </div>
            <div className="flex items-center justify-between gap-2">
              <EngineStatus state={engineState} engine={engine} detail={statusDetail} onRecheck={onRecheck} />
              <ThemeToggle theme={theme} onTheme={onTheme} />
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}

/** Sidebar groups, in the sections' own order: the console's map, not new destinations. */
const NAV_GROUPS: readonly { label: string | null; ids: readonly Section[] }[] = [
  { label: null, ids: ["overview"] },
  { label: "Inspect", ids: ["playground", "logs"] },
  { label: "Set up", ids: ["connect", "policy"] },
  { label: "Measure", ids: ["evaluation"] },
];

const ICONS: Record<Section, string> = {
  overview: "M2.5 13.5h11M4.5 11V7.5M8 11V4M11.5 11V6",
  playground: "M4 3.5 2 8l2 4.5M12 3.5 14 8l-2 4.5M9.5 3 6.5 13",
  logs: "M2.5 4h11M2.5 8h11M2.5 12h7",
  connect: "M6.5 9.5 9.5 6.5M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1A2.5 2.5 0 0 1 4.5 9l1-1",
  policy: "M8 2.5 3.5 4.5v3.2c0 2.8 1.9 5 4.5 5.8 2.6-.8 4.5-3 4.5-5.8V4.5L8 2.5ZM6 8l1.5 1.5L10.5 6.5",
  evaluation: "M3 13V3M3 13h10.5M5.5 10l2.5-3 2 2 3-4",
};

function SectionIcon({ id, active }: { id: Section; active: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      className={["size-4 shrink-0", active ? "text-ink" : "text-muted"].join(" ")}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={ICONS[id]} />
    </svg>
  );
}

/**
 * The connection, as a quiet footer line: a dot and the API version when all is well. The
 * label grows only when something differs: the demo engine answers, or the API is down (red).
 * A click checks again.
 */
export function EngineStatus({ state, engine, detail, onRecheck }: { state: EngineState; engine: EngineDisplay; detail?: string | null; onRecheck: () => void }) {
  const reason = engineReason(state);
  const status = state.status;
  const version = status.state === "online" ? `v${status.version}` : null;
  // Down means nobody asked for the demo engine and the API does not answer: the one case
  // worth attention, so it is red here and in the notice above the content.
  const down = engine === "mock" && state.preference !== "mock" && status.state === "offline";
  const { label, shown, sub, tone } =
    engine === "pending"
      ? { label: "Connecting…", shown: true, sub: null, tone: "pending" as const }
      : engine === "mock"
        ? { label: "Demo mode", shown: true, sub: status.state === "online" ? `API ${version} up, not in use` : "API offline", tone: down ? ("down" as const) : ("demo" as const) }
        : { label: "API up", shown: false, sub: version, tone: "live" as const };
  const dot = { live: "bg-guard-dot", demo: "bg-warn", down: "bg-danger", pending: "bg-faint motion-safe:animate-pulse" }[tone];
  const tip = tone === "live" ? ["API connected", detail].filter(Boolean).join(" · ") : reason;

  return (
    <div role="status" aria-label={`${label}. ${reason}.`} className="min-w-0">
      <button
        type="button"
        onClick={onRecheck}
        title={`${tip}. Click to check again.`}
        className="inline-flex h-7 max-w-full min-w-0 items-center gap-2 rounded-sm text-xs whitespace-nowrap text-muted transition-colors hover:text-ink"
      >
        <span aria-hidden="true" className={["size-1.5 shrink-0 rounded-full", dot].join(" ")} />
        <span className={shown ? (tone === "down" ? "font-medium text-danger" : tone === "demo" ? "font-medium text-warn" : "") : "sr-only"}>{label}</span>
        {sub && <span className="truncate tabular-nums">{sub}</span>}
      </button>
    </div>
  );
}

function ThemeToggle({ theme, onTheme }: { theme: ThemePref; onTheme: (t: ThemePref) => void }) {
  const options: { id: ThemePref; label: string; icon: string }[] = [
    { id: "light", label: "Light theme", icon: "M8 3.5V2m0 12v-1.5M3.5 8H2m12 0h-1.5M4.8 4.8 3.8 3.8m8.4 8.4-1-1m0-6.4 1-1M3.8 12.2l1-1M10.5 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" },
    { id: "system", label: "System theme", icon: "M2.5 3.5h11v7h-11zM6 13.5h4M8 10.5v3" },
    { id: "dark", label: "Dark theme", icon: "M13 9.6A5.5 5.5 0 0 1 6.4 3a5.5 5.5 0 1 0 6.6 6.6Z" },
  ];
  return (
    <div role="group" aria-label="Theme" className="flex shrink-0 rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={theme === o.id}
          aria-label={o.label}
          title={o.label}
          onClick={() => onTheme(o.id)}
          className={["grid size-7 place-items-center rounded-md transition-colors", theme === o.id ? "bg-primary text-on-primary" : "text-muted hover:text-ink"].join(" ")}
        >
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d={o.icon} />
          </svg>
        </button>
      ))}
    </div>
  );
}

function Logo() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 shrink-0 text-ink" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round">
      <path d="M12 3 5 6v5.2c0 4.3 2.9 8 7 9.3 4.1-1.3 7-5 7-9.3V6l-7-3Z" />
      <path d="M8.6 12h6.8" strokeLinecap="round" />
    </svg>
  );
}
