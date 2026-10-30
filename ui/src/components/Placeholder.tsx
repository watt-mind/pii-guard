import type { EntityType } from "../api/types";
import { metaFor } from "../lib/entities";
import { activationHandlers, type ActivateHandler } from "../lib/placeholders";

interface Props {
  text: string;
  entityType: EntityType | null;
  active?: boolean;
  /** The token isn't in the session mapping (the model invented or mangled it). */
  unresolved?: boolean;
  onActivate?: ActivateHandler;
  description?: string;
  className?: string;
}

function parsePlaceholderParts(text: string): { type: string; id: string } {
  const m = /^\[\[(.+)_([0-9a-f]+)\]\]$/.exec(text);
  return { type: m?.[1] ?? text, id: m?.[2] ?? "" };
}

function placeholderLabel(description: string | undefined, unresolved: boolean | undefined, metaLabel: string): string {
  if (description) return description;
  return unresolved ? "unknown placeholder, not restored" : `${metaLabel} placeholder`;
}

/** A placeholder exactly as the model sees it, e.g. [[PERSON_7f3a]], colour-coded by type. */
export function Placeholder({ text, entityType, active, unresolved, onActivate, description, className = "" }: Props) {
  const meta = metaFor(entityType);
  const { type, id } = parsePlaceholderParts(text);
  const label = placeholderLabel(description, unresolved, meta.label);
  const chipStyle = unresolved ? "bg-danger-soft text-danger ring-danger/60 line-through decoration-2" : meta.chip;
  return (
    <span
      data-placeholder={text}
      data-active={active || undefined}
      {...activationHandlers(text, onActivate)}
      className={[
        "inline rounded-md px-1 py-px ring-1 ring-inset font-mono font-medium whitespace-nowrap box-decoration-clone",
        chipStyle,
        onActivate ? "cursor-help" : "",
        active ? "ring-2 outline-2 outline-offset-2 outline-current" : "",
        className,
      ].join(" ")}
    >
      <span className="opacity-45">[[</span>
      <span>{type}</span>
      <span>_{id}</span>
      <span className="opacity-45">]]</span>
      <span className="sr-only"> ({label})</span>
    </span>
  );
}
