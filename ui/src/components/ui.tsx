import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type Ref,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import type { ThemePref } from "../hooks/useTheme";
import { errorCopy, statusFromMessage } from "../lib/errorCopy";
import type { RunError } from "../lib/run";
import { CONTROL_BASE, CONTROL_SIZE, buttonClass, type ButtonVariant, type ControlSize } from "./controls";

export type { ButtonVariant, ControlSize };

/*
 * The console's canonical components (ui/DESIGN.md, "Components"). Every screen builds its
 * controls from these; `className` is for layout only (width, margin, flex), never for colour,
 * height or radius, because there is no class merging and the base classes would win.
 */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ControlSize;
  /** Running: the button stays focusable (no `disabled`), says so, and ignores clicks. */
  busy?: boolean;
  ref?: Ref<HTMLButtonElement>;
};

export function Button({ variant = "secondary", size = "md", busy = false, className = "", type = "button", onClick, ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      aria-disabled={busy || undefined}
      aria-busy={busy || undefined}
      className={buttonClass(variant, size, className)}
      onClick={(e) => {
        if (busy) {
          e.preventDefault();
          return;
        }
        onClick?.(e);
      }}
      {...rest}
    />
  );
}

/** A link styled as a button (navigation, not an action). */
export function ButtonLink({ variant = "secondary", size = "md", className = "", ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant; size?: ControlSize }) {
  return <a className={buttonClass(variant, size, `no-underline ${className}`)} {...rest} />;
}

/* ---------- Form fields ---------- */

interface FieldState {
  id: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
}
const FieldContext = createContext<FieldState | null>(null);

/**
 * A label, its control, an optional hint (the control's description, not part of its name)
 * and an error slot. Required fields are marked; the control picks up id, aria-describedby,
 * aria-invalid and required from the Field.
 */
export function Field({
  label,
  hint,
  error,
  required = false,
  className = "",
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <FieldContext.Provider value={{ id, describedBy, invalid: Boolean(error), required }}>
      <div className={["grid content-start gap-1.5", className].join(" ")}>
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
          {required && (
            <span aria-hidden="true" className="ml-0.5 text-danger">
              *
            </span>
          )}
        </label>
        {children}
        {hint && (
          <p id={hintId} className="text-xs text-muted">
            {hint}
          </p>
        )}
        {error && (
          <p id={errorId} className="text-xs text-danger">
            {error}
          </p>
        )}
      </div>
    </FieldContext.Provider>
  );
}

function useFieldProps(props: { id?: string; required?: boolean; "aria-describedby"?: string; "aria-invalid"?: boolean | "true" | "false" | "grammar" | "spelling" }) {
  const field = useContext(FieldContext);
  return {
    id: props.id ?? field?.id,
    required: props.required ?? (field?.required || undefined),
    "aria-describedby": props["aria-describedby"] ?? field?.describedBy,
    "aria-invalid": props["aria-invalid"] ?? (field?.invalid || undefined),
  };
}

export function Input({ size = "md", className = "", ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, "size"> & { size?: ControlSize; ref?: Ref<HTMLInputElement> }) {
  const field = useFieldProps(rest);
  return <input {...rest} {...field} className={[CONTROL_BASE, CONTROL_SIZE[size], "read-only:bg-surface-2", className].join(" ")} />;
}

export function Select({ size = "md", className = "", ...rest }: Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> & { size?: ControlSize; ref?: Ref<HTMLSelectElement> }) {
  const field = useFieldProps(rest);
  // One chevron (ours, not the browser's), so the room it takes is reserved once: pr-8.
  return <select {...rest} {...field} className={[CONTROL_BASE, CONTROL_SIZE[size], "select-chevron pr-8", className].join(" ")} />;
}

export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { ref?: Ref<HTMLTextAreaElement> }) {
  const field = useFieldProps(rest);
  return <textarea {...rest} {...field} className={[CONTROL_BASE, "min-h-36 resize-y bg-surface-2 px-3 py-2 font-mono text-ui", className].join(" ")} />;
}

