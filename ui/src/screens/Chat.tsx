import { useEffect, useRef, useState, type ReactNode } from "react";
import { FALLBACK_CHAT_MODEL, SYSTEM_PROMPT, isChatModel, pickDefaultModel, type ChatClient, type ChatMessage, type ChatMode, type KeptSpan } from "../api/chat";
import { MaskedText } from "../components/MaskedText";
import { Popover } from "../components/Popover";
import { RestoredText } from "../components/RestoredText";
import { NerHint } from "../components/NerHint";
import { BlockedNotice, Button, ConfirmAction, Input, SegmentedControl, Select, Textarea } from "../components/ui";
import { CHAT_SAMPLES, DEFAULT_CHAT_SAMPLE } from "../content/chatSamples";
import { metaFor } from "../lib/entities";
import { SESSION_SOURCE_LABEL } from "../lib/traffic";
import { alignLoose, alignRestored, tokenize, type RestoredSegment } from "../lib/placeholders";
import { toRunError, type RunError } from "../lib/run";
import { errorCopy, statusFromMessage } from "../lib/errorCopy";
import { readPref, writePref } from "../lib/storage";

/** Where the last model used in Chat is remembered (per viewer, best effort). */
export const MODEL_PREF = "chat-model";

export interface ChatDraft {
  text: string;
  language: "hu" | "en";
  /** Changes every time a new draft is handed over, so the same text can be sent twice. */
  nonce: number;
  /** The Text screen's vault session: reusing it keeps every placeholder number (LAB-1261). */
  sessionId?: string | null;
}

interface Turn {
  id: number;
  user: string;
  mode: ChatMode;
  status: "masking" | "streaming" | "done" | "error";
  thinking: boolean;
  maskedUser: string | null;
  /** Values in your message detected but kept by policy (gateway echo, LAB-1180). */
  keptUser: KeptSpan[];
  maskedSystem: string | null;
  answer: string;
  maskedAnswer: string | null;
  masked: number | null;
  ms: number | null;
  error: RunError | null;
  finishReason: string | null;
}

/** The gateway's model list: loading, the ids it serves, or failed (then the fallback / a typed id is used). */
interface ModelList {
  status: "idle" | "loading" | "ok" | "failed";
  ids: string[];
}

interface Props {
  client: ChatClient;
  /** The live API is up but no upstream may be configured; shown as a hint only. */
  live: boolean;
  draft: ChatDraft | null;
  /** Whether the server runs the NER (`/v1/status`); null when unknown. False: names pass unmasked. */
  ner?: boolean | null;
  /** The server's upstream is the offline mock model, which echoes (LAB-1264). */
  mockUpstream?: boolean;
  /** The detection modes the server offers (`/v1/status` `gateway.modes`); a hosted owner gets fast only. */
  modes?: readonly ChatMode[];
}

const ALL_MODES: readonly ChatMode[] = ["fast", "audit"];

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

