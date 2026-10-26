import { metaFor } from "../lib/entities";
import { tokenize } from "../lib/placeholders";
import { Placeholder } from "./Placeholder";

interface Props {
  text: string;
  activeKey?: string | null;
  onActivate?: (key: string | null, anchor?: HTMLElement | null) => void;
  unresolved?: readonly string[];
}

/** What the model saw: masked text, placeholders highlighted. Contains no original values. */
export function MaskedText({ text, activeKey = null, onActivate, unresolved = [] }: Props) {
  const tokens = tokenize(text);
  return (
    <div className="doc text-ink" data-testid="masked-text">
      {tokens.map((t, i) =>
        t.kind === "text" ? (
          <span key={i}>{t.text}</span>
        ) : (
          <Placeholder
            key={i}
            text={t.text}
            entityType={t.entityType}
            active={activeKey === t.text}
            unresolved={unresolved.includes(t.text)}
            onActivate={onActivate}
            description={
              unresolved.includes(t.text)
                ? undefined
                : `${metaFor(t.entityType).label} placeholder`
            }
          />
        ),
      )}
    </div>
  );
}
