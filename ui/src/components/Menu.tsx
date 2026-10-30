import type { ReactNode } from "react";
import type { useMenu } from "../hooks/useMenu";

/** The dropdown card under a header button, right-aligned and never wider than the phone. */
export function MenuPanel({ menuProps, label, children }: { menuProps: ReturnType<typeof useMenu>["menuProps"]; label: string; children: ReactNode }) {
  return (
    <div
      {...menuProps}
      aria-label={label}
      className="absolute top-full right-0 z-40 mt-2 max-h-[min(70dvh,32rem)] w-72 max-w-[calc(100vw-2rem)] overflow-y-auto overscroll-contain rounded-control border border-line-strong bg-surface py-1.5 text-sm text-ink shadow-[0_12px_32px_-12px_rgb(0_0_0/0.35)]"
    >
      {children}
    </div>
  );
}

/** A non-focusable label inside a menu: names the group of items that follows it. */
export function MenuHeading({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} role="presentation" className="px-3.5 pt-2 pb-1 text-2xs font-medium tracking-[0.04em] text-faint uppercase">
      {children}
    </p>
  );
}

export const MenuSeparator = () => <div role="separator" className="my-1.5 border-t border-line" />;
