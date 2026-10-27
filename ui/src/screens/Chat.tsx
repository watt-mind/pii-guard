import { useEffect, useRef, useState, type ReactNode } from "react";
import { DEFAULT_CHAT_MODEL, SYSTEM_PROMPT, type ChatClient, type ChatMessage, type ChatMode } from "../api/chat";
import { MaskedText } from "../components/MaskedText";
import { Popover } from "../components/Popover";
import { RestoredText } from "../components/RestoredText";
import { BlockedNotice, Button } from "../components/ui";
import { CHAT_SAMPLES } from "../content/chatSamples";
import { metaFor } from "../lib/entities";
import { alignLoose, alignRestored, tokenize, type RestoredSegment } from "../lib/placeholders";
import { toRunError, type RunError } from "../lib/run";

export interface ChatDraft {
  text: string;
  language: "hu" | "en";
  /** Changes every time a new draft is handed over, so the same text can be sent twice. */
  nonce: number;
}

interface Turn {
  id: number;
  user: string;
  mode: ChatMode;
  status: "masking" | "streaming" | "done" | "error";
  thinking: boolean;
  maskedUser: string | null;
  maskedSystem: string | null;
  answer: string;
  maskedAnswer: string | null;
  masked: number | null;
  ms: number | null;
  error: RunError | null;
}

interface Props {
  client: ChatClient;
  /** The live API is up but no upstream may be configured; shown as a hint only. */
  live: boolean;
  draft: ChatDraft | null;
  replay: ReactNode;
}

const MODES: { id: ChatMode; label: string; hint: string }[] = [
  {
    id: "fast",
    label: "Fast",
    hint: "The default and the production path. Rules + the on-device NER: finds names, addresses and structured data in milliseconds, with no model call; nothing leaves the machine. Without a NER checkpoint on the server it runs the rules alone.",
  },
  {
    id: "audit",
    label: "Audit",
    hint: "Fast mode plus a second opinion from a remote LLM detector (Muse Spark Open on Baseten), for spot-checking quality on fictional or sample data. It sends your unmasked text, personal data included, to that detector, adds about 2 s per message and costs about $2.5–3 per 1,000. Needs a detector key on the server. Use Fast for production traffic.",
  },
];

