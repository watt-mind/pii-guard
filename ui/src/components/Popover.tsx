import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface Props {
  /** The highlight under the cursor or keyboard focus; null hides the popover. */
  anchor: HTMLElement | null;
  children: ReactNode;
}

const GAP = 8;
const MARGIN = 8;
const WIDTH = 320;

/**
 * A small card anchored to the active highlight. It is decorative for screen
 * readers (aria-hidden): every highlight already carries the same details as
 * visually hidden text, read out when it receives focus.
 */
export function Popover({ anchor, children }: Props) {
  // Re-render on scroll/resize so the card follows its anchor.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!anchor) return;
    const bump = () => setTick((t) => t + 1);
    window.addEventListener("scroll", bump, true);
    window.addEventListener("resize", bump);
    return () => {
      window.removeEventListener("scroll", bump, true);
      window.removeEventListener("resize", bump);
    };
  }, [anchor]);

  if (!anchor || !anchor.isConnected || typeof document === "undefined") return null;
  const rect = anchor.getBoundingClientRect();
  const vw = window.innerWidth;
  const width = Math.min(WIDTH, vw - MARGIN * 2);
  const left = Math.min(Math.max(MARGIN, rect.left + rect.width / 2 - width / 2), vw - width - MARGIN);
  const below = rect.top < 120;
  const style = below
    ? { top: rect.bottom + GAP, left, width }
    : { top: rect.top - GAP, left, width, transform: "translateY(-100%)" };

  return createPortal(
    <div
      aria-hidden="true"
      data-testid="entity-popover"
      style={{ position: "fixed", ...style }}
      className="pointer-events-none z-50 rounded-control border border-line-strong bg-surface px-3 py-2.5 text-xs text-muted shadow-[0_8px_24px_-12px_rgb(0_0_0/0.5)]"
    >
      {children}
    </div>,
    document.body,
  );
}
