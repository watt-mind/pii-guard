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
    primary: "bg-ink text-canvas hover:opacity-90 shadow-sm",
    secondary: "border border-line bg-surface text-ink hover:border-line-strong",
    ghost: "text-muted hover:bg-surface-2 hover:text-ink",
  };
  return (
    <button
      type={type}
      className={[
        "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3.5 text-sm font-medium whitespace-nowrap transition disabled:cursor-not-allowed disabled:opacity-45",
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
      <dt className="mt-0.5 text-[10px] tracking-wide text-faint uppercase">{label}</dt>
      <dd className="text-lg leading-none font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}

export function EmptyState({ title, body, children }: { title: string; body: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-[14rem] flex-col items-center justify-center rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
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
    <div role="alert" className="rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm">
      <p className="font-semibold text-danger">{title}</p>
      <p className="mt-1 text-ink">
        <code className="font-mono text-xs">{error.code}</code>
        {error.message && error.message !== error.code ? <> · {error.message}</> : null}
      </p>
      <p className="mt-2 text-muted">{body}</p>
    </div>
  );
}
