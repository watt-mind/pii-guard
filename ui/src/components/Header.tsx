import type { KeyboardEvent } from "react";
import { engineReason, type EngineDisplay, type EngineState, type ModePreference } from "../api/engine";
import type { ThemePref } from "../hooks/useTheme";

export type Screen = "playground" | "chat" | "images" | "benchmarks" | "traffic";

const SCREENS: { id: Screen; label: string; short?: string }[] = [
  { id: "playground", label: "Mask" },
  { id: "chat", label: "Chat" },
  { id: "images", label: "Images" },
  { id: "benchmarks", label: "Benchmarks" },
  { id: "traffic", label: "Live traffic", short: "Traffic" },
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
    <header className="relative z-30 border-b border-line bg-canvas md:sticky md:top-0">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:rounded focus:bg-surface focus:px-3 focus:py-1">
          Skip to content
        </a>
        <div className="flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight">
            <p className="font-mono text-sm font-semibold tracking-tight text-ink">pii-guard</p>
            <p className="hidden text-xs text-muted sm:block">privacy firewall for AI agents</p>
          </div>
        </div>

        <div role="tablist" aria-label="Demo screens" className="order-last -mb-3 flex w-full gap-1 overflow-x-auto md:order-none md:mb-0 md:w-auto md:self-stretch">
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
                  "relative flex min-w-0 flex-auto items-center justify-center px-2 py-3 text-ui font-medium whitespace-nowrap transition-colors sm:px-3 sm:text-sm md:flex-none md:py-0",
                  "after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full sm:after:inset-x-3",
                  selected ? "text-ink after:bg-ink" : "text-muted hover:text-ink after:bg-transparent",
                ].join(" ")}
              >
                {s.short ? (
                  <>
                    <span className="lg:hidden">{s.short}</span>
                    <span className="hidden lg:inline">{s.label}</span>
                  </>
                ) : (
                  s.label
                )}
              </button>
            );
          })}
        </div>

        <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
          <EngineBadge state={engineState} engine={engine} onRecheck={onRecheck} />
          <span className="flex-1 sm:hidden" />
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
  const version = status.state === "online" ? `v${status.version}` : null;
  // One indicator: what is answering right now, and the API's own state only when it differs.
  const { label, detail, tone } =
    engine === "pending"
      ? { label: "Connecting…", detail: null, tone: "pending" as const }
      : engine === "mock"
        ? { label: "Demo mode", detail: status.state === "online" ? `API ${version} idle` : "API offline", tone: "demo" as const }
        : { label: "Live API", detail: version, tone: "live" as const };
  const dot = tone === "live" ? "bg-guard" : tone === "demo" ? "bg-warn" : "bg-faint motion-safe:animate-pulse";

  return (
    <div role="status" aria-label={`${label}. ${reason}.`}>
      <button
        type="button"
        onClick={onRecheck}
        title={`${reason}. Click to check again.`}
        className={[
          "inline-flex h-8 items-center gap-2 rounded-lg border px-2.5 text-xs font-medium whitespace-nowrap transition-colors",
          tone === "demo" ? "border-warn/40 bg-warn-soft text-warn" : "border-line text-ink hover:border-line-strong",
        ].join(" ")}
      >
        <span aria-hidden="true" className={["size-1.5 rounded-full", dot].join(" ")} />
        <span>{label}</span>
        {detail && <span className="hidden font-mono text-2xs font-normal text-muted tabular-nums sm:inline">{detail}</span>}
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
    <span className="grid size-8 place-items-center rounded-lg bg-ink text-canvas dark:bg-guard-soft dark:text-guard dark:ring-1 dark:ring-guard/30">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round">
        <path d="M12 3 5 6v5.2c0 4.3 2.9 8 7 9.3 4.1-1.3 7-5 7-9.3V6l-7-3Z" />
        <path d="M8.6 12h6.8" strokeLinecap="round" />
      </svg>
    </span>
  );
}