/** One checkbox style: 16 px, the primary as its accent, the label beside it. */
export function Checkbox({ label, hint, className = "", ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className={["flex items-start gap-2.5", className].join(" ")}>
      <input
        id={id}
        type="checkbox"
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="mt-0.5 size-4 shrink-0 accent-[var(--primary)] disabled:cursor-not-allowed pointer-coarse:mt-0 pointer-coarse:size-5"
        {...rest}
      />
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm text-ink">
          {label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}

/* ---------- Segmented control ---------- */

export interface Segment<T extends string> {
  value: T;
  label: ReactNode;
  /** The accessible name when the label is only an icon. */
  ariaLabel?: string;
  title?: string;
  disabled?: boolean;
}

/**
 * A single choice among a few options, built on native radios: one tab stop, arrow keys move
 * the choice, and screen readers announce "radio, 2 of 3". The selected segment is neutral
 * (a raised surface), so it never reads as the primary action.
 */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  size = "md",
  name,
  square = false,
  className = "",
}: {
  /** Icon-only segments: square, so a row of icons stays compact. */
  square?: boolean;
  /** The group's accessible name ("Theme", "Chat mode"). */
  label: string;
  options: readonly Segment<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: ControlSize;
  name?: string;
  className?: string;
}) {
  const auto = useId();
  const group = name ?? auto;
  return (
    <div role="radiogroup" aria-label={label} className={["inline-flex max-w-full rounded-lg border border-line bg-surface-2 p-0.5", className].join(" ")}>
      {options.map((o) => (
        <label
          key={o.value}
          title={o.title}
          className={[
            "relative inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-md whitespace-nowrap text-muted transition-colors select-none",
            "hover:text-ink has-[:checked]:bg-surface has-[:checked]:text-ink has-[:checked]:shadow-[0_0_0_1px_var(--line-strong)]",
            "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--focus)]",
            "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45",
            square
              ? size === "sm"
                ? "size-7 pointer-coarse:size-10"
                : "size-8 pointer-coarse:size-10"
              : size === "sm"
                ? "h-7 px-2.5 text-xs pointer-coarse:h-10"
                : "h-8 px-3 text-sm pointer-coarse:h-10",
          ].join(" ")}
        >
          <input
            type="radio"
            name={group}
            value={o.value}
            checked={value === o.value}
            disabled={o.disabled}
            aria-label={o.ariaLabel}
            onChange={() => onChange(o.value)}
            className="sr-only"
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/* ---------- Brand ---------- */

/** The product mark: a 24 px shield glyph, no tile (ui/DESIGN.md, "Brand row"). Console and landing. */
export function Logo() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6 shrink-0 text-ink" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
      <path d="M12 3 5 6v5.2c0 4.3 2.9 8 7 9.3 4.1-1.3 7-5 7-9.3V6l-7-3Z" />
      <path d="M8.6 12h6.8" strokeLinecap="round" />
    </svg>
  );
}

/** Light, system or dark: three square icon segments. The sidebar footer and the landing footer. */
export function ThemeToggle({ theme, onTheme }: { theme: ThemePref; onTheme: (t: ThemePref) => void }) {
  const options: { id: ThemePref; label: string; icon: string }[] = [
    { id: "light", label: "Light theme", icon: "M8 3.5V2m0 12v-1.5M3.5 8H2m12 0h-1.5M4.8 4.8 3.8 3.8m8.4 8.4-1-1m0-6.4 1-1M3.8 12.2l1-1M10.5 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" },
    { id: "system", label: "System theme", icon: "M2.5 3.5h11v7h-11zM6 13.5h4M8 10.5v3" },
    { id: "dark", label: "Dark theme", icon: "M13 9.6A5.5 5.5 0 0 1 6.4 3a5.5 5.5 0 1 0 6.6 6.6Z" },
  ];
  return (
    <SegmentedControl
      label="Theme"
      size="sm"
      square
      className="shrink-0"
      value={theme}
      onChange={onTheme}
      options={options.map((o) => ({
        value: o.id,
        ariaLabel: o.label,
        title: o.label,
        label: (
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d={o.icon} />
          </svg>
        ),
      }))}
    />
  );
}

/* ---------- Badge ---------- */

export type BadgeTone = "neutral" | "live" | "failed";
const BADGE_TONE: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 text-muted ring-line-strong",
  live: "bg-guard-soft text-guard ring-guard/30",
  failed: "bg-danger-soft text-danger ring-danger/35",
};

/** A short status label: 6 px radius, 11/500 (ui/DESIGN.md, "Type"). `live` and `failed` are states; neutral is not. */
export function Badge({ tone = "neutral", children, className = "" }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return <span className={["inline-flex w-fit items-center rounded-md px-2 py-0.5 text-2xs font-medium ring-1 ring-inset", BADGE_TONE[tone], className].join(" ")}>{children}</span>;
}

/* ---------- Confirmation ---------- */

/**
 * A destructive action in two steps. The trigger opens an inline confirmation that names the
 * object and the consequence; the danger button takes focus. Cancel and Escape return focus to
 * the trigger. After a confirmed action the caller announces the result and moves focus.
 */
export function ConfirmAction({
  trigger,
  triggerLabel,
  title,
  body,
  confirm,
  cancel = "Cancel",
  onConfirm,
  busy = false,
  disabled = false,
  size = "md",
  triggerVariant = "secondary",
  className = "",
}: {
  /** The trigger's visible text ("Revoke"). */
  trigger: ReactNode;
  /** The trigger's accessible name when the visible text is ambiguous ("Revoke key production"). */
  triggerLabel?: string;
  /** The question, naming the object ("Revoke key 'production'?"). */
  title: ReactNode;
  /** The consequence ("Apps using it stop working."). */
  body?: ReactNode;
  /** The danger button's text ("Revoke key"). */
  confirm: ReactNode;
  cancel?: ReactNode;
  onConfirm: () => Promise<void> | void;
  busy?: boolean;
  disabled?: boolean;
  size?: ControlSize;
  triggerVariant?: ButtonVariant;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) confirmRef.current?.focus();
    else if (wasOpen.current) triggerRef.current?.focus();
    wasOpen.current = open;
  }, [open]);
  if (!open)
    return (
      <Button ref={triggerRef} variant={triggerVariant} size={size} disabled={disabled} aria-label={triggerLabel} className={className} onClick={() => setOpen(true)}>
        {trigger}
      </Button>
    );
  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className={["w-full rounded-lg border border-danger/40 bg-danger-soft p-3 sm:p-4", className].join(" ")}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <p id={titleId} className="text-sm font-medium text-ink">
        {title}
      </p>
      {body && <p className="mt-1 text-sm text-muted">{body}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          ref={confirmRef}
          variant="danger"
          size={size}
          busy={busy}
          onClick={async () => {
            await onConfirm();
          }}
        >
          {busy ? "Working…" : confirm}
        </Button>
        <Button variant="ghost" size={size} disabled={busy} onClick={() => setOpen(false)}>
          {cancel}
        </Button>
      </div>
    </div>
  );
}