export function Chat({ client, live, draft, ner = null, mockUpstream = false, modes = ALL_MODES }: Props) {
  const [chosenMode, setMode] = useState<ChatMode>("fast");
  // A mode the server stops offering (or never offered) is never sent.
  const mode = modes.includes(chosenMode) ? chosenMode : (modes[0] ?? "fast");
  const [language, setLanguage] = useState<"hu" | "en">(DEFAULT_CHAT_SAMPLE.language);
  const [model, setModel] = useState(FALLBACK_CHAT_MODEL);
  /** The last `/v1/models` answer, and which client it came from (null ids: it failed). */
  const [listed, setListed] = useState<{ client: ChatClient; ids: string[] | null } | null>(null);
  const models: ModelList =
    listed?.client === client
      ? { status: listed.ids ? "ok" : "failed", ids: listed.ids ?? [] }
      : { status: client.kind === "api" && client.listModels ? "loading" : "idle", ids: [] };
  const [text, setText] = useState(DEFAULT_CHAT_SAMPLE.text);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionSource, setSessionSource] = useState<string | null>(null);
  /** The conversation continues the Text screen's session (same placeholders). */
  const [handedOver, setHandedOver] = useState(false);
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

  // Default to a model the upstream actually serves (LAB-1335): the last one used if it's
  // still listed, else a preferred one, else the first chat-capable id.
  useEffect(() => {
    if (client.kind !== "api" || !client.listModels) return;
    const controller = new AbortController();
    client.listModels(controller.signal).then(
      (ids) => {
        setListed({ client, ids });
        setModel(pickDefaultModel(ids, readPref(MODEL_PREF)));
      },
      () => {
        if (controller.signal.aborted) return;
        setListed({ client, ids: null });
        setModel(readPref(MODEL_PREF) || FALLBACK_CHAT_MODEL);
      },
    );
    return () => controller.abort();
  }, [client]);

  const chooseModel = (m: string) => {
    setModel(m);
    if (m.trim()) writePref(MODEL_PREF, m.trim());
  };
  const needsModel = client.kind === "api" && !mockUpstream && model.trim() === "";


  const reset = () => {
    abortRef.current?.abort();
    setTurns([]);
    setSessionId(null);
    setSessionSource(null);
    setHandedOver(false);
    activate(null);
    // The confirmation unmounts with the conversation: keep the keyboard user in the composer.
    requestAnimationFrame(() => document.getElementById("chat-input")?.focus({ preventScroll: true }));
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

  const send = async (override?: { text: string; language: "hu" | "en"; sessionId?: string | null }, retry?: string) => {
    const message = (override?.text ?? retry ?? text).trim();
    const lang = override?.language ?? language;
    const fresh = override !== undefined;
    if (!message || (busy && !fresh) || needsModel) return;
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
      { id, user: message, mode, status: "masking", thinking: false, maskedUser: null, keptUser: [], maskedSystem: null, answer: "", maskedAnswer: null, masked: null, ms: null, error: null, finishReason: null },
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
        model: model.trim(),
        mode,
        language: lang,
        sessionId: fresh ? (override.sessionId ?? null) : sessionId,
        signal: controller.signal,
        onMaskedRequest: (msgs, kept) =>
          update(id, {
            status: "streaming",
            maskedUser: [...msgs].reverse().find((m) => m.role === "user")?.content ?? null,
            keptUser: kept[kept.length - 1] ?? [],
            maskedSystem: msgs.find((m) => m.role === "system")?.content ?? null,
          }),
        onAnswer: (answer) => update(id, { answer }),
        onThinking: () => update(id, { thinking: true }),
      });
      setSessionId(result.sessionId);
      setSessionSource(result.sessionSource ?? null);
      update(id, {
        status: "done",
        answer: result.answer,
        maskedAnswer: result.maskedAnswer || null,
        maskedUser: [...result.maskedMessages].reverse().find((m) => m.role === "user")?.content ?? null,
        keptUser: result.keptSpans?.[result.keptSpans.length - 1] ?? [],
        masked: result.masked,
        ms: result.ms,
        finishReason: result.finishReason ?? null,
      });
      if (client.kind === "api" && model.trim()) writePref(MODEL_PREF, model.trim());
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

  // Stop swaps back to Send: keep the keyboard user in the composer.
  const stop = () => {
    abortRef.current?.abort();
    requestAnimationFrame(() => document.getElementById("chat-input")?.focus({ preventScroll: true }));
  };

  // A document handed over from the Mask screen starts a new conversation and is sent at once.
  const conversationRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!draft || draft.nonce === lastDraft.current) return;
    lastDraft.current = draft.nonce;
    setLanguage(draft.language);
    setSessionId(draft.sessionId ?? null);
    setHandedOver(Boolean(draft.sessionId));
    void send({ text: draft.text, language: draft.language, sessionId: draft.sessionId ?? null });
    requestAnimationFrame(() => conversationRef.current?.focus({ preventScroll: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once per handed-over draft
  }, [draft]);

  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-pretty text-muted">
        Your message goes through the PII Guard gateway, a drop-in for any OpenAI-compatible API. The model only ever sees placeholders: the message is masked on the way
        out and the streamed answer is restored on the way back, with the same placeholder for the same person in every turn.
      </p>

      <>
          {client.kind === "mock" && (
            <p role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
              <strong className="font-medium text-warn">Simulated model.</strong> The demo engine masks in your browser and a scripted
              reply stands in for the LLM.{" "}
              {live ? "Switch the engine to Auto or Live API to chat with the real model." : "Start the API with an upstream model to chat for real."}
            </p>
          )}
          {client.kind === "api" && ner === false && (
            <p role="note" data-testid="rules-only-note" className="rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
              <strong className="font-medium text-warn">Names are not detected.</strong> This server runs fast mode with the rules only, so email addresses, phone numbers,
              IBANs and IDs are masked but free-text names reach the model as written. Names need <NerHint />.
            </p>
          )}
          {client.kind === "api" && mockUpstream && (
            <p role="note" className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-ink">
              <strong className="font-medium">Mock upstream.</strong> The server's model is the offline mock: it answers by echoing the masked text it received, whatever model
              is named. Start PII Guard with <code className="font-mono text-xs">--upstream-url</code> for a real one.
            </p>
          )}

          <p className="sr-only" aria-live="polite">
            {(() => {
              const t = turns[turns.length - 1];
              if (!t) return "";
              if (t.status === "masking") return "Masking your message";
              if (t.status === "streaming") return t.maskedUser ? "Masked message sent; waiting for the answer" : "";
              if (t.status === "error" && t.error) return errorCopy(t.error.code, t.error.status ?? statusFromMessage(t.error.message)).title;
              return "Answer received and restored";
            })()}
          </p>
          <section ref={conversationRef} tabIndex={-1} aria-label="Conversation" className="space-y-5 focus:outline-none">
            {turns.length === 0 && (
              <div className="rounded-xl border border-line px-6 py-8 text-center">
                <p className="text-sm font-medium text-ink">No messages yet</p>
                <p className="mx-auto mt-1 max-w-md text-sm text-muted">
                  Send the sample below, or write your own (fictional data only). You will see the message as the model received it, its
                  raw answer, and the answer with the real values put back.
                </p>
              </div>
            )}
            {turns.map((t, i) => (
              <TurnView
                key={t.id}
                turn={t}
                first={i === 0}
                simulated={client.kind === "mock"}
                activeKey={activeKey}
                onActivate={activate}
                onRetry={t.status === "error" && i === turns.length - 1 && !busy && !needsModel ? () => void send(undefined, t.user) : undefined}
              />
            ))}
          </section>

          <Composer
            text={text}
            onText={setText}
            onSend={() => void send()}
            onStop={stop}
            busy={busy}
            mode={mode}
            modes={modes}
            onMode={setMode}
            language={language}
            onLanguage={setLanguage}
            model={model}
            onModel={chooseModel}
            models={models}
            needsModel={needsModel}
            mock={client.kind === "mock"}
            sessionId={sessionId}
            onReset={turns.length ? reset : undefined}
            mockUpstream={mockUpstream}
            sessionSource={sessionSource}
            handedOver={handedOver}
          />
        </>

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

/** The masked request left pii-guard and reached (or was sent to) the upstream. */
function reachedUpstream(error: RunError): boolean {
  const kind = errorCopy(error.code).kind;
  return kind === "upstream" || kind === "stream";
}

function TurnView({
  turn,
  first,
  simulated,
  activeKey,
  onActivate,
  onRetry,
}: {
  turn: Turn;
  first: boolean;
  simulated: boolean;
  activeKey: string | null;
  onActivate: (key: string | null, el?: HTMLElement | null) => void;
  onRetry?: () => void;
}) {
  const userSegments = segmentsFor(turn.maskedUser, turn.user);
  const maskedValues = userSegments.filter((s) => s.kind === "restored").length;
  const keptValues = turn.keptUser.length;
  const keptLine = `${keptValues} ${keptValues === 1 ? "value" : "values"} detected but kept by policy (dashed outline)`;
  const answerSegments = turn.status === "done" ? segmentsFor(turn.maskedAnswer, turn.answer) : null;
  const marked = answerSegments?.filter((s) => s.kind === "restored").length ?? 0;
  const placeholdersInAnswer = turn.maskedAnswer ? tokenize(turn.maskedAnswer).filter((t) => t.kind === "placeholder").length : 0;
  // If the answer can't be lined up for highlighting, still count what was restored.
  const restored = marked || placeholdersInAnswer;

  return (
    <article id={`turn-${turn.id}`} aria-label="Chat turn" className="scroll-mt-24 grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-x-6">
      {/* Row 1: what you wrote | what the model received */}
      <Bubble side="you" label="You wrote">
        <RestoredText segments={userSegments} activeKey={activeKey} onActivate={onActivate} outgoing kept={turn.keptUser} />
        {turn.maskedUser !== null && (
          <p className="mt-2 text-xs text-muted">
            {maskedValues === 0 && keptValues === 0
              ? "Nothing was detected in this message, so it was sent as written."
              : maskedValues === 0
                ? `Nothing was masked; ${keptLine}. The rest was sent as written.`
                : `${maskedValues} ${maskedValues === 1 ? "value" : "values"} masked before sending (${simulated ? "demo engine" : `${turn.mode} mode`})${keptValues ? `; ${keptLine}` : ""}. Unmarked text was sent as written.`}
          </p>
        )}
      </Bubble>
      <Bubble side="model" label="What the model received">
        {turn.status === "error" && turn.maskedUser === null ? (
          <p className="text-sm text-muted">
            {turn.error && reachedUpstream(turn.error)
              ? "The masked request was sent; the upstream refused it before answering."
              : "Nothing was sent."}
          </p>
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
          <BlockedNotice error={turn.error} onRetry={onRetry} />
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
            {turn.status === "done" && turn.answer.trim() === "" && (
              <p role="note" data-testid="empty-answer-hint" className="mt-1 text-sm text-warn">
                {turn.finishReason === "length"
                  ? "The model used its whole token budget reasoning and returned no answer: raise max tokens, or pick a non-reasoning model."
                  : "The model returned an empty answer."}
              </p>
            )}
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
  modes: readonly ChatMode[];
  onMode: (m: ChatMode) => void;
  language: "hu" | "en";
  onLanguage: (l: "hu" | "en") => void;
  model: string;
  onModel: (m: string) => void;
  models: ModelList;
  needsModel: boolean;
  mock: boolean;
  sessionId: string | null;
  onReset?: () => void;
  mockUpstream: boolean;
  sessionSource: string | null;
  handedOver: boolean;
}

function Composer({ text, onText, onSend, onStop, busy, mode, modes, onMode, language, onLanguage, model, onModel, models, needsModel, mock, sessionId, onReset, mockUpstream, sessionSource, handedOver }: ComposerProps) {
  const chatIds = models.ids.filter(isChatModel);
  const options = model && !chatIds.includes(model) ? [model, ...chatIds] : chatIds;
  const modeHint = mock
    ? "The demo engine runs a small rule set in your browser in both modes; the AI detector and the real model need the live API."
    : MODES.find((m) => m.id === mode)!.hint;
  return (
    <section aria-label="New message" className="space-y-3 rounded-xl border border-line bg-surface p-4 sm:p-5">
      <div role="group" aria-labelledby="chat-samples-label" className="flex flex-wrap items-center gap-2">
        <span id="chat-samples-label" className="text-xs font-medium text-muted">
          Fictional samples
        </span>
        {CHAT_SAMPLES.map((s) => (
          <Button
            key={s.id}
            size="sm"
            onClick={() => {
              onText(s.text);
              onLanguage(s.language);
            }}
          >
            {s.label}
          </Button>
        ))}
      </div>
      <label htmlFor="chat-input" className="sr-only">
        Message
      </label>
      <Textarea
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
        className="doc block"
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="text-sm text-muted">
            Detection
          </span>
          <SegmentedControl
            label="Detection mode"
            name="chat-mode"
          value={mode}
          onChange={onMode}
          options={MODES.filter((m) => modes.includes(m.id)).map((m) => ({ value: m.id, label: m.label, title: m.hint }))}
          />
        </span>
        <label className="flex items-center gap-2 text-sm text-muted">
          Language
          <span className="w-32">
            <Select value={language} onChange={(e) => onLanguage(e.target.value as "hu" | "en")}>
              <option value="hu">Hungarian</option>
              <option value="en">English</option>
            </Select>
          </span>
        </label>
        {!mock && !mockUpstream && (
          <label className="flex min-w-0 items-center gap-2 text-sm text-muted">
            Model
            <span className="w-56 min-w-0 max-w-full">
              {models.status === "ok" && options.length > 0 ? (
                <Select id="chat-model" aria-label="Model" value={model} onChange={(e) => onModel(e.target.value)} className="font-mono">
                  {options.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id="chat-model"
                  aria-label="Model"
                  value={model}
                  onChange={(e) => onModel(e.target.value)}
                  disabled={models.status === "loading"}
                  placeholder={models.status === "loading" ? "Loading models…" : "upstream model id"}
                  spellCheck={false}
                  className="font-mono"
                />
              )}
            </span>
          </label>
        )}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {onReset && (
            <ConfirmAction
              trigger="New conversation"
              triggerVariant="ghost"
              title="Start a new conversation?"
              body="This conversation and its placeholders are cleared from the screen. The next message starts a new session."
              confirm="Clear and start over"
              disabled={busy}
              onConfirm={onReset}
            />
          )}
          {busy ? (
            <Button variant="secondary" onClick={onStop}>
              Stop
            </Button>
          ) : (
            <Button variant="primary" onClick={onSend} disabled={text.trim() === "" || needsModel} title={needsModel ? "Choose a model first" : undefined}>
              Send through PII Guard <span aria-hidden="true">→</span>
            </Button>
          )}
        </div>
      </div>
      {!mock && !mockUpstream && models.status === "failed" && (
        <p role="note" data-testid="models-failed" className="text-xs text-warn">
          The gateway's model list (<code className="font-mono">GET /v1/models</code>) is not available. Type a model id the upstream serves.
        </p>
      )}
      <p className="text-xs text-muted">
        <span className="font-medium text-ink">{mock ? "Demo engine" : `${MODES.find((m) => m.id === mode)!.label} mode`}:</span> {modeHint}{" "}
        <kbd className="rounded border border-line px-1 font-mono text-2xs">⌘/Ctrl ↵</kbd> sends.
      </p>
      <details className="text-xs text-muted">
        <summary className="cursor-pointer">Connection details</summary>
        <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
          <dt>Model</dt>
          <dd>
            {mock ? (
              "Simulated (demo engine)"
            ) : mockUpstream ? (
              "Mock upstream (echo): the model name is ignored"
            ) : (
              <>
                <span className="font-mono">{model || "none chosen"}</span>
                {models.status === "ok" ? ` · ${models.ids.length} listed by GET /v1/models` : models.status === "failed" ? " · GET /v1/models failed" : ""}
              </>
            )}
          </dd>
          <dt>Endpoint</dt>
          <dd className="font-mono">POST /v1/chat/completions (stream)</dd>
          <dt>Session</dt>
          <dd className="min-w-0">
            <span className="block truncate font-mono">{sessionId ?? "new on first message"}</span>
            {handedOver && <span className="block">Continued from Text: the same values keep the same placeholders.</span>}
            {sessionSource && <span className="block">Picked by the gateway from: {SESSION_SOURCE_LABEL[sessionSource] ?? sessionSource}</span>}
          </dd>
        </dl>
      </details>
    </section>
  );
}
