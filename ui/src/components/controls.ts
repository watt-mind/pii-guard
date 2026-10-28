/** Class names for the canonical controls (ui.tsx), for elements that are not a <button>:
 * a <summary>, a file-input <label>. ui/DESIGN.md, "Components". */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ControlSize = "sm" | "md";

export const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-normal whitespace-nowrap transition-colors active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:cursor-progress aria-disabled:opacity-60";
export const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-primary-hover",
  secondary: "border border-line-strong bg-surface text-ink hover:border-field hover:bg-surface-2",
  ghost: "text-muted hover:bg-surface-2 hover:text-ink",
  danger: "border border-danger/60 bg-surface text-danger hover:border-danger hover:bg-danger-soft",
};
/** Heights: sm 32 px, md 36 px; both 44 px on a coarse pointer (a phone or tablet). */
export const BUTTON_SIZE: Record<ControlSize, string> = {
  sm: "h-8 px-2.5 pointer-coarse:h-11",
  md: "h-9 px-3.5 pointer-coarse:h-11",
};

export function buttonClass(variant: ButtonVariant = "secondary", size: ControlSize = "md", className = ""): string {
  return [BUTTON_BASE, BUTTON_VARIANT[variant], BUTTON_SIZE[size], className].filter(Boolean).join(" ");
}


/** Inputs, selects and text areas: one height, radius, `--field` outline and neutral focus. */
export const CONTROL_BASE =
  "w-full min-w-0 rounded-lg border border-field bg-surface text-ink transition-colors placeholder:text-faint hover:border-ink/60 disabled:cursor-not-allowed disabled:opacity-55 aria-invalid:border-danger read-only:bg-surface-2";
export const CONTROL_SIZE: Record<ControlSize, string> = {
  sm: "h-8 px-2.5 text-xs pointer-coarse:h-11 pointer-coarse:text-sm",
  md: "h-9 px-3 text-sm pointer-coarse:h-11",
};


export function controlClass(size: ControlSize = "md", className = ""): string {
  return [CONTROL_BASE, CONTROL_SIZE[size], className].filter(Boolean).join(" ");
}
