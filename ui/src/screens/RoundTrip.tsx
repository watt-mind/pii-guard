import { useEffect, useMemo, useRef, useState } from "react";
import type { RoutingClient } from "../api/engine";
import { Boundary } from "../components/Boundary";
import { MaskedText } from "../components/MaskedText";
import { Pane } from "../components/Pane";
import { Placeholder } from "../components/Placeholder";
import { Popover } from "../components/Popover";
import { RestoredText } from "../components/RestoredText";
import { BlockedNotice, Button, EmptyState, Stat } from "../components/ui";
import { SAMPLES } from "../data/samples";
import { valuesByPlaceholder } from "../lib/analysis";
import { metaFor } from "../lib/entities";
import { tokenize } from "../lib/placeholders";
import { toRunError, initialAnswer, type RunError, type RunResult } from "../lib/run";
import { chunkify, playStream, restore, type Restoration } from "../lib/stream";

const SPEEDS = [
  { id: "slow", label: "Slow", ms: 140 },
  { id: "normal", label: "Normal", ms: 60 },
  { id: "fast", label: "Fast", ms: 20 },
] as const;
type SpeedId = (typeof SPEEDS)[number]["id"];

const INVENTED = " Please also copy [[PERSON_0bad]] on the reply.";

interface Props {
  client: RoutingClient;
  result: RunResult | null;
  answer: string;
  onAnswer: (a: string) => void;
  running: boolean;
  onRun: () => void;
}

type View =
  | { kind: "idle" }
  | { kind: "streaming"; received: string[]; held: string; total: number; restoration: Restoration; freshFrom: number }
  | { kind: "done"; restoration: Restoration; streamed: { chunks: string[] } | null; freshFrom: number }
  | { kind: "error"; error: RunError };

