import { useEffect, useRef, useState, type ReactNode } from "react";
import { Placeholder } from "../components/Placeholder";
import { Button } from "../components/ui";
import recording from "../content/agentReplayRecording.json";
import { metaFor } from "../lib/entities";
import { tokenize } from "../lib/placeholders";
import { RECORD, replayValues, streamAt } from "./replayData";

/*
 * The landing's agent-turn replay (LAB-1499): one agent turn through PII Guard, replayed from a
 * recording of the real gateway (fast mode, rules + the published NER) with a scripted stand-in
 * model and fictional data (scripts/record_agent_replay.py). The recording is value-free: the
 * fictional values come back from RECORD below, as the gateway put them back.
 *
 * What it shows that a chat demo can't: a tool result masked on its way to the model, a tool
 * call streamed with placeholders in its arguments and restored before the agent runs it, and
 * a placeholder held back while it is split across stream chunks. With reduced motion it shows
 * the finished turn at once.
 */

const SEND = recording.send_call;
const ANSWER = recording.answer;
// Steps: 0 nothing, 1 task, 2 read_file, 3 masked record, 4..4+S streamed send_email, then
// the answer's chunks, then done.
const SEND_FROM = 4;
const ANSWER_FROM = SEND_FROM + SEND.upstream.length + 1;
const DONE = ANSWER_FROM + ANSWER.upstream.length + 1;
const delayAfter = (step: number): number => {
  if (step < SEND_FROM) return 1100;
  if (step === ANSWER_FROM - 1 || step === DONE - 1) return 1200;
  return 120;
};

function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => globalThis.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const m = globalThis.matchMedia?.(query);
    if (!m) return;
    const on = () => setReduce(m.matches);
    m.addEventListener?.("change", on);
    return () => m.removeEventListener?.("change", on);
  }, []);
  return reduce;
}

/** Masked text: each placeholder as the model sees it. */
function Masked({ text }: { text: string }) {
  return <>{tokenize(text).map((t, i) => t.kind === "text" ? <span key={i}>{t.text}</span> : <Placeholder key={i} text={t.text} entityType={t.entityType} />)}</>;
}

/** Text with each placeholder replaced by its fictional value: restored (green) or still yours (the entity's colour). */
function Valued({ text, values, outgoing = false }: { text: string; values: Map<string, string>; outgoing?: boolean }) {
  return <>{tokenize(text).map((t, i) => {
    if (t.kind === "text") return <span key={i}>{t.text}</span>;
    const value = values.get(t.text);
    if (!value) return <Placeholder key={i} text={t.text} entityType={t.entityType} />;
    return <mark key={i} className={["rounded-sm px-0.5 -mx-0.5 ring-1 ring-inset", outgoing ? metaFor(t.entityType).mark : "bg-restored-soft text-ink ring-restored/45"].join(" ")}>{value}</mark>;
  })}</>;
}

/** A block that keeps the height of its finished content while it streams in (no layout shift). */
function Sized({ final, children }: { final: ReactNode; children: ReactNode }) {
  return <div className="grid min-w-0 font-mono text-2xs leading-relaxed break-words whitespace-pre-wrap text-ink">
    <div aria-hidden="true" className="invisible col-start-1 row-start-1">{final}</div>
    <div className="col-start-1 row-start-1">{children}</div>
  </div>;
}

/** One line of the transcript: who, then what, on your side (plain) or the model's (tinted). */
function Line({ side, label, shown, children }: { side: "you" | "model"; label: string; shown: boolean; children: ReactNode }) {
  return <li className={["grid grid-cols-[5.25rem_minmax(0,1fr)] gap-3 rounded-md px-2.5 py-1.5 transition-opacity duration-300", side === "model" ? "bg-model-soft/60" : "", shown ? "opacity-100" : "opacity-0"].join(" ")}>
    <span className={["pt-px font-mono text-2xs", side === "model" ? "text-model" : "text-guard"].join(" ")}>{label}</span>
    {children}
  </li>;
}

const values = replayValues();

