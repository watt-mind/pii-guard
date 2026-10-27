import type { KeyboardEvent } from "react";
import { engineReason, type EngineDisplay, type EngineState, type ModePreference } from "../api/engine";
import type { ThemePref } from "../hooks/useTheme";

export type Screen = "playground" | "roundtrip" | "images" | "benchmarks";

const SCREENS: { id: Screen; step: string; label: string }[] = [
  { id: "playground", step: "1", label: "Playground" },
  { id: "roundtrip", step: "2", label: "Round trip" },
  { id: "images", step: "3", label: "Images" },
  { id: "benchmarks", step: "4", label: "Benchmarks" },
];

interface Props {
  screen: Screen;
  onScreen: (s: Screen) => void;
  engineState: EngineState;
  engine: EngineDisplay;
  onPreference: (p: ModePreference) => void;
  onRecheck: () => void;
  theme: ThemePref;
  onTheme: (t: ThemePref) => void;
}

export function Header({ screen, onScreen, engineState, engine, onPreference, onRecheck, theme, onTheme }: Props) {
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = SCREENS.findIndex((s) => s.id === screen);
    const next = SCREENS[(i + (e.key === "ArrowRight" ? 1 : SCREENS.length - 1)) % SCREENS.length]!;
    onScreen(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  };

  return (
    <header className="relative z-30 border-b md:sticky md:top-0 border-line bg-canvas/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
          Skip to content
        </a>
        <div className="flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight">
            <p className="text-[15px] font-semibold tracking-tight text-ink">pii-guard</p>
            <p className="hidden text-xs text-muted sm:block">privacy firewall for AI agents</p>
          </div>
        </div>

        <div role="tablist" aria-label="Demo screens" className="order-last flex w-full gap-1 rounded-xl bg-surface-2 p-1 ring-1 ring-line md:order-none md:w-auto">
          {SCREENS.map((s) => {
            const selected = s.id === screen;
            return (
              <button
                key={s.id}
                id={`tab-${s.id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`panel-${s.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => onScreen(s.id)}
                onKeyDown={onTabKey}
                className={[
                  "flex min-w-0 flex-1 items-center justify-center gap-2 rounded-lg px-1.5 py-2.5 text-[13px] font-medium whitespace-nowrap transition-colors sm:px-3.5 sm:py-1.5 sm:text-sm md:flex-none",
                  selected ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-muted hover:text-ink",
                ].join(" ")}
              >
                <span
                  aria-hidden="true"
                  className={[
                    "hidden size-5 place-items-center rounded-full text-[11px] font-semibold tabular-nums sm:grid",
                    selected ? "bg-ink text-canvas" : "bg-line text-muted",
                  ].join(" ")}
                >
                  {s.step}
                </span>
                {s.label}
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <EngineBadge state={engineState} engine={engine} onRecheck={onRecheck} />
          <label className="sr-only" htmlFor="engine-mode">
            Engine
          </label>
          <select
            id="engine-mode"
            value={engineState.preference}
            onChange={(e) => onPreference(e.target.value as ModePreference)}
            className="h-8 rounded-lg border border-line bg-surface px-2 text-xs font-medium text-ink"
          >
            <option value="auto">Auto</option>
            <option value="api">Live API</option>
            <option value="mock">Demo engine</option>
          </select>
          <ThemeToggle theme={theme} onTheme={onTheme} />
        </div>
      </div>
    </header>
  );
}

function EngineBadge({ state, engine, onRecheck }: { state: EngineState; engine: EngineDisplay; onRecheck: () => void }) {
  const reason = engineReason(state);
  const status = state.status;
  const apiLabel =
    status.state === "online" ? `API v${status.version}` : status.state === "checking" ? "API …" : "API offline";
  const dot =
    status.state === "online" ? "bg-guard" : status.state === "checking" ? "bg-faint animate-pulse" : "bg-danger";

  return (
    <div className="flex items-center gap-2" role="status" aria-label={`${engine === "mock" ? "Demo engine" : engine === "pending" ? "Connecting" : "Live API"}. ${reason}.`}>
      <button
        type="button"
        onClick={onRecheck}
        title={`${reason}. Click to check again.`}
        className="hidden items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-surface-2 sm:inline-flex"
      >
        <span aria-hidden="true" className={["size-2 rounded-full", dot].join(" ")} />
        <span className="tabular-nums">{apiLabel}</span>
      </button>
      {engine === "pending" ? (
        <span
          title={reason}
          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-xs font-semibold text-muted"
        >
          <span aria-hidden="true" className="size-1.5 rounded-full bg-faint motion-safe:animate-pulse" />
          Connecting…
        </span>
      ) : engine === "mock" ? (
        <span
          title={reason}
          className="inline-flex items-center gap-1.5 rounded-full border border-warn/40 bg-warn-soft px-2.5 py-1 text-xs font-semibold text-warn"
        >
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="currentColor">
            <path d="M8 1.5 15 14H1L8 1.5Zm0 4a.75.75 0 0 0-.75.75v3.5a.75.75 0 0 0 1.5 0v-3.5A.75.75 0 0 0 8 5.5Zm0 7.25a.9.9 0 1 0 0-1.8.9.9 0 0 0 0 1.8Z" />
          </svg>
          Demo mode
        </span>
      ) : (
        <span
          title={reason}
          className="inline-flex items-center gap-1.5 rounded-full border border-guard/40 bg-guard-soft px-2.5 py-1 text-xs font-semibold text-guard-ink"
        >
          <span aria-hidden="true" className="size-1.5 rounded-full bg-guard" />
          Live
        </span>
      )}
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
    <div role="group" aria-label="Theme" className="flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={theme === o.id}
          aria-label={o.label}
          title={o.label}
          onClick={() => onTheme(o.id)}
          className={[
            "grid size-7 place-items-center rounded-md transition-colors",
            theme === o.id ? "bg-ink text-canvas" : "text-muted hover:text-ink",
          ].join(" ")}
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
    <span className="grid size-9 place-items-center rounded-[10px] bg-[#14161a] text-[#b6f36b] ring-1 ring-black/10 dark:ring-white/10">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round">
        <path d="M12 3 5 6v5.2c0 4.3 2.9 8 7 9.3 4.1-1.3 7-5 7-9.3V6l-7-3Z" />
        <path d="M8.6 12h6.8" strokeLinecap="round" />
      </svg>
    </span>
  );
}