export function Chat({ client, live, draft, replay }: Props) {
  const [view, setView] = useState<"chat" | "replay">("chat");
  const [mode, setMode] = useState<ChatMode>("fast");
  const [language, setLanguage] = useState<"hu" | "en">(CHAT_SAMPLES[0]!.language);
  const [model, setModel] = useState(DEFAULT_CHAT_MODEL);
  const [text, setText] = useState(CHAT_SAMPLES[0]!.text);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const lastDraft = useRef<number | null>(null);
  const busy = turns.some((t) => t.status === "masking" || t.status === "streaming");

  const activate = (key: string | null, el?: HTMLElement | null) => {
    setActiveKey(key);
    setAnchor(key ? (el ?? null) : null);
  };

  useEffect(() => () => abortRef.current?.abort(), []);


  const reset = () => {
    abortRef.current?.abort();
    setTurns([]);
    setSessionId(null);
    activate(null);
  };

  // A different engine (demo vs live) can't continue the other's session.
  const [engineKind, setEngineKind] = useState(client.kind);
  if (engineKind !== client.kind) {
    setEngineKind(client.kind);
    setTurns([]);
    setSessionId(null);
  }

  const update = (id: number, patch: Partial<Turn>) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t)));

  const send = async (override?: { text: string; language: "hu" | "en" }) => {
    const message = (override?.text ?? text).trim();
    const lang = override?.language ?? language;
    const fresh = override !== undefined;
    if (!message || (busy && !fresh)) return;
    if (fresh) abortRef.current?.abort();
    const id = nextId.current++;
    const history: ChatMessage[] = [{ role: "system", content: SYSTEM_PROMPT }];
    for (const t of fresh ? [] : turns) {
      if (t.status !== "done") continue;
      history.push({ role: "user", content: t.user }, { role: "assistant", content: t.answer });
    }
    history.push({ role: "user", content: message });
    setTurns((ts) => [
      ...(fresh ? [] : ts.filter((t) => t.status !== "error")),
      { id, user: message, mode, status: "masking", thinking: false, maskedUser: null, maskedSystem: null, answer: "", maskedAnswer: null, masked: null, ms: null, error: null },
    ]);
    setText("");
    // Keep the keyboard user in the composer; bring the new turn into view.
    requestAnimationFrame(() => {
      document.getElementById("chat-input")?.focus({ preventScroll: true });
      document.getElementById(`turn-${id}`)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
    });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result = await client.send({
        messages: history,
        model,
        mode,
        language: lang,
        sessionId: fresh ? null : sessionId,
        signal: controller.signal,
        onMaskedRequest: (msgs) =>
          update(id, {
            status: "streaming",
            maskedUser: [...msgs].reverse().find((m) => m.role === "user")?.content ?? null,
            maskedSystem: msgs.find((m) => m.role === "system")?.content ?? null,
          }),
        onAnswer: (answer) => update(id, { answer }),
        onThinking: () => update(id, { thinking: true }),
      });
      setSessionId(result.sessionId);
      update(id, {
        status: "done",
        answer: result.answer,
        maskedAnswer: result.maskedAnswer || null,
        maskedUser: [...result.maskedMessages].reverse().find((m) => m.role === "user")?.content ?? null,
        masked: result.masked,
        ms: result.ms,
      });
    } catch (err) {
      if (controller.signal.aborted) {
        setTurns((ts) => ts.filter((t) => t.id !== id));
        setText(message);
        return;
      }
      const error = toRunError(err);
      update(id, { status: "error", error });
      setText(message);
      // An expired session can't be continued; the next message starts a new one.
      if (error.code === "not_found") setSessionId(null);
    }
  };

  const stop = () => abortRef.current?.abort();

  // A document handed over from the Mask screen starts a new conversation and is sent at once.
  const conversationRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!draft || draft.nonce === lastDraft.current) return;
    lastDraft.current = draft.nonce;
    setView("chat");
    setLanguage(draft.language);
    setSessionId(null);
    void send({ text: draft.text, language: draft.language });
    requestAnimationFrame(() => conversationRef.current?.focus({ preventScroll: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per handed-over draft
  }, [draft]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
            Chat through the gateway. The model only ever sees placeholders.
          </h1>
          <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
            Your message goes through the pii-guard gateway, a drop-in for any OpenAI-compatible API. It is masked on the way out and the
            streamed answer is restored on the way back, with the same placeholder for the same person in every turn.
          </p>
        </div>
        <div role="group" aria-label="Chat view" className="flex rounded-lg border border-line bg-surface p-0.5 text-sm">
          {(
            [
              ["chat", client.kind === "mock" ? "Chat" : "Live chat"],
              ["replay", "Replay a document"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={view === id}
              onClick={() => setView(id)}
              className={["rounded-md px-3 py-1.5 font-medium", view === id ? "bg-ink text-canvas" : "text-muted hover:text-ink"].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {view === "replay" ? (
        replay
      ) : (
        <>
          {client.kind === "mock" && (
            <p role="note" className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
              <strong className="font-semibold text-warn">Simulated model.</strong> The demo engine masks in your browser and a scripted
              reply stands in for the LLM.{" "}
              {live ? "Switch the engine to Auto or Live API to chat with the real model." : "Start the API with an upstream model to chat for real."}
            </p>
          )}

          <p className="sr-only" aria-live="polite">
            {(() => {
              const t = turns[turns.length - 1];
              if (!t) return "";
              if (t.status === "masking") return "Masking your message";
              if (t.status === "streaming") return t.maskedUser ? "Masked message sent; waiting for the answer" : "";
              if (t.status === "error") return "Blocked. Nothing was sent to the model.";
              return "Answer received and restored";
            })()}
          </p>
          <section ref={conversationRef} tabIndex={-1} aria-label="Conversation" className="space-y-5 focus:outline-none">
            {turns.length === 0 && (
              <div className="rounded-xl border border-line px-6 py-8 text-center">
                <p className="text-sm font-semibold text-ink">No messages yet</p>
                <p className="mx-auto mt-1 max-w-md text-sm text-muted">
                  Send the sample below, or write your own (fictional data only). You will see the message as the model received it, its
                  raw answer, and the answer with the real values put back.
                </p>
              </div>
            )}
            {turns.map((t, i) => (
              <TurnView key={t.id} turn={t} first={i === 0} simulated={client.kind === "mock"} activeKey={activeKey} onActivate={activate} />
            ))}
          </section>

          <Composer
            text={text}
            onText={setText}
            onSend={() => void send()}
            onStop={stop}
            busy={busy}
            mode={mode}
            onMode={setMode}
            language={language}
            onLanguage={setLanguage}
            model={model}
            onModel={setModel}
            mock={client.kind === "mock"}
            sessionId={sessionId}
            onReset={turns.length ? reset : undefined}
          />
        </>
      )}

      <Popover anchor={activeKey ? anchor : null}>{activeKey && <PlaceholderInfo placeholder={activeKey} />}</Popover>
    </div>
  );
}

function PlaceholderInfo({ placeholder }: { placeholder: string }) {
  const token = tokenize(placeholder)[0];
  const meta = metaFor(token?.kind === "placeholder" ? token.entityType : null);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="inline-flex items-center gap-1.5 font-medium text-ink">
        <span className={["size-2 rounded-full", meta.swatch].join(" ")} />
        {meta.label}
      </span>
      <code className="font-mono text-ink">{placeholder}</code>
    </div>
  );
}

/** Original text with the values that were masked marked, by lining it up with the masked text. */
function segmentsFor(masked: string | null, original: string): RestoredSegment[] {
  if (!masked) return [{ kind: "text", text: original }];
  return alignRestored(masked, original) ?? alignLoose(masked, original) ?? [{ kind: "text", text: original }];
}

function TurnView({
  turn,
  first,
  simulated,
  activeKey,
  onActivate,
}: {
  turn: Turn;
  first: boolean;
  simulated: boolean;
  activeKey: string | null;
  onActivate: (key: string | null, el?: HTMLElement | null) => void;
}) {
  const userSegments = segmentsFor(turn.maskedUser, turn.user);
  const maskedValues = userSegments.filter((s) => s.kind === "restored").length;
  const answerSegments = turn.status === "done" ? segmentsFor(turn.maskedAnswer, turn.answer) : null;
  const marked = answerSegments?.filter((s) => s.kind === "restored").length ?? 0;
  const placeholdersInAnswer = turn.maskedAnswer ? tokenize(turn.maskedAnswer).filter((t) => t.kind === "placeholder").length : 0;
  // If the answer can't be lined up for highlighting, still count what was restored.
  const restored = marked || placeholdersInAnswer;

  return (
    <article id={`turn-${turn.id}`} aria-label="Chat turn" className="scroll-mt-24 grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-x-6">
      {/* Row 1: what you wrote | what the model received */}
      <Bubble side="you" label="You wrote">
        <RestoredText segments={userSegments} activeKey={activeKey} onActivate={onActivate} outgoing />
        {turn.maskedUser !== null && (
          <p className="mt-2 text-xs text-muted">
            {maskedValues === 0
              ? "Nothing was detected in this message, so it was sent as written."
              : `${maskedValues} ${maskedValues === 1 ? "value" : "values"} masked before sending (${simulated ? "demo engine" : `${turn.mode} mode`}). Unmarked text was sent as written.`}
          </p>
        )}
      </Bubble>
      <Bubble side="model" label="What the model received">
        {turn.status === "error" && turn.maskedUser === null ? (
          <p className="text-sm text-muted">Nothing was sent.</p>
        ) : turn.maskedUser === null ? (
          <Pending
            label={simulated ? "Masking in your browser…" : turn.mode === "audit" ? "Detecting personal data (rules + NER + LLM detector)…" : "Detecting personal data (rules + NER)…"}
          />
        ) : (
          <>
            <MaskedText text={turn.maskedUser} activeKey={activeKey} onActivate={onActivate} />
            {first && turn.maskedSystem && (
              <details className="mt-2 text-xs text-muted">
                <summary className="cursor-pointer">System prompt sent with it</summary>
                <p className="mt-1">{turn.maskedSystem}</p>
              </details>
            )}
          </>
        )}
      </Bubble>

      {/* Row 2: what you got back | what the model said */}
      {turn.status === "error" && turn.error ? (
        <div className="lg:col-span-2">
          <BlockedNotice error={turn.error} />
          {(turn.error.code === "detection_unavailable" ||
            (turn.error.code === "detection_failed" && turn.mode === "audit")) && (
            <p className="mt-2 text-sm text-muted">
              Audit mode needs a working LLM detector key on the server (
              <code className="font-mono text-xs">PII_GUARD_LLM_DETECTOR_API_KEY</code>). Switch to Fast to continue.
            </p>
          )}
          {turn.error.code === "upstream_not_configured" && (
            <p className="mt-2 text-sm text-muted">
              Start the API with <code className="font-mono text-xs">PII_GUARD_UPSTREAM_BASE_URL</code> and{" "}
              <code className="font-mono text-xs">PII_GUARD_UPSTREAM_API_KEY</code> set (see the README, “Gateway”).
            </p>
          )}
        </div>
      ) : (
        <>
          <Bubble side="you" label="What you got back" className="lg:order-none">
            <div>
              {answerSegments ? (
                <RestoredText segments={answerSegments} activeKey={activeKey} onActivate={onActivate} />
              ) : turn.answer ? (
                <p className="doc text-ink">
                  {turn.answer}
                  <span aria-hidden="true" className="ml-0.5 inline-block h-4 w-2 translate-y-0.5 bg-ink motion-safe:animate-pulse" />
                </p>
              ) : (
                <Pending
                  label={
                    turn.maskedUser === null
                      ? "Waiting for the masked request…"
                      : turn.thinking
                        ? "The model is reasoning before it answers…"
                        : "Waiting for the model…"
                  }
                />
              )}
            </div>
            {turn.status === "done" && (
              <p className="mt-2 text-xs text-muted">
                {restored} {restored === 1 ? "value" : "values"} restored{turn.ms !== null ? ` · ${turn.ms < 1000 ? `${Math.max(1, Math.round(turn.ms))} ms` : `${(turn.ms / 1000).toFixed(1)} s`}` : ""}.{" "}
                {marked > 0 || restored === 0
                  ? "Marked values were placeholders in the model's answer."
                  : "Compare with the model's answer to see where they were (this answer couldn't be lined up for highlighting)."}
              </p>
            )}
          </Bubble>
          <Bubble side="model" label="What the model answered">
            {turn.maskedAnswer ? (
              <MaskedText text={turn.maskedAnswer} activeKey={activeKey} onActivate={onActivate} />
            ) : (
              <Pending label={turn.status === "done" ? "Not available" : "Shown when the answer is complete."} still={turn.status === "done"} />
            )}
          </Bubble>
        </>
      )}
    </article>
  );
}

function Bubble({ side, label, children, className = "" }: { side: "you" | "model"; label: string; children: ReactNode; className?: string }) {
  return (
    <section
      aria-label={label}
      data-side={side}
      className={[
        "min-w-0 rounded-xl border px-4 py-3",
        side === "model" ? "border-model/25 bg-model-soft/40" : "border-line bg-surface",
        className,
      ].join(" ")}
    >
      <h3
        className={[
          "mb-1.5 font-mono text-2xs",
          side === "model" ? "text-model" : "text-guard",
        ].join(" ")}
      >
        {side === "model" ? "Model side · " : "Your side · "}
        {label}
      </h3>
      {children}
    </section>
  );
}

function Pending({ label, still = false }: { label: string; still?: boolean }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted">
      {!still && <span aria-hidden="true" className="size-2 rounded-full bg-faint motion-safe:animate-pulse" />}
      {label}
    </p>
  );
}

interface ComposerProps {
  text: string;
  onText: (t: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  mode: ChatMode;
  onMode: (m: ChatMode) => void;
  language: "hu" | "en";
  onLanguage: (l: "hu" | "en") => void;
  model: string;
  onModel: (m: string) => void;
  mock: boolean;
  sessionId: string | null;
  onReset?: () => void;
}

function Composer({ text, onText, onSend, onStop, busy, mode, onMode, language, onLanguage, model, onModel, mock, sessionId, onReset }: ComposerProps) {
  const modeHint = mock
    ? "The demo engine runs a small rule set in your browser in both modes; the AI detector and the real model need the live API."
    : MODES.find((m) => m.id === mode)!.hint;
  return (
    <section aria-label="New message" className="space-y-3 rounded-xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted">Fictional samples</span>
        {CHAT_SAMPLES.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => {
              onText(s.text);
              onLanguage(s.language);
            }}
            className="rounded-full border border-line px-3 py-1 text-xs font-medium text-ink hover:border-line-strong"
          >
            {s.label}
          </button>
        ))}
      </div>
      <label htmlFor="chat-input" className="sr-only">
        Message
      </label>
      <textarea
        id="chat-input"
        value={text}
        onChange={(e) => onText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onSend();
          }
        }}
        rows={4}
        spellCheck={false}
        placeholder="Write a message with some (fictional) personal data in it…"
        className="doc block w-full resize-y rounded-lg border border-line bg-surface-2 p-3 text-ink placeholder:text-faint focus:border-line-strong"
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div role="radiogroup" aria-label="Detection mode" className="flex rounded-lg border border-line bg-surface-2 p-0.5 text-sm">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={mode === m.id}
              title={m.hint}
              onClick={() => onMode(m.id)}
              className={["rounded-md px-3 py-1.5 font-medium", mode === m.id ? "bg-ink text-canvas" : "text-muted hover:text-ink"].join(" ")}
            >
              {m.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-muted">
          Language
          <select
            value={language}
            onChange={(e) => onLanguage(e.target.value as "hu" | "en")}
            className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink"
          >
            <option value="hu">Hungarian</option>
            <option value="en">English</option>
          </select>
        </label>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {onReset && (
            <Button variant="ghost" onClick={onReset} disabled={busy}>
              New conversation
            </Button>
          )}
          {busy ? (
            <Button variant="secondary" onClick={onStop}>
              Stop
            </Button>
          ) : (
            <Button variant="primary" onClick={onSend} disabled={text.trim() === ""}>
              Send through pii-guard <span aria-hidden="true">→</span>
            </Button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted">
        <span className="font-semibold text-ink">{mock ? "Demo engine" : `${MODES.find((m) => m.id === mode)!.label} mode`}:</span> {modeHint}{" "}
        <kbd className="rounded border border-line px-1 font-mono text-2xs">⌘/Ctrl ↵</kbd> sends.
      </p>
      <details className="text-xs text-muted">
        <summary className="cursor-pointer">Connection details</summary>
        <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
          <dt>Model</dt>
          <dd>
            {mock ? (
              "Simulated (demo engine)"
            ) : (
              <>
                <label htmlFor="chat-model" className="sr-only">
                  Upstream model
                </label>
                <input
                  id="chat-model"
                  value={model}
                  onChange={(e) => onModel(e.target.value)}
                  className="h-7 w-full max-w-sm rounded border border-line bg-surface-2 px-2 font-mono text-xs text-ink"
                />
              </>
            )}
          </dd>
          <dt>Endpoint</dt>
          <dd className="font-mono">POST /v1/chat/completions (stream)</dd>
          <dt>Session</dt>
          <dd className="truncate font-mono">{sessionId ?? "new on first message"}</dd>
        </dl>
      </details>
    </section>
  );
}