/* ---------- Notices ---------- */

export type NoticeTone = "info" | "warn" | "danger" | "success";
const NOTICE_TONE: Record<NoticeTone, { box: string; title: string }> = {
  info: { box: "border-line bg-surface-2", title: "text-ink" },
  warn: { box: "border-warn/35 bg-warn-soft", title: "text-warn" },
  danger: { box: "border-danger/35 bg-danger-soft", title: "text-danger" },
  success: { box: "border-guard/30 bg-guard-soft", title: "text-guard" },
};

/**
 * A message box. `live` makes it a live region: `status` (polite) for info and success,
 * `alert` for warnings and errors. A live notice should stay mounted and change its text, or
 * mount with its message, so screen readers announce it.
 */
export function Notice({
  tone = "info",
  title,
  children,
  action,
  live = false,
  className = "",
  ref,
  ...rest
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  live?: boolean;
  className?: string;
  ref?: Ref<HTMLDivElement>;
  "data-error-kind"?: string;
  id?: string;
  tabIndex?: number;
}) {
  const t = NOTICE_TONE[tone];
  const role = live ? (tone === "danger" || tone === "warn" ? "alert" : "status") : undefined;
  return (
    <div ref={ref} role={role} className={["rounded-lg border p-3 text-sm sm:p-4", t.box, className].join(" ")} {...rest}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        {/* The message keeps at least 16 rem: on a phone the action wraps below it rather than squeezing it. */}
        <div className="min-w-0 flex-[1_1_16rem]">
          {title && <p className={["font-medium", t.title].join(" ")}>{title}</p>}
          {children && <div className={[title ? "mt-1" : "", "text-ink [&_p+p]:mt-1"].join(" ")}>{children}</div>}
        </div>
        {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
      </div>
    </div>
  );
}

/** A polite live region that stays mounted; set its text to announce a result. */
export function Announcer({ message, className = "sr-only" }: { message: string; className?: string }) {
  return (
    <p role="status" aria-live="polite" className={className}>
      {message}
    </p>
  );
}

/* ---------- Copy-once secret ---------- */

/**
 * A secret shown once (an endpoint key). It is announced and takes focus on its Copy button;
 * "Copied" shows on the button itself; dismissing an uncopied secret asks first.
 */
export function SecretReveal({
  label,
  secret,
  onDismiss,
  envName,
}: {
  /** What the secret is ("Endpoint key production"). */
  label: string;
  secret: string;
  onDismiss: () => void;
  /** The variable the snippet reads it from. */
  envName?: string;
}) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");
  const [asking, setAsking] = useState(false);
  const copyRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    copyRef.current?.focus();
  }, []);
  const copy = () =>
    void navigator.clipboard
      .writeText(secret)
      .then(() => setCopied("yes"))
      .catch(() => setCopied("failed"));
  return (
    <div role="alert" aria-labelledby={titleId} className="rounded-lg border border-warn/40 bg-warn-soft p-3 sm:p-4">
      <p id={titleId} className="text-sm font-medium text-warn">
        Copy {label} now. It is shown only once.
      </p>
      <p className="mt-1 text-sm text-ink">
        PII Guard keeps only a hash, so this value can't be shown again.{envName && <> Store it as <code className="font-mono text-xs">{envName}</code>.</>}
      </p>
      <code className="mt-3 block rounded-md border border-line bg-surface px-3 py-2 font-mono text-xs break-all text-ink select-all">{secret}</code>
      {copied === "failed" && <p className="mt-2 text-xs text-danger">Copy failed. Select the key and copy it manually.</p>}
      {asking ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <p className="w-full text-sm text-ink">You haven't copied this key. Dismiss it anyway?</p>
          <Button variant="danger" onClick={onDismiss}>
            I've stored it, dismiss
          </Button>
          <Button variant="ghost" onClick={() => setAsking(false)}>
            Keep showing
          </Button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button ref={copyRef} variant="primary" onClick={copy} aria-label={copied === "yes" ? `${label} copied` : `Copy ${label}`}>
            {copied === "yes" ? "Copied" : "Copy key"}
          </Button>
          <Button variant="ghost" onClick={() => (copied === "yes" ? onDismiss() : setAsking(true))}>
            Dismiss key
          </Button>
        </div>
      )}
    </div>
  );
}

