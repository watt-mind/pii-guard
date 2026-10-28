import type { ReactNode } from "react";

export type Side = "you" | "model";

interface Props {
  side: Side;
  eyebrow: string;
  title: string;
  id?: string;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Cap the body's height and scroll it (Logs' request and response panes). */
  scroll?: boolean;
}

/** A document pane. `side` says which side of the guard boundary its content lives on. */
export function Pane({ side, eyebrow, title, id, actions, footer, children, className = "", scroll = false }: Props) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      aria-labelledby={headingId}
      data-side={side}
      className={[
        "flex min-w-0 flex-col overflow-hidden rounded-xl border bg-surface",
        side === "model" ? "border-model/25" : "border-line",
        className,
      ].join(" ")}
    >
      <header
        className={[
          "flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3 sm:px-5",
          side === "model" ? "border-model/20 bg-model-soft/60" : "border-line bg-surface-2",
        ].join(" ")}
      >
        <div className="min-w-[11rem] flex-1">
          <p
            className={[
              "flex items-center gap-1.5 font-mono text-2xs",
              side === "model" ? "text-model" : "text-guard",
            ].join(" ")}
          >
            <SideIcon side={side} />
            {eyebrow}
          </p>
          <h2 id={headingId} className="mt-0.5 text-lg font-normal text-balance text-ink">
            {title}
          </h2>
        </div>
        {actions && <div className="flex min-w-0 flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={["min-h-0 flex-1 px-4 py-4 sm:px-5", scroll ? "max-h-[32rem] overflow-y-auto" : ""].join(" ")}>{children}</div>
      {footer && <footer className="border-t border-line px-4 py-2.5 text-xs text-muted sm:px-5">{footer}</footer>}
    </section>
  );
}

function SideIcon({ side }: { side: Side }) {
  return side === "you" ? (
    <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  ) : (
    <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4.5 12.5h7a3 3 0 0 0 .4-6 4 4 0 0 0-7.7.9A2.6 2.6 0 0 0 4.5 12.5Z" />
    </svg>
  );
}
