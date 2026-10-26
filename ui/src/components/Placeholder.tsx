import type { EntityType } from "../api/types";
import { metaFor } from "../lib/entities";

interface Props {
  text: string;
  entityType: EntityType | null;
  active?: boolean;
  /** The token isn't in the session mapping (the model invented or mangled it). */
  unresolved?: boolean;
  onActivate?: (key: string | null, anchor?: HTMLElement | null) => void;
  description?: string;
  className?: string;
}

/** A placeholder exactly as the model sees it, e.g. [[PERSON_7f3a]], colour-coded by type. */
export function Placeholder({ text, entityType, active, unresolved, onActivate, description, className = "" }: Props) {
  const meta = metaFor(entityType);
  const m = /^\[\[(.+)_([0-9a-f]+)\]\]$/.exec(text);
  const type = m?.[1] ?? text;
  const id = m?.[2] ?? "";
  const label =
    description ??
    (unresolved
      ? "unknown placeholder, not restored"
      : `${meta.label} placeholder`);
  return (
    <span
      tabIndex={onActivate ? 0 : undefined}
      data-placeholder={text}
      data-active={active || undefined}
      onMouseEnter={onActivate ? (e) => onActivate(text, e.currentTarget) : undefined}
      onMouseLeave={onActivate ? () => onActivate(null) : undefined}
      onFocus={onActivate ? (e) => onActivate(text, e.currentTarget) : undefined}
      onBlur={onActivate ? () => onActivate(null) : undefined}
      className={[
        "inline rounded-md px-1 py-px ring-1 ring-inset font-mono font-medium whitespace-nowrap box-decoration-clone",
        unresolved
          ? "bg-danger-soft text-danger ring-danger/60 line-through decoration-2"
          : meta.chip,
        onActivate ? "cursor-help" : "",
        active ? "ring-2 shadow-[0_0_0_3px_var(--canvas),0_0_0_5px_currentColor]" : "",
        className,
      ].join(" ")}
    >
      <span className="opacity-45">[[</span>
      <span>{type}</span>
      <span className="opacity-60">_{id}</span>
      <span className="opacity-45">]]</span>
      <span className="sr-only"> ({label})</span>
    </span>
  );
}