/* ---------- Data display ---------- */

/** One number with its label: value 18/500 tabular, label 12 px muted. Use inside a `<dl>`. */
export function Metric({ label, value, suffix, hint, className = "" }: { label: ReactNode; value: ReactNode; suffix?: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={["min-w-0", className].join(" ")}>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-medium text-ink tabular-nums">
        {value}
        {suffix && <span className="ml-1 text-sm font-normal text-muted">{suffix}</span>}
      </dd>
      {hint && <dd className="mt-0.5 text-xs text-muted">{hint}</dd>}
    </div>
  );
}

/** @deprecated name kept for the screens that list counts in a row; renders a Metric. */
export function Stat({ label, value }: { label: string; value: number | string }) {
  return <Metric label={label} value={value} className="min-w-12" />;
}

/** Label/value rows with one fixed label column, so neighbouring cards line up. */
export function KeyValues({ items, className = "" }: { items: readonly { label: ReactNode; value: ReactNode; key?: string }[]; className?: string }) {
  return (
    <dl className={["grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-y-2", className].join(" ")}>
      {items.map((item, i) => (
        <div key={item.key ?? i} className="contents">
          <dt className="text-muted max-sm:mt-2 max-sm:first:mt-0">{item.label}</dt>
          <dd className="min-w-0 break-words text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The one page heading: the section name as the h1 and a lead sentence. */
export function PageHeader({ title, lead, actions, id, children }: { title: ReactNode; lead?: ReactNode; actions?: ReactNode; id?: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-[20rem]">
        <h1 id={id} className="text-2xl font-medium text-balance text-ink">
          {title}
        </h1>
        {lead && <p className="mt-2 max-w-3xl text-sm text-pretty text-muted sm:text-base">{lead}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A card: 20 px radius, 16/20 px inset, an 18/400 title and a 14 px muted subtitle. */
export function Card({
  title,
  subtitle,
  actions,
  titleId,
  as: As = "section",
  className = "",
  children,
  headingLevel = 2,
  ref,
  tabIndex,
  "aria-label": ariaLabel,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  titleId?: string;
  as?: "section" | "div" | "form";
  className?: string;
  children?: ReactNode;
  headingLevel?: 2 | 3;
  ref?: Ref<HTMLElement>;
  tabIndex?: number;
  "aria-label"?: string;
}) {
  const H = headingLevel === 2 ? "h2" : "h3";
  const Tag = As as "section";
  return (
    <Tag
      ref={ref as Ref<HTMLElement>}
      tabIndex={tabIndex}
      aria-labelledby={title && titleId && !ariaLabel ? titleId : undefined}
      aria-label={ariaLabel}
      className={["rounded-xl border border-line bg-surface p-4 sm:p-5", className].join(" ")}
    >
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="min-w-0 flex-1 basis-[14rem]">
            {title && (
              <H id={titleId} tabIndex={-1} className="text-lg font-normal text-balance text-ink focus:outline-none">
                {title}
              </H>
            )}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
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
 * Fail closed, made visible. Outbound: why the request stopped, by error code (an upstream
 * refusal says the masked request did reach the upstream). Inbound: the answer could not be
 * restored, so nothing is shown. The hosted console never prints server text, which could echo
 * input; it shows the code and the mapped copy only.
 */
export function BlockedNotice({ error, phase = "outbound", onRetry }: { error: RunError; phase?: "outbound" | "inbound"; onRetry?: () => void }) {
  // Outbound copy depends on the code: an upstream refusal is not pii-guard failing closed (LAB-1335).
  const copy = errorCopy(error.code, error.status ?? statusFromMessage(error.message));
  const title =
    phase === "inbound"
      ? error.code === "not_found"
        ? "This session is no longer known to the guard."
        : "The answer could not be restored."
      : copy.title;
  const body =
    phase === "inbound"
      ? error.code === "not_found"
        ? "Mappings live only in the guard's memory and expire. Mask the document again to start a new session."
        : "PII Guard shows nothing rather than a half-restored answer."
      : copy.body;
  const showMessage = import.meta.env.VITE_PII_GUARD_HOSTED !== "true" && error.message && error.message !== error.code;
  return (
    <div role="alert" data-error-kind={phase === "inbound" ? "inbound" : copy.kind} className="rounded-lg border border-blocked/40 bg-blocked-soft p-3 text-sm sm:p-4">
      <p className="flex items-center gap-2 font-medium text-blocked">
        <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="8" cy="8" r="6" />
          <path d="M3.8 12.2 12.2 3.8" />
        </svg>
        {title}
      </p>
      <p className="mt-1 text-ink">
        <code className="font-mono text-xs">{error.code}</code>
        {showMessage ? <> · {error.message}</> : null}
      </p>
      <p className="mt-2 text-muted">{body}</p>
      {onRetry && (
        <Button size="sm" className="mt-3" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
