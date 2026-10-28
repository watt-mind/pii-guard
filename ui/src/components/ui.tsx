import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { RunError } from "../lib/run";

type Variant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "secondary",
  className = "",
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const styles: Record<Variant, string> = {
    primary: "rounded-lg bg-primary px-3 font-normal text-on-primary hover:bg-primary-hover",
    secondary: "rounded-control border border-line bg-surface px-4 font-normal text-ink hover:border-line-strong hover:bg-surface-2",
    ghost: "rounded-lg px-3 font-normal text-muted hover:bg-surface-2 hover:text-ink",
  };
  return (
    <button
      type={type}
      className={[
        "inline-flex h-9 items-center justify-center gap-1.5 text-sm whitespace-nowrap transition-colors active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45",
        styles[variant],
        className,
      ].join(" ")}
      {...rest}
    />
  );
}

export function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex min-w-12 flex-col-reverse">
      <dt className="mt-1 text-2xs text-muted">{label}</dt>
      <dd className="font-mono text-lg leading-none tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function EmptyState({ title, body, children }: { title: string; body: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[14rem] flex-col items-center justify-center px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-xs text-sm text-muted">{body}</p>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}

/**
 * Fail closed, made visible. Outbound: the request was blocked and nothing
 * left. Inbound: the answer could not be restored, so nothing is shown.
 */
export function BlockedNotice({ error, phase = "outbound" }: { error: RunError; phase?: "outbound" | "inbound" }) {
  const unreachable = error.code === "unreachable";
  const title =
    phase === "inbound"
      ? error.code === "not_found"
        ? "This session is no longer known to the guard."
        : "The answer could not be restored."
      : unreachable
        ? "The guard is not reachable. Nothing was sent."
        : "Blocked. Nothing was sent to the model.";
  const body =
    phase === "inbound"
      ? error.code === "not_found"
        ? "Mappings live only in the guard's memory and expire. Mask the document again to start a new session."
        : "pii-guard shows nothing rather than a half-restored answer."
      : "pii-guard fails closed: if detection or masking fails, the request is stopped rather than forwarded unmasked.";
  return (
    <div role="alert" className="rounded-lg border border-blocked/40 bg-blocked-soft p-4 text-sm">
      <p className="flex items-center gap-2 font-medium text-blocked">
        <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="8" cy="8" r="6" />
          <path d="M3.8 12.2 12.2 3.8" />
        </svg>
        {title}
      </p>
      <p className="mt-1 text-ink">
        <code className="font-mono text-xs">{error.code}</code>
        {error.message && error.message !== error.code ? <> · {error.message}</> : null}
      </p>
      <p className="mt-2 text-muted">{body}</p>
    </div>
  );
}
