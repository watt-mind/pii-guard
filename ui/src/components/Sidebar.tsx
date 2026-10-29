import { MENU_OPENED } from "../hooks/useMenu";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { engineReason, type EngineDisplay, type EngineState, type ModePreference } from "../api/engine";
import type { ThemePref } from "../hooks/useTheme";
import { SECTIONS, hashOf, type Route, type Section } from "../lib/routes";
import { offersSection, playgroundHint, type Capabilities } from "../lib/capabilities";
import { Logo, Select, ThemeToggle } from "./ui";
import { buttonClass } from "./controls";

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
  /** What the server offers: sections it doesn't are left out of the menu. */
  caps: Capabilities;
}

/**
 * The console's navigation: a fixed left column from 1024 px, a top bar with a menu below.
 * Sections are plain hash links, so they open in a new tab, can be copied, and keep working
 * with the back button.
 */
export function Sidebar({ route, onSection, engineState, engine, onPreference, onRecheck, theme, onTheme, statusDetail, caps }: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const menuButton = useRef<HTMLButtonElement>(null);
  const focusDestination = useRef(false);

  // A route change from outside the menu (a link, Back, a chart) closes the phone menu.
  const routeKey = `${route.section}/${route.tab}`;
  const [shownFor, setShownFor] = useState(routeKey);
  if (shownFor !== routeKey) {
    setShownFor(routeKey);
    setOpen(false);
  }
  // Position the destination only after the expanded mobile menu has collapsed.
  useLayoutEffect(() => {
    if (open || !focusDestination.current) return;
    focusDestination.current = false;
    const main = document.getElementById("main");
    main?.focus({ preventScroll: true });
    main?.scrollIntoView({ block: "start", behavior: "auto" });
  }, [open, routeKey]);

  // So does another menu opening (the profile or project menu: useMenu announces it).
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener(MENU_OPENED, close);
    window.addEventListener("hashchange", close);
    return () => {
      window.removeEventListener(MENU_OPENED, close);
      window.removeEventListener("hashchange", close);
    };
  }, [open]);

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
        <div className="flex h-14 items-center gap-2 px-2 lg:h-12">
          {/* The 24px mark is 8px wider than the 16px nav icons, so px-2 (not px-3) keeps it centred over them. */}
          <a href="#overview" className="flex h-9 min-w-0 items-center gap-2.5 rounded-sm px-2 text-ink">
            <Logo />
            <span className="text-base font-medium">PII Guard</span>
          </a>
          <span className="truncate text-sm text-muted lg:hidden">{current.label}</span>
          <span className="flex-1 lg:hidden" />
          <button
            ref={menuButton}
            type="button"
            aria-expanded={open}
            aria-controls={menuId}
            onClick={() => setOpen((o) => !o)}
            className={buttonClass("secondary", "md", "lg:hidden")}
          >
            <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              {open ? <path d="M4 4l8 8M12 4l-8 8" /> : <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />}
            </svg>
            Menu
          </button>
        </div>

        <div id={menuId} className={[open ? "block" : "hidden", "max-h-[calc(100dvh-3.5rem)] overflow-y-auto border-t border-line lg:max-h-none lg:overflow-visible lg:flex lg:min-h-0 lg:flex-col lg:border-t-0"].join(" ")}>
          <nav aria-label="Console" className="px-2 py-2 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:px-2">
            {NAV_GROUPS.map((group, gi) => (
              <div key={group.label ?? "top"} className={group.label ? "mt-4" : undefined}>
                {group.label && (
                  <p id={`${menuId}-group-${gi}`} className="px-3 pb-1.5 text-2xs font-medium tracking-[0.04em] text-faint uppercase">
                    {group.label}
                  </p>
                )}
                <ul className="space-y-0.5" aria-labelledby={group.label ? `${menuId}-group-${gi}` : undefined}>
                  {SECTIONS.filter((s) => group.ids.includes(s.id) && offersSection(caps, s.id)).map((s) => {
                    const active = s.id === route.section;
                    return (
                      <li key={s.id}>
                        <a
                          href={hashOf(s.id === route.section ? route : { section: s.id, tab: route.tab })}
                          aria-current={active ? "page" : undefined}
                          onClick={(e) => {
                            // A plain click navigates here, without a history entry per section;
                            // a modified click (new tab) is left to the browser.
                            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                            e.preventDefault();
                            focusDestination.current = open;
                            setOpen(false);
                            onSection(s.id);
                          }}
                          className={[
                            "flex min-h-10 items-center pointer-coarse:min-h-11",
                            "gap-3 rounded-sm px-3 py-2 text-sm text-ink transition-colors lg:min-h-9 lg:py-1.5",
                            active ? "bg-surface-2 font-medium" : "hover:bg-surface-2",
                          ].join(" ")}
                        >
                          <SectionIcon id={s.id} active={active} />
                          <span className="min-w-0">
                            <span className="block">{s.label}</span>
                            <span className="block text-2xs text-faint lg:hidden">{s.id === "playground" ? playgroundHint(caps) : s.hint}</span>
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
            {!caps.accounts && (
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted" htmlFor="engine-mode">
                  Engine
                </label>
                <Select
                  id="engine-mode"
                  size="sm"
                  value={engineState.preference}
                  onChange={(e) => onPreference(e.target.value as ModePreference)}
                >
                  <option value="auto">Auto</option>
                  <option value="api">Live API</option>
                  <option value="mock">Demo engine</option>
                </Select>
              </div>
            )}
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
  { label: "Inspect", ids: ["playground", "logs", "vault"] },
  { label: "Set up", ids: ["projects", "connect", "policy"] },
  { label: "Measure", ids: ["evaluation"] },
];

const ICONS: Record<Section, string> = {
  overview: "M2.5 13.5h11M4.5 11V7.5M8 11V4M11.5 11V6",
  playground: "M4 3.5 2 8l2 4.5M12 3.5 14 8l-2 4.5M9.5 3 6.5 13",
  logs: "M2.5 4h11M2.5 8h11M2.5 12h7",
  vault: "M3 6.5h10v7H3zM5.5 6.5V5a2.5 2.5 0 0 1 5 0v1.5M8 9.5v1.5",
  projects: "M2 4h5l1-2h6v11H2zM5 7h6M5 10h4",
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
        className="inline-flex h-8 max-w-full min-w-0 items-center gap-2 pointer-coarse:h-11 rounded-sm text-xs whitespace-nowrap text-muted transition-colors hover:text-ink"
      >
        <span aria-hidden="true" className={["size-1.5 shrink-0 rounded-full", dot].join(" ")} />
        <span className={shown ? (tone === "down" ? "font-medium text-danger" : tone === "demo" ? "font-medium text-warn" : "") : "sr-only"}>{label}</span>
        {sub && <span className="truncate tabular-nums">{sub}</span>}
      </button>
    </div>
  );
}