export function RoundTrip({ client, result, answer, onAnswer, running, onRun }: Props) {
  const [view, setView] = useState<View>({ kind: "idle" });
  const [speed, setSpeed] = useState<SpeedId>("normal");
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const activate = (key: string | null, el?: HTMLElement | null) => {
    setActiveKey(key);
    setAnchor(key ? (el ?? null) : null);
  };
  const abortRef = useRef<AbortController | null>(null);

  const values = useMemo(() => (result ? valuesByPlaceholder(result.input, result.links) : new Map<string, string>()), [result]);
  const expected = (ph: string) => values.get(ph);
  const sample = SAMPLES.find((s) => s.id === result?.sampleId);

  // An edited answer invalidates the previous restoration. (A new session remounts this screen.)
  const editAnswer = (a: string) => {
    abortRef.current?.abort();
    setView({ kind: "idle" });
    onAnswer(a);
  };

  useEffect(() => () => abortRef.current?.abort(), []);

  if (!result) {
    return (
      <div className="space-y-6">
        <RoundTripIntro />
        <EmptyState title="No masked document yet" body="Mask a document first; its placeholders are what the model answers with.">
          <Button variant="primary" onClick={onRun} disabled={running}>
            {running ? "Masking…" : "Mask the sample document"}
          </Button>
        </EmptyState>
      </div>
    );
  }

  const sessionId = result.mask.session_id;
  const streaming = view.kind === "streaming";
  const tokens = tokenize(answer);
  const answerPlaceholders = tokens.filter((t) => t.kind === "placeholder");
  const issued = new Set(result.mask.entities.map((e) => e.placeholder));

  const restoreNow = async () => {
    abortRef.current?.abort();
    try {
      const restoration = await restore(client, sessionId, answer, expected);
      setView({ kind: "done", restoration, streamed: null, freshFrom: 0 });
    } catch (err) {
      setView({ kind: "error", error: toRunError(err) });
    }
  };

  const stream = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const chunks = chunkify(answer, answer.length);
    setView({ kind: "streaming", received: [], held: "", total: chunks.length, restoration: { segments: [], unresolved: [] }, freshFrom: 0 });
    try {
      await playStream({
        client,
        sessionId,
        chunks,
        delayMs: SPEEDS.find((s) => s.id === speed)!.ms,
        expected,
        signal: controller.signal,
        onStep: (step) =>
          setView(
            step.done
              ? { kind: "done", restoration: step.restoration, streamed: { chunks: step.received }, freshFrom: step.previousSegmentCount }
              : {
                  kind: "streaming",
                  received: step.received,
                  held: step.held,
                  total: chunks.length,
                  restoration: step.restoration,
                  freshFrom: step.previousSegmentCount,
                },
          ),
      });
    } catch (err) {
      if (!controller.signal.aborted) setView({ kind: "error", error: toRunError(err) });
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setView({ kind: "idle" });
  };

  const restoration = view.kind === "streaming" || view.kind === "done" ? view.restoration : null;
  const restoredCount = restoration?.segments.filter((s) => s.kind === "restored").length ?? 0;
  const unresolved = restoration?.unresolved ?? [];
  const freshFrom = view.kind === "streaming" || view.kind === "done" ? view.freshFrom : 0;
  const chunksShown = view.kind === "streaming" ? view.received : view.kind === "done" ? view.streamed?.chunks ?? null : null;

  return (
    <div className="space-y-6">
      <RoundTripIntro live={result.engine === "api"} />

      <details className="group rounded-2xl border border-model/25 bg-surface">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
          <span>
            <span className="block text-[11px] font-semibold tracking-[0.08em] text-model uppercase">Sent to the model</span>
            <span className="block text-sm font-semibold text-ink">
              What the model saw{sample ? ` · ${sample.subtitle.toLowerCase()}` : ""}
            </span>
          </span>
          <span className="text-xs text-muted">
            <span className="group-open:hidden">Show</span>
            <span className="hidden group-open:inline">Hide</span>
          </span>
        </summary>
        <div className="space-y-3 border-t border-model/20 px-4 py-4 sm:px-5">
          {sample && (
            <p className="rounded-lg bg-model-soft px-3 py-2 text-sm text-ink">
              <span className="font-semibold text-model">Instruction · </span>
              {sample.task}
            </p>
          )}
          <MaskedText text={result.mask.masked_text} activeKey={activeKey} onActivate={activate} />
        </div>
      </details>

      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane
          id="answer"
          side="model"
          eyebrow="From the model"
          title={chunksShown ? "Streaming in" : "Model answer"}
          className="lg:flex-1"
          actions={
            !chunksShown ? (
              <>
                <Button variant="ghost" onClick={() => editAnswer(initialAnswer(result, sample))}>
                  Reset
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => editAnswer(answer + INVENTED)}
                  disabled={answer.includes("[[PERSON_0bad]]")}
                  title="Append a placeholder that is not in this session, as a model might invent one"
                >
                  + Invented placeholder
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={stop}>
                {streaming ? "Stop" : "Edit answer"}
              </Button>
            )
          }
          footer={
            chunksShown ? (
              <span>
                Placeholders split across chunks are held back until they are complete, then restored.{" "}
                {view.kind === "streaming" && view.held && (
                  <>
                    Holding <code className="rounded bg-warn-soft px-1 font-mono text-warn">{view.held}</code>
                  </>
                )}
              </span>
            ) : (
              <span>
                {result.engine === "api"
                  ? "Simulated, edit freely. The model got placeholders only for what was masked; anything the detectors missed it saw as written."
                  : "Edit freely: this stands in for the LLM. It can only refer to people through placeholders."}
              </span>
            )
          }
        >
          {chunksShown ? (
            <ChunkStream chunks={chunksShown} held={view.kind === "streaming" ? view.held : ""} />
          ) : (
            <div className="space-y-3">
              <label htmlFor="answer-input" className="sr-only">
                Simulated model answer
              </label>
              <textarea
                id="answer-input"
                value={answer}
                onChange={(e) => editAnswer(e.target.value)}
                spellCheck={false}
                rows={12}
                className="doc block min-h-[18rem] w-full resize-y rounded-lg border border-line bg-surface-2 p-3 text-ink focus:border-model focus:outline-none"
              />
              {answerPlaceholders.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs text-faint">Placeholders in this answer</p>
                  <ul className="flex flex-wrap gap-1.5 text-xs">
                    {[...new Set(answerPlaceholders.map((t) => t.text))].map((ph) => {
                      const t = answerPlaceholders.find((x) => x.text === ph)!;
                      const known = issued.has(ph);
                      return (
                        <li key={ph}>
                          <Placeholder
                            text={ph}
                            entityType={t.kind === "placeholder" ? t.entityType : null}
                            unresolved={!known}
                            description={known ? `${metaFor(t.kind === "placeholder" ? t.entityType : null).label} placeholder` : "not issued in this session"}
                          />
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Pane>

        <Boundary direction="inbound" label="pii-guard boundary: placeholders are restored on the way back">
          <div className="flex flex-row items-center gap-2 lg:flex-col">
            <Button variant="primary" onClick={() => void stream()} disabled={streaming || answer.trim() === ""} className="lg:w-full">
              <span aria-hidden="true">▶</span> Stream
            </Button>
            <Button variant="secondary" onClick={() => void restoreNow()} disabled={streaming || answer.trim() === ""} className="lg:w-full">
              Restore
            </Button>
            <label className="sr-only" htmlFor="stream-speed">
              Stream speed
            </label>
            <select
              id="stream-speed"
              value={speed}
              onChange={(e) => setSpeed(e.target.value as SpeedId)}
              disabled={streaming}
              className="h-9 rounded-lg border border-line bg-surface px-2 text-xs text-ink lg:h-8 lg:w-full"
            >
              {SPEEDS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </Boundary>

        <Pane
          id="restored"
          side="you"
          eyebrow="Back inside your network"
          title="What you got back"
          className="lg:flex-1"
          footer={
            restoration ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <dl className="flex gap-4">
                  <Stat label="restored" value={restoredCount} />
                  <Stat label="unknown" value={unresolved.length} />
                  {view.kind === "streaming" && <Stat label="chunks" value={`${view.received.length}/${view.total}`} />}
                </dl>
                <span>Restored values are underlined and coloured by type. Hover one to see its placeholder.</span>
              </div>
            ) : undefined
          }
        >
          <div aria-live="polite" aria-busy={streaming} className="sr-only">
            {view.kind === "streaming" ? "Streaming the answer" : view.kind === "done" ? `Answer restored, ${restoredCount} values put back` : ""}
          </div>
          {view.kind === "error" ? (
            <div className="space-y-3">
              <BlockedNotice error={view.error} phase="inbound" />
              {view.error.code === "not_found" && (
                <Button variant="secondary" onClick={onRun} disabled={running}>
                  Mask the document again
                </Button>
              )}
            </div>
          ) : restoration ? (
            <div className="space-y-4">
              <RestoredText segments={restoration.segments} activeKey={activeKey} onActivate={activate} freshFrom={freshFrom} />
              {streaming && <span aria-hidden="true" className="ml-0.5 inline-block h-4 w-2 translate-y-0.5 bg-ink motion-safe:animate-pulse" />}
              {unresolved.length > 0 && view.kind === "done" && (
                <div role="note" className="rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm text-ink">
                  <p className="font-semibold text-warn">Unknown placeholder left as is</p>
                  <p className="mt-1 text-muted">
                    The model produced {unresolved.map((u, i) => (
                      <span key={u}>
                        {i > 0 && ", "}
                        <code className="font-mono text-ink">{u}</code>
                      </span>
                    ))}
                    , which this session never issued. pii-guard doesn't guess: it leaves the token visible so a person can check it.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <EmptyState title="Waiting for the answer" body="Stream the answer to watch the guard put real values back as the chunks arrive, or restore it in one go." />
          )}
        </Pane>
      </div>

      <Popover anchor={activeKey ? anchor : null}>
        {activeKey && <PlaceholderDetails placeholder={activeKey} restored={values.has(activeKey)} />}
      </Popover>
    </div>
  );
}

function PlaceholderDetails({ placeholder, restored }: { placeholder: string; restored: boolean }) {
  const type = tokenize(placeholder)[0];
  const meta = metaFor(type?.kind === "placeholder" ? type.entityType : null);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="inline-flex items-center gap-1.5 font-medium text-ink">
        <span className={["size-2 rounded-full", meta.swatch].join(" ")} />
        {meta.label}
      </span>
      <span>
        {restored ? "restored from" : "placeholder"} <code className="font-mono text-ink">{placeholder}</code>
      </span>
    </div>
  );
}

function RoundTripIntro({ live = false }: { live?: boolean }) {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">
        {live ? "The answer comes back with the masked values restored." : "The answer comes back with the real names in it."}
      </h1>
      <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
        The model writes about placeholders. On the way back, pii-guard swaps them for the original values, even mid-stream, when a placeholder is split across two chunks.
      </p>
    </div>
  );
}

function ChunkStream({ chunks, held }: { chunks: readonly string[]; held: string }) {
  const end = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [chunks.length]);
  return (
    <div className="doc max-h-[26rem] overflow-y-auto" data-testid="chunk-stream">
      {chunks.map((c, i) => (
        <span
          key={i}
          className="animate-chunk rounded-[3px] px-px text-ink odd:bg-model-soft even:bg-surface-2 [box-shadow:inset_-1px_0_0_var(--line-strong)]"
        >
          {c}
        </span>
      ))}
      {held && (
        <span className="ml-1 inline-flex translate-y-[-1px] items-center gap-1 rounded bg-warn-soft px-1.5 font-sans text-[11px] font-semibold text-warn ring-1 ring-warn/40">
          held back
        </span>
      )}
      <span ref={end} />
    </div>
  );
}
