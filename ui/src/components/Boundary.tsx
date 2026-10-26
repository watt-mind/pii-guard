import type { ReactNode } from "react";

interface Props {
  /** Direction of travel across the guard: outbound (you → model) or inbound (model → you). */
  direction: "outbound" | "inbound";
  label: string;
  children?: ReactNode;
}

/** The guard boundary between two panes: vertical on desktop, horizontal on narrow screens. */
export function Boundary({ direction, label, children }: Props) {
  return (
    <div
      role="group"
      aria-label={label}
      data-direction={direction}
      className="boundary-rail relative flex items-center justify-center py-2 lg:w-28 lg:flex-col lg:py-0"
    >
      <div className="relative z-10 flex flex-col items-center gap-2 bg-canvas px-2 py-2 text-center">
        <span className="grid size-10 place-items-center rounded-full border border-guard/40 bg-guard-soft text-guard shadow-sm">
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
            <path d="M12 3 5 6v5.2c0 4.3 2.9 8 7 9.3 4.1-1.3 7-5 7-9.3V6l-7-3Z" />
            <path d="M8.8 12h6.4" strokeLinecap="round" />
          </svg>
        </span>
        <span className="text-[10px] font-semibold tracking-[0.12em] text-guard uppercase">pii-guard</span>
        <span aria-hidden="true" className="text-lg leading-none text-faint">
          <span className="lg:hidden">↓</span>
          <span className="hidden lg:inline">→</span>
        </span>
        {children}
      </div>
    </div>
  );
}