/** The replay card. */
export default function AgentReplay() {
  const reduce = useReducedMotion();
  const [rawStep, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const root = useRef<HTMLElement | null>(null);
  const started = useRef(false);
  // Reduced motion: the finished turn, no animation.
  const step = reduce ? DONE : rawStep;
  const running = !reduce && playing && rawStep < DONE;

  // Start once, when the card is on screen.
  useEffect(() => {
    const el = root.current;
    if (reduce || !el || started.current || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !started.current) { started.current = true; setPlaying(true); io.disconnect(); }
    }, { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, [reduce]);

  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setStep((s) => Math.min(DONE, s + 1)), delayAfter(rawStep));
    return () => clearTimeout(timer);
  }, [running, rawStep]);

  const send = streamAt(SEND.upstream, SEND.agent, Math.max(0, Math.min(SEND.upstream.length, step - SEND_FROM + 1)));
  const answer = streamAt(ANSWER.upstream, ANSWER.agent, Math.max(0, Math.min(ANSWER.upstream.length, step - ANSWER_FROM + 1)));
  const sendFinal = SEND.upstream.join("");
  const answerFinal = ANSWER.upstream.join("");
  const holding = (step >= SEND_FROM && step < ANSWER_FROM - 1 && send.held.includes("[")) || (step >= ANSWER_FROM && step < DONE && answer.held.includes("["));
  const control = running ? "Pause" : step >= DONE ? "Replay" : step === 0 ? "Play" : "Resume";
  function onControl() {
    if (running) { setPlaying(false); return; }
    if (rawStep >= DONE) setStep(0);
    started.current = true;
    setPlaying(true);
  }

  return <figure ref={root} aria-labelledby="replay-title" className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="font-mono text-2xs text-guard">Real gateway · scripted model · fictional data</p>
        <p id="replay-title" className="mt-0.5 text-sm font-medium text-ink">Tool calls masked, answers restored mid-stream</p>
      </div>
      {!reduce && <Button size="sm" onClick={onControl} aria-label={`${control} the replay`}>{control}</Button>}
    </div>
    <figcaption className="sr-only">
      {`A recorded agent turn through the PII Guard gateway, with a scripted model and fictional data. The agent is asked: ${recording.task} The model calls read_file on crm.json. The file holds a fictional customer's name, email and IBAN; the model receives placeholders instead. The model streams a send_email tool call addressed to placeholders, and PII Guard restores the real email and name in the arguments before the agent runs the tool. The model's closing message streams back with placeholders split across chunks; PII Guard holds each split placeholder back until it is complete, then restores it. ${recording.upstream_requests} model requests, no fictional value reached the model.`}
    </figcaption>
    <ol aria-hidden="true" className="mt-4 space-y-1">
      <Line side="you" label="task" shown={step >= 1}><Sized final={recording.task}>{recording.task}</Sized></Line>
      <Line side="model" label="model calls" shown={step >= 2}><Sized final={`${recording.read_call.name}(${recording.read_call.arguments})`}>{`${recording.read_call.name}(${recording.read_call.arguments})`}</Sized></Line>
      <Line side="you" label="tool result" shown={step >= 3}><Sized final={RECORD}><Valued text={recording.masked_record} values={values} outgoing /></Sized></Line>
      <Line side="model" label="model sees" shown={step >= 3}><Sized final={<Masked text={recording.masked_record} />}><Masked text={recording.masked_record} /></Sized></Line>
      <Line side="model" label="model streams" shown={step >= SEND_FROM}><Sized final={<Masked text={sendFinal} />}><Masked text={send.model} /></Sized></Line>
      <Line side="you" label="agent runs" shown={step >= SEND_FROM}><Sized final={<Valued text={sendFinal} values={values} />}><Valued text={send.agent} values={values} /></Sized></Line>
      <Line side="model" label="model streams" shown={step >= ANSWER_FROM}><Sized final={<Masked text={answerFinal} />}><Masked text={answer.model} /></Sized></Line>
      <Line side="you" label="agent sees" shown={step >= ANSWER_FROM}><Sized final={<Valued text={answerFinal} values={values} />}><Valued text={answer.agent} values={values} /></Sized></Line>
    </ol>
    <div className="mt-3 flex min-h-5 flex-wrap items-center justify-between gap-x-4 gap-y-1 text-2xs text-muted sm:text-xs">
      <p aria-hidden="true" className={["inline-flex items-center gap-1.5 transition-opacity", holding ? "opacity-100" : "opacity-0"].join(" ")}><span className="size-1.5 rounded-full bg-guard-dot motion-safe:animate-pulse" />Holding a split placeholder until it’s complete</p>
      <p className="tabular-nums">{recording.upstream_requests} model requests · 0 values reached the model</p>
    </div>
  </figure>;
}
