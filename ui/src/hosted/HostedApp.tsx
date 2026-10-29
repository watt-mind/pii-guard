import { lazy, Suspense, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import demoRecording from "../content/demoRecording.json";
import { createHttpChat, pickDefaultModel, SYSTEM_PROMPT } from "../api/chat";
import type { EntityType } from "../api/types";
import { Boundary } from "../components/Boundary";
import { Legend } from "../components/Legend";
import { MaskedText } from "../components/MaskedText";
import { Pane } from "../components/Pane";
import { Placeholder } from "../components/Placeholder";
import { RestoredText } from "../components/RestoredText";
import { Announcer, Badge, Button, ButtonLink, Card, Field, KeyValues, Logo, Metric, Notice, SegmentedControl, Select, Textarea, ThemeToggle, type BadgeTone } from "../components/ui";
import { useTheme } from "../hooks/useTheme";
import { metaFor } from "../lib/entities";
import { ApiError } from "../api/http";
import { request, recovery, type Account, type DemoResult, type Requester } from "./api";
import { Limits } from "./AccountPanels";
import { YourText } from "./Highlight";
import { friendlyModel, modelName, placeholderCounts, providerLabel, restoredSegments, resetsIn, runsLeft } from "./landing";
import { COMPARED, COMPARISON, HARNESS, IMAGE_LIMITS, IMAGE_PROOF, LATENCY, MEASURED, OPEN_MODELS, PROOF, RUNS, SETS, VISUAL_PLACEHOLDERS, WEAKER } from "./proof";
import AgentReplay from "./AgentReplay";
import { DemoVideo } from "./DemoVideo";
import { SITE_HASHES, SOURCE, useAccount, useHash, type HostedSession } from "./session";
import { useCurrentSection } from "./useCurrentSection";
import { consoleSectionOf } from "./consoleLink";
import { PublicEvaluation } from "./PublicEvaluation";
import { SignedOutConsole } from "./SignedOut";

// Without a return address Easy Auth ends on its own bare "signed in" page (LAB-1425);
// sign-in returns to the console (LAB-1430).
const LOGIN = "/.auth/login/google?post_login_redirect_uri=%2F%23overview";
const LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2F";
const NER_MODEL = "https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base";
const DOCS = `${SOURCE}/blob/develop/docs`;
const SELF_HOST = `${SOURCE}#try-it`;
const MODEL_CARD = `${NER_MODEL}#model-card`;
const CI = `${SOURCE}/actions/workflows/ci.yml`;
const HARNESS_REPORT = `${DOCS}/integrations/harness-matrix-2026-10-29.md`;
const EU_REGULATION = `${DOCS}/eu-regulation.md`;
const META_TERMS = "https://dev.meta.ai/legal/terms-of-service";
// The 3-minute demo video: the slot stays hidden until a URL is configured at build time.
const DEMO_VIDEO_URL = import.meta.env.VITE_PII_GUARD_DEMO_VIDEO_URL || null;

// Below the fold and heavier than the rest of the page: loaded on demand, so the first paint
// stays small (Lighthouse, LAB-1466).
const ImageShowcase = lazy(() => import("./ImageShowcase"));
const ResultsChart = lazy(() => import("./ResultsChart"));

// TODO(owner, LAB-1474): operator name, privacy notice URL and contact address. Until they are
// set the footer points at the repository's issues; never invent a legal entity here.
const OPERATOR: string | null = null;
const PRIVACY_NOTICE_URL: string | null = null;
const CONTACT_URL: string | null = null;

// The default demo state (LAB-1503): a real run of /v1/demo on the hosted preview, recorded by
// scripts/record_demo_run.py. The server's own fictional sample, masked by the real gateway, answered
// by the included Meta model, restored; the same text a live run sends.
type Recorded = Pick<DemoResult, "original" | "masked" | "answer" | "restored" | "entities" | "model">;
const RECORDED = demoRecording.runs as Record<"en" | "hu", Recorded>;
const RECORDED_ON = new Date(`${demoRecording.recorded_at}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
type Language = keyof typeof RECORDED;
const LANGUAGES = [{ value: "en", label: "English" }, { value: "hu", label: "Hungarian" }] as const;

/** The sticky nav's sections, in page order; `wide` ones show from lg up, the rest from md. */
const NAV: readonly { href: string; label: string; wide?: boolean }[] = [
  { href: "#demo", label: "Demo" },
  { href: "#meta", label: "Meta models", wide: true },
  { href: "#images", label: "Images" },
  { href: "#results", label: "Results" },
  { href: "#how", label: "How it works" },
  { href: "#data", label: "Your data", wide: true },
];
/** Every section, for the nav's current-section marker: between two nav entries none is marked. */
const SECTIONS = ["why", "demo", "meta", "europe", "images", "results", "how", "data", "privacy", "account"] as const;

const initialLanguage = (): Language => (globalThis.navigator?.language ?? "").toLowerCase().startsWith("hu") ? "hu" : "en";
const link = "underline underline-offset-4 hover:text-ink";

/** Anonymous visitors get the public page; a signed-in owner gets the console (`console`). */
export function HostedApp({ call = request, console: renderConsole }: { call?: Requester; console?: (session: HostedSession) => ReactNode }) {
  const { account, error, refresh } = useAccount(call);
  const hash = useHash();
  // Signed in earlier on this page, so an anonymous account now means the session ended.
  const [wasSignedIn, setWasSignedIn] = useState(false);
  if (account?.authenticated && !wasSignedIn) setWasSignedIn(true);
  if (renderConsole && account?.authenticated && !SITE_HASHES.has(hash)) return renderConsole({ account, error, refresh, call });
  // A console deep link without a session: say what the screen is and how to get there (LAB-1519).
  const section = renderConsole && account && !account.authenticated ? consoleSectionOf(hash) : null;
  // Evaluation shows only the published benchmarks bundled with the page, so it needs no sign-in
  // (LAB-1533), and it still opens when the account can't be read.
  if (renderConsole && !account?.authenticated && (account || error) && consoleSectionOf(hash) === "evaluation") return <PublicEvaluation loginUrl={account?.login_url || LOGIN} hash="#evaluation" />;
  if (section && account) return <SignedOutConsole section={section} hash={hash} loginUrl={account.login_url || LOGIN} expired={wasSignedIn} />;
  // Back from sign-in: wait for the account rather than flash the public page.
  if (renderConsole && !account && !error && hash !== "" && !SITE_HASHES.has(hash) && hash !== "#account") return <p role="status" className="p-6 text-sm text-muted">Opening your console…</p>;
  return <HostedContent call={call} account={error ? null : account} accountError={error} refresh={refresh} console={Boolean(renderConsole)} />;
}

function HostedContent({ call, account, accountError, refresh, console: hasConsole }: { call: Requester; account: Account | null; accountError: string; refresh: () => Promise<void>; console: boolean }) {
  const [theme, setTheme] = useTheme();
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState("");
  const [quota, setQuota] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [text, setText] = useState(RECORDED[language].original);
  const [editable, setEditable] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);
  // Stepwise progress while a run is in flight. The browser sees one request, so the steps are
  // paced, not measured; the last one completes when the answer arrives.
  useEffect(() => {
    if (!running) return;
    const timers = [700, 1400].map((ms, i) => setTimeout(() => setStep(i + 1), ms));
    return () => timers.forEach(clearTimeout);
  }, [running]);

  const signedIn = Boolean(account?.authenticated);
  const loginUrl = account?.login_url || LOGIN;
  // Sponsorship stays off until the provider authorises it (docs/hosted.md): then a guest has
  // no live run, only the recorded run and the way to sign in.
  const sponsoredOff = account?.limits.sponsored_enabled === false;
  const guestLive = Boolean(account) && !signedIn && !sponsoredOff;
  // Signed in: the included model when it's on; otherwise the owner's first saved provider
  // connection, silently; with neither there is no run, only the way to add a key.
  const ownConnection = signedIn && sponsoredOff ? account?.connections[0] : undefined;
  const needsKey = signedIn && sponsoredOff && !ownConnection;
  const canRun = guestLive || (signedIn && !needsKey);
  // The model's name comes from the server (`included_model`), never from this page (LAB-1466).
  const model = account?.included_model ? modelName(account.included_model) : null;
  const modelOr = (fallback: string) => model ?? fallback;
  const steps = ["Finding personal data", "Swapping it for placeholders", `Waiting for ${ownConnection ? `your ${providerLabel(ownConnection.provider)} model` : modelOr("the model")}`, "Putting the real values back"];

  function reset(nextLanguage = language) {
    setLanguage(nextLanguage); setText(RECORDED[nextLanguage].original); setResult(null); setFailed(false); setQuota(false); setError(""); setAnnounce("");
  }
  async function run() {
    setRunning(true); setStep(0); setError(""); setFailed(false); setQuota(false); setResult(null); setAnnounce("Running the live demo…");
    try {
      let next: DemoResult;
      // The curated sample goes through /v1/demo (included model only); your text, or any run
      // through your own connection, goes through the gateway's chat endpoint.
      if (signedIn && (editable || ownConnection)) {
        const abort = new AbortController(); controller.current = abort;
        const timeout = setTimeout(() => abort.abort(), 180_000);
        const doFetch: typeof fetch = (input, init) => {
          const headers = new Headers(init?.headers);
          headers.set("X-PII-Guard-Mode", "fast");
          if (ownConnection) headers.set("X-PII-Guard-Connection", ownConnection.id);
          return fetch(input, { ...init, credentials: "same-origin", headers });
        };
        try {
          const chat = createHttpChat({ fetch: doFetch });
          const models = await chat.listModels!(abort.signal);
          const picked = pickDefaultModel(models, null);
          if (!picked) throw new Error("No available model");
          const turn = await chat.send({ model: picked, mode: "fast", language, sessionId: null, signal: abort.signal, messages: [{ role: "system", content: SYSTEM_PROMPT }, { role: "user", content: text }] });
          if (!turn.answer || !turn.maskedAnswer || !turn.maskedMessages.length || turn.finishReason === "length") throw new Error("Incomplete answer");
          next = { sample_id: "custom", language, original: text, masked: turn.maskedMessages.filter((m) => m.role !== "system").map((m) => m.content).join("\n"), answer: turn.maskedAnswer, restored: turn.answer, entities: [], model: picked, session_id: turn.sessionId, request_id: "" };
        } finally { clearTimeout(timeout); controller.current = null; }
      } else {
        next = await call<DemoResult>("/v1/demo", { sample_id: `${language}-support`, language });
        if (![next.original, next.masked, next.answer, next.restored, next.model].every((s) => typeof s === "string" && s.length > 0) || !Array.isArray(next.entities) || !next.entities.every((entity) =>
          entity !== null && typeof entity === "object" && Number.isInteger(entity.start) && Number.isInteger(entity.end) &&
          entity.start >= 0 && entity.end > entity.start && typeof entity.type === "string" && entity.type.length > 0,
        )) throw new Error("Incomplete demo");
      }
      setResult(next);
      const types = placeholderCounts(next.masked).map(([type]) => metaFor(type).label);
      setAnnounce(`Live result ready: ${types.length ? `${types.join(", ")} masked, ` : ""}answer restored. Model: ${friendlyModel(next.model)}.`);
      void refresh();
    } catch (e) { setFailed(true); setQuota(e instanceof ApiError && e.status === 429); setAnnounce(""); setError(recovery(e, "site")); }
    finally { setRunning(false); }
  }

  // A run in flight or a failed one keeps the recorded run on screen: a live failure never blanks it.
  const shown: Recorded | null = result ?? (editable && signedIn && !needsKey ? null : RECORDED[language]);
  const counts = shown ? placeholderCounts(shown.masked) : [];
  const legend = new Map<EntityType, number>(counts.filter((c): c is [EntityType, string, number] => c[0] !== null).map(([type, , n]) => [type, n]));
  const masked = counts.reduce((sum, [, , n]) => sum + n, 0);
  const badge: { tone: BadgeTone; text: string } = running ? { tone: "neutral", text: "Live run in progress" } : result ? { tone: "live", text: `Live result · answered by ${friendlyModel(result.model)}` } : failed ? { tone: "failed", text: "Live run didn’t finish · showing the recorded run" } : { tone: "neutral", text: "Recorded run · real model · fictional data" };
  const heroCta = signedIn ? "Run your own text" : guestLive ? "Run the live demo" : "See the demo";
  // A guest with a live run gets it from the hero in one press (LAB-1479): the link still points
  // at #demo, so without JS, signed in or paused it stays a plain anchor.
  const startsRun = guestLive && !running && !quota;
  function heroRun(e: MouseEvent<HTMLAnchorElement>) {
    if (!startsRun || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    document.getElementById("demo")?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    document.getElementById("demo-heading")?.focus({ preventScroll: true });
    void run();
  }

  const current = useCurrentSection(SECTIONS);

  return <div className="min-h-dvh bg-canvas text-sm text-ink">
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">Skip to content</a>
    <header className="sticky top-0 z-30 bg-canvas">
      <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-4 px-4 sm:px-6 lg:h-12 lg:px-10">
        <a href="#" className="flex h-9 min-w-0 items-center gap-2.5 rounded-sm text-base font-medium text-ink"><Logo />PII Guard</a>
        <nav aria-label="Main navigation" className="flex min-w-0 items-center gap-5">
          {NAV.map((item) => <a key={item.href} aria-current={current === item.href.slice(1) ? "location" : undefined} className={["hidden text-muted hover:text-ink aria-[current]:text-ink aria-[current]:underline aria-[current]:decoration-guard aria-[current]:decoration-2 aria-[current]:underline-offset-[6px]", item.wide ? "lg:inline" : "md:inline"].join(" ")} href={item.href}>{item.label}</a>)}
          <a className="hidden text-muted hover:text-ink md:inline" href={SELF_HOST}>Self-host</a>
          <SectionMenu current={current} />
          {signedIn ? <ButtonLink href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Console" : "Your account"}</ButtonLink> : <ButtonLink href={loginUrl}>Console</ButtonLink>}
        </nav>
      </div>
      <div aria-hidden="true" className="header-hairline" />
    </header>
    <main id="main" tabIndex={-1} className="mx-auto max-w-[1280px] space-y-16 px-4 pb-16 focus:outline-none sm:px-6 lg:space-y-20 lg:px-10">
      <section aria-labelledby="intro-heading" className="grid items-center gap-10 pt-10 sm:pt-16 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:pt-20">
        <div className="min-w-0 space-y-6">
          <p className="font-mono text-2xs text-muted sm:text-xs">Open source · OpenAI-compatible · Built on Meta’s XLM-RoBERTa, Muse Glimmer, Muse Spark and SAM&nbsp;3.1</p>
          <h1 id="intro-heading" className="text-3xl leading-tight font-medium text-balance text-ink sm:text-5xl"><span className="block">Send the work to the model.</span><span className="block">Keep the people out of it.</span></h1>
          <p className="max-w-2xl text-sm text-pretty text-muted sm:text-base"><span className="text-ink">Legal, HR and finance teams in the EU often can’t send case files to a hosted model, so their agents stay off the useful work.</span> PII Guard is a privacy gateway: personal data in text, tool calls and images becomes placeholders before the request leaves, and the real values come back in the answer.</p>
          <div className="max-w-2xl space-y-3">
            <dl aria-label="Measured results" className="grid grid-cols-3 gap-3 sm:gap-6">{PROOF.map((p) => <Metric key={p.label} size="hero" label={<><span className="sm:hidden">{p.short}</span><span className="max-sm:hidden">{p.label}</span></>} value={p.value} hint={p.hint} />)}</dl>
            <p className="text-xs text-muted">{MEASURED} · compared with the open-source tools Presidio, PrivAiTe and LLM Guard · <a className={[link, "whitespace-nowrap"].join(" ")} href={`${DOCS}/benchmarks.md`}>All results ↗</a></p>
          </div>
          <div className="flex flex-wrap items-center gap-3"><ButtonLink variant="primary" href="#demo" onClick={heroRun}>{heroCta}</ButtonLink><ButtonLink href={SELF_HOST}>Self-host it ↗</ButtonLink></div>
          <ul aria-label="Proof" className="flex max-w-2xl flex-wrap gap-x-4 gap-y-0.5 border-t border-line pt-4 text-xs text-muted">
            <ProofItem href={HARNESS_REPORT}>Tested with {HARNESS.agents.length} real coding agents</ProofItem>
            <ProofItem href={`${DOCS}/benchmarks.md#run-log`}>{RUNS.label} committed benchmark runs</ProofItem>
            <ProofItem href={NER_MODEL}>Published open NER model</ProofItem>
            <ProofItem href={`${SOURCE}/blob/develop/LICENSE`}>Apache-2.0</ProofItem>
            <ProofItem href={CI}>CI and tests</ProofItem>
          </ul>
        </div>
        <AgentReplay />
      </section>

      <section id="why" aria-labelledby="why-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="why-heading" eyebrow="Why PII Guard" title="Made for agents, measured in the open." />
        <ul aria-label="What makes it different" className="grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-5 border-y border-line py-6 sm:grid-cols-2 lg:grid-cols-5">
          <Differentiator href="#how" title="Agents, not just chat">Prompts, tool calls and streamed answers. Tested on the coding agents {HARNESS.agents.join(", ").replace(/, (?=[^,]*$)/, " and ")}: {HARNESS.requests} requests, {HARNESS.leaked} values leaked, {HARNESS.refused} turns refused.</Differentiator>
          <Differentiator href="#how" title="No LLM, no GPU to mask">Validated rules and our open NER on the CPU, adding {LATENCY.value} per request (p50). Nothing is sent out to find personal data.</Differentiator>
          <Differentiator href="#how" title="EU languages, grammar-aware">Hungarian names change with every case; the ending stays outside the placeholder, so the model still writes correct sentences.</Differentiator>
          <Differentiator href="#images" title="One person, one placeholder">The same placeholder in the text and on a scanned ID: {VISUAL_PLACEHOLDERS.recall}&nbsp;% of image values matched, no false merges.</Differentiator>
          <Differentiator href="#results" title="Measured in the open">Public test sets, {COMPARED.tools} other tools and {COMPARED.openModels} other open NER models, {RUNS.label} committed runs. Our NER is published.</Differentiator>
        </ul>
      </section>

      <section id="demo" aria-labelledby="demo-heading" aria-busy={running} className="scroll-mt-20 space-y-4">
        <SectionHead id="demo-heading" eyebrow="Demo" focusable title="See exactly what the model sees." lead={`One request, four steps: your text, what ${modelOr("the model")} sees, its answer, and that answer with the real values back.`} />
        {DEMO_VIDEO_URL && <DemoVideo url={DEMO_VIDEO_URL} />}
        <Card aria-label="Run the example">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-3"><p aria-hidden="true" className="text-sm font-medium text-ink">Sample</p><SegmentedControl label="Sample language" options={LANGUAGES.map((l) => ({ ...l, disabled: running }))} value={language} onChange={(v) => reset(v as Language)} /></div>
            {signedIn && !needsKey && <Field label="Input" className="min-w-36 max-w-56 flex-1"><Select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">The sample</option><option value="custom">Your text</option></Select></Field>}
            {canRun && !quota && <Button variant="primary" busy={running} disabled={!running && editable && !text.trim()} onClick={() => void run()}>{running ? "Running…" : failed ? "Try again" : editable ? "Run your text" : "Run the live demo"}</Button>}
            {result && !running && <Button onClick={() => reset()}>Back to the recorded run</Button>}
            <div className="basis-full sm:basis-auto sm:self-center"><Badge tone={badge.tone}>{badge.text}</Badge></div>
            {canRun && !running && !quota && <p className="w-full text-xs text-muted sm:w-auto sm:self-center">{ownConnection ? <>Runs through your {providerLabel(ownConnection.provider)} connection.{hasConsole && <> <a className={link} href="#connect">Change it in Connect</a></>}</> : <>Runs on {modelOr("Meta’s model")} · no key needed{account && runsLeft(account) && <> · <span className="tabular-nums">{runsLeft(account)}</span></>}</>}</p>}
          </div>
          <div className="mt-4 space-y-3 empty:hidden">
            {account && !signedIn && sponsoredOff && <Notice title="Free runs are paused right now" action={<ButtonLink variant="primary" href={loginUrl}>Sign in to run your own text</ButtonLink>}>The recorded run below shows the same flow, answered by a real model.</Notice>}
            {needsKey && <Notice title="Free runs are paused right now" action={<ButtonLink variant="primary" href={hasConsole ? "#connect" : "#account"}>Add a model key</ButtonLink>}>Add your own model key to run it, or follow the recorded run below.</Notice>}
            {!account && accountError && <Notice title="The live service isn’t reachable">The recorded run below still shows the whole flow. <a className={link} href="#account">Check the connection ↓</a></Notice>}
            {running && <div className="rounded-lg border border-line bg-surface-2 p-3 sm:p-4">
              <ol aria-label="Live run progress" className="flex flex-wrap gap-x-6 gap-y-2">{steps.map((label, i) => <li key={label} data-state={i < step ? "done" : i === step ? "active" : "todo"} className={["inline-flex items-center gap-2", i === step ? "font-medium text-ink" : "text-muted"].join(" ")}><span aria-hidden="true" className={["size-2 rounded-full border", i < step ? "border-guard-dot bg-guard-dot" : i === step ? "border-ink bg-ink motion-safe:animate-pulse" : "border-field"].join(" ")} />{label}{i === step && <span className="sr-only"> (in progress)</span>}</li>)}</ol>
              <p className="mt-2 text-xs text-muted">Usually a few seconds. The first run after a quiet spell can take up to a minute while the service wakes up.</p>
            </div>}
            {error && <Notice tone="danger" live action={quota && !signedIn ? <ButtonLink variant="primary" href={loginUrl}>Sign in for more runs</ButtonLink> : undefined}>{error}{quota && account && resetsIn(account) && <> Free runs reset {resetsIn(account)}.</>}</Notice>}
          </div>
        </Card>
        <Announcer message={announce} />
        <div data-flow className={["space-y-4 transition-opacity", running ? "opacity-55" : ""].join(" ")}>
          <div className="flex flex-col lg:flex-row lg:items-stretch">
            <Pane headingLevel={3} id="demo-input" side="you" eyebrow="Stays with PII Guard" title="Your text" className="lg:flex-1" footer={result ? "A real guard and model produced this. Check the masked request: detection can miss values, and this is pseudonymization, not anonymization." : shown ? `Recorded ${RECORDED_ON} on this hosted preview: the real gateway masked the server’s fictional sample and ${model ? modelName(shown.model) : "Meta’s model"} answered. A live run sends the same sample again.` : "Runs through the real gateway and model when you press Run your text."}>
              {shown ? <YourText text={shown.original} masked={shown.masked} entities={shown.entities.length ? shown.entities : undefined} /> : <Field label="Your text" hint="PII Guard receives this text in full on Azure in Sweden Central. Use fictional data while you evaluate."><Textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></Field>}
            </Pane>
            <Boundary direction="outbound" label="PII Guard boundary: only this crosses to the model">
              {shown && <dl className="text-center"><Metric label="masked" value={masked} className="min-w-12" /></dl>}
            </Boundary>
            <Pane headingLevel={3} id="demo-sent" side="model" eyebrow="Placeholders only" title="Sent to the model" className="lg:flex-1" footer={legend.size > 0 ? <Legend counts={legend} /> : undefined}>
              {shown ? <MaskedText text={shown.masked} /> : <p className="text-sm text-muted">Write or paste your text, then run it to see each step.</p>}
            </Pane>
          </div>
          <div className="flex flex-col lg:flex-row lg:items-stretch">
            <Pane headingLevel={3} id="demo-answer" side="model" eyebrow="Still placeholders" title="Model answer" className="lg:flex-1">
              {shown ? <MaskedText text={shown.answer} /> : <p className="text-sm text-muted">The model’s answer appears here.</p>}
            </Pane>
            <Boundary direction="inbound" label="PII Guard boundary: placeholders are restored on the way back" />
            <Pane headingLevel={3} id="demo-restored" side="you" eyebrow="Real values put back" title="Restored answer" className="lg:flex-1">
              {shown ? <RestoredText segments={restoredSegments(shown)} /> : <p className="text-sm text-muted">The answer with the real values appears here.</p>}
            </Pane>
          </div>
          <p className="text-xs text-muted">Blue marks a value and the placeholder that replaced it; green marks a value PII Guard put back.</p>
        </div>
      </section>

      <section id="meta" aria-labelledby="meta-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="meta-heading" eyebrow="Built on Meta models" title="Open weights wherever real data goes. Hosted models see placeholders." lead="Anything that sees real personal data is an open-weight model you can run yourself." />
        <ul aria-label="Meta models and what each does" className="grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
          <MetaModel name="XLM-RoBERTa" where="Inside PII Guard, CPU" role={<>The base of our NER, fine-tuned for personal data. Runs on every request. <a className={link} href={NER_MODEL}>Published ↗</a></>} />
          <MetaModel name="Muse Glimmer 30B" where="Open weights, served on Modal" role="The teacher: it labeled 4,964 fictional documents, and our NER was distilled from its labels." />
          <MetaModel name="Muse Spark Open" where="Open weights, on Baseten" role="The opt-in audit detector, and the red team that tries to re-identify masked text." />
          <MetaModel name="SAM 3.1" where="Self-hosted installs" role="Finds signatures on scans, so they’re masked along with faces and ID photos." />
          <MetaModel name={modelOr("Muse Spark")} where="Meta Model API" role="Answers in this demo. It only ever sees placeholders." />
        </ul>
      </section>

      <section id="europe" aria-labelledby="europe-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="europe-heading" eyebrow="Why Europe" title="What EU rules ask, and what PII Guard does." />
        <ul aria-label="EU rules and what PII Guard does" className="grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          <EuCard title="Minimize before you send" href={`${EU_REGULATION}#minimization-and-pseudonymization`}>GDPR requires data minimization (Art. 5) and lists pseudonymization among example design and security measures (Art. 25, 32). PII Guard swaps names and IDs for placeholders before the prompt leaves.</EuCard>
          <EuCard title="Less personal data crossing borders" href={`${EU_REGULATION}#international-transfers`}>Non-EU model providers raise Chapter V transfer questions. PII Guard reduces the personal data that reaches them: placeholders go out, the mapping stays with your guard. Your transfer obligations remain.</EuCard>
          <EuCard title="Built for regulated work" href={`${EU_REGULATION}#sector-rules`}>Lawyers’ secrecy, employee data (GDPR Art. 88) and DORA’s ICT third-party rules all bear on what reaches an outside vendor. PII Guard lists every call in Logs, outbound check included.</EuCard>
        </ul>
        <p className="max-w-3xl text-xs text-muted">A technical measure, not legal advice or a compliance feature: pseudonymized data can still be personal data, and you still need your own DPIA, agreements and transfer assessment. <a className={link} href={`${EU_REGULATION}#what-we-dont-claim`}>What we don’t claim ↗</a></p>
        <div id="for" className="scroll-mt-20 space-y-3">
          <h3 className="text-sm font-medium text-ink">Who it’s for: agents that work on people’s files</h3>
          <Card as="div">
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-5 md:grid-cols-3 md:gap-0 md:divide-x md:divide-line">
              <Audience title="Legal" task="Summarize the case file and draft the reply to opposing counsel.">Parties, addresses and case-file IDs are masked; the model sees <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" />, not your client, and the draft comes back with the name.</Audience>
              <Audience title="HR" task="Answer this employee’s leave request from their folder.">Names, ID numbers, addresses and dates of birth are masked on the way out, in tool results as well as in the prompt.</Audience>
              <Audience title="Finance and back office" task="Match these invoices to the account letters and flag the gaps.">IBANs and tax IDs are caught by validated rules with checksums; names and companies by the NER.</Audience>
            </ul>
          </Card>
        </div>
      </section>

      <section id="images" aria-labelledby="images-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="images-heading" eyebrow="Images" title="Images too: faces blocked, ID details tokenized." lead="Text-only gateways pass screenshots and scans through untouched. PII Guard blocks faces and ID photos and covers each printed detail with a placeholder, the same one that person gets in your text, so the model can still answer." />
        <Suspense fallback={<div className="h-[420px] rounded-xl border border-line bg-surface" aria-hidden="true" />}><ImageShowcase /></Suspense>
        <p className="max-w-3xl text-xs text-muted">Through the gateway, the model receives the masked image and its masked transcript. This hosted preview masks images and returns them to you, never to a model,, with faces, ID photos and signatures found on the server itself. {signedIn && hasConsole ? <a className={link} href="#playground/images">Try your own image in the Playground</a> : <><a className={link} href={loginUrl}>Sign in</a> to try your own image.</>}</p>
        <div aria-labelledby="images-proof-heading" role="group" className="grid grid-cols-[minmax(0,1fr)] gap-x-6 gap-y-4 border-y border-line py-5 lg:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,1fr))]">
          <div className="min-w-0">
            <h3 id="images-proof-heading" className="text-sm font-medium text-ink">Measured on images</h3>
            <p className="mt-1 text-xs text-muted">Portraits and signatures: {IMAGE_LIMITS.ids} official specimen IDs from {IMAGE_LIMITS.countries} countries, self-hosted, IoU ≥ 0.5. Runs of 27 Oct 2026. Printed text on real ID scans is still the weak spot (<a className={link} href="#privacy">limits</a>). <a className={link} href={`${DOCS}/benchmarks.md#image-masking`}>Details ↗</a></p>
          </div>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:col-span-3">{IMAGE_PROOF.map((p) => <Metric key={p.label} label={p.label} value={p.value} hint={p.hint} />)}</dl>
        </div>
      </section>

      <section id="results" aria-labelledby="results-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="results-heading" eyebrow="Results" title="The lowest leak rate on each test set below." lead="Committed runs of 27–28 Oct 2026 on fictional and public data. Leak: personal values that still reach the model; F1 also counts over-masking. The sets are small, so treat a gap of a point or two as noise; where PII Guard is weaker is under Limits." />
        <div className="grid grid-cols-[minmax(0,1fr)] items-stretch gap-6 lg:grid-cols-2">
          <Card title="Leak rate against detection time" headingLevel={3} subtitle="Hand-written German, English and Hungarian set (51 docs). Down and left is better. Time is detection per document, measured where each tool ran.">
            <Suspense fallback={<div className="h-[340px] rounded-lg bg-surface-2" aria-hidden="true" />}><ResultsChart /></Suspense>
          </Card>
          <Card title="Leak and F1 by dataset" headingLevel={3} subtitle="Leak: labeled personal values that still reach the model (lower is safer). F1: detection accuracy (higher is better)." className="flex flex-col">
            <div tabIndex={0} role="region" aria-label="Leak and F1 by dataset, scrollable" className="hidden overflow-x-auto rounded-md sm:block">
              <table className="w-full min-w-[28rem] border-collapse text-sm">
                <caption className="sr-only">Leak rate and F1 in percent, by dataset, for PII Guard and three comparison tools</caption>
                <thead><tr className="border-b border-line text-xs text-muted"><th scope="col" className="py-2 pr-3 text-left font-normal">System</th>{SETS.map((set) => <th key={set} scope="col" className="px-2 py-2 text-right font-normal last:pr-0">{set}<span className="block">leak · F1</span></th>)}</tr></thead>
                <tbody>{COMPARISON.map((row) => <tr key={row.system} className="border-b border-line last:border-0"><th scope="row" className={["py-2 pr-3 text-left", row.ours ? "font-medium" : "font-normal"].join(" ")}>{row.system}</th>{row.leak.map((v, i) => <td key={i} className={["px-2 py-2 text-right whitespace-nowrap tabular-nums last:pr-0", row.ours ? "font-medium text-ink" : "text-muted"].join(" ")}>{v}&nbsp;% · {row.f1[i]}&nbsp;%</td>)}</tr>)}</tbody>
              </table>
            </div>
            <div className="space-y-5 sm:hidden">{SETS.map((set, i) => <ResultTable key={set} caption={set} columns={["Leak", "F1"]} rows={COMPARISON.map((row) => ({ name: row.system, ours: row.ours, values: [row.leak[i]!, row.f1[i]!] }))} />)}</div>
            <p className="mt-3 text-xs text-muted">PII Guard runs of 28 Oct 2026, the other tools 27 Oct 2026. CEE-PII and Nemotron-PII are public test splits PII Guard was not trained on.</p>
            <div className="mt-auto border-t border-line pt-4">
              <p className="text-muted"><span className="font-medium text-ink">Against {COMPARED.openModels} other open PII models</span>, with the same rules around each: ours leaks {OPEN_MODELS[0].leak}&nbsp;%. The closest, {OPEN_MODELS[1].model}, leaks {OPEN_MODELS[1].leak}&nbsp;% and masks about nine times as much text that isn’t personal data ({OPEN_MODELS[1].over}&nbsp;% against {OPEN_MODELS[0].over}&nbsp;%).</p>
              <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">{hasConsole && <a className={link} href="#evaluation">Open the Evaluation page</a>}<a className={link} href={`${DOCS}/benchmarks.md`}>All benchmark results ↗</a><a className={link} href={`${DOCS}/evaluation.md`}>How we measure ↗</a><a className={link} href={MODEL_CARD}>NER model card ↗</a></p>
            </div>
          </Card>
        </div>
      </section>

      <section id="how" aria-labelledby="how-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="how-heading" eyebrow="How it works" title="Live in three steps." lead="An OpenAI-compatible gateway (Chat Completions and Responses) between your agent and the model provider, tested with Codex, OpenCode, Muse Code, pi and the OpenAI SDK." />
        <ol aria-label="Live in three steps" className="grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <Step n={1} title="Change one base URL.">
            <pre tabIndex={0} aria-label="Python client example" className="mt-3 overflow-x-auto rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-ui text-ink"><code>{"client = OpenAI(\n    base_url=\"https://<your-pii-guard>/v1\",\n    api_key=\"…\",\n)"}</code></pre>
            <p className="mt-2 text-xs"><a className={link} href={`${DOCS}/integrations/README.md`}>Integration guides ↗</a></p>
          </Step>
          <Step n={2} title="Masking and restoring happen automatically: streaming, tool calls, images.">Prompts, tool definitions, arguments and results are masked on the way out; the answer is restored as it streams, even when a placeholder is split across chunks. If masking fails, the request isn’t sent.</Step>
          <Step n={3} title="See every request in Logs, with its outbound check result.">What the model received, and the re-check before it left: a request is blocked if a known value survived masking.</Step>
        </ol>
      </section>

      <section id="data" aria-labelledby="data-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="data-heading" eyebrow="Your data" title="What happens to your data here." lead="This covers the hosted preview. If you self-host, all of it stays on your own servers." />
        <Card>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-x-10 gap-y-2 lg:grid-cols-2">
            <KeyValues items={[
              { label: "Where", value: "Microsoft Azure, Sweden Central (EU). Processed in memory. No content archive, and no backup of the mappings. Azure operators can access process memory." },
              { label: "As a guest", value: `You can’t type anything. A fixed, fictional sample is masked here, and only the masked version goes to ${modelOr("Meta’s model")}, when free runs are on.` },
              { label: "Signed in", value: `Google receives your sign-in (name, email, profile). PII Guard receives your text in full; only the masked text goes to ${modelOr("Meta’s model")} or to the provider you connect.` },
            ]} />
            <KeyValues items={[
              { label: "Images", value: "Signed in only. Read and masked inside the service: faces and ID photos are covered, and signatures and stamps stay visible. Images are never stored or sent to a model." },
              { label: "How long", value: "Placeholder mappings expire after 1 hour without use. Your last 50 masked requests are kept in memory for your activity log. A restart clears both. Expiry makes them unavailable; it doesn’t prove the memory is erased." },
              { label: "What Meta receives", value: <>Masked text only. The <a className={link} href={META_TERMS}>Meta Model API terms ↗</a> exclude training on it (section 5.1) but allow retention as needed (section 4.4), and processing there isn’t guaranteed to stay in the EU.</> },
            ]} />
          </div>
          <p className="mt-4 text-xs text-muted"><a className={link} href={`${DOCS}/hosted.md`}>Full processing and retention details ↗</a></p>
        </Card>
      </section>

      <section id="privacy" aria-labelledby="privacy-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="privacy-heading" eyebrow="Limits" title="What PII Guard doesn’t promise." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-2 lg:grid-cols-3">
          <Card title="Detection can miss" headingLevel={3}><p className="text-muted">A missed value goes to the model. That’s why we publish leak rates and show you the masked request.</p></Card>
          <Card title="Context can identify" headingLevel={3}><p className="text-muted">Even with names removed, surrounding detail can point to a person.</p></Card>
          <Card title="It pseudonymizes; it doesn’t anonymize" headingLevel={3}><p className="text-muted">The data is still personal data, and PII Guard reduces exposure. Using it doesn’t by itself make a deployment compliant with any law.</p></Card>
          <Card title="Remote detectors join your trust boundary" headingLevel={3}><p className="text-muted">If you enable one, it sees originals. Don’t submit highly sensitive data, or content you aren’t authorized to process.</p></Card>
          <Card title="Weaker on some text" headingLevel={3}>
            <ul className="grid gap-2">
              <Point title="Finance text.">{WEAKER.gretel}&nbsp;% leak on Gretel finance, level with Presidio ({WEAKER.gretelPresidio}&nbsp;%).</Point>
              <Point title="Over-masking.">Reference numbers without a cue word can be masked as IDs ({WEAKER.ceeOverMasking}&nbsp;% on CEE-PII).</Point>
              <Point title="Other EU languages.">Trained on Hungarian, German and English; on EU legal text in 21 languages it leaks {WEAKER.mapaLeak}&nbsp;%.</Point>
            </ul>
          </Card>
          <Card title="Printed text on ID scans" headingLevel={3}><p className="text-muted">On {IMAGE_LIMITS.ids} official specimen IDs, {IMAGE_LIMITS.all}&nbsp;% of all labeled regions are covered (Presidio Image Redactor: {IMAGE_LIMITS.presidio}&nbsp;%). Printed text alone: {IMAGE_LIMITS.text}&nbsp;%. Faces and ID photos are the strong part; read the masked transcript before you rely on it.</p></Card>
        </div>
        <p className="text-xs text-muted"><a className={link} href={`${DOCS}/privacy-model.md`}>Read the privacy model ↗</a></p>
      </section>

      <section id="account" aria-labelledby="account-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="account-heading" eyebrow="Get started" title="Try it now. Connect your app when you’re ready." lead={!account && accountError ? "The live service isn’t reachable right now. You can still self-host it, or come back to run the live demo." : signedIn ? "You’re signed in. Your projects, endpoints, model connections and activity are in the console." : sponsoredOff ? "Free runs are paused right now. Sign in with Google to run your own text with your own model key, create projects and point your app at your own PII Guard address." : "No sign-in needed for the live demo. Sign in with Google to run your own text, create projects and point your app at your own PII Guard address."} />
        <div className="flex flex-wrap items-center gap-3">
          {signedIn ? <>{hasConsole && <ButtonLink variant="primary" href="#overview">Open console</ButtonLink>}<ButtonLink variant="ghost" href={account?.logout_url || LOGOUT}>Sign out</ButtonLink></> : <>{startsRun && <ButtonLink variant="primary" href="#demo" onClick={heroRun}>Run the live demo ↑</ButtonLink>}<ButtonLink variant={startsRun ? "secondary" : "primary"} href={loginUrl}>Sign in with Google</ButtonLink><ButtonLink href={SELF_HOST}>Self-host it ↗</ButtonLink></>}
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-2">
          <Card title="Hosted preview" subtitle="For evaluation · we run the guard" headingLevel={3} aria-label="Hosted preview: your runs and the server limits">
            <div className="space-y-4">
              <KeyValues items={[
                { label: "Your originals", value: "Our service on Azure, Sweden Central (EU), in memory." },
                { label: "What leaves", value: `Masked text, to ${modelOr("Meta’s model")} or the provider you connect.` },
              ]} />
              {accountError ? <Notice tone="danger" live action={<Button size="sm" onClick={() => void refresh()}>Reconnect to API</Button>}>{accountError}</Notice> : !account ? <p className="text-muted">Checking live availability…</p> : <>
                {(!sponsoredOff || signedIn) && <dl className="grid max-w-md grid-cols-2 gap-4 border-t border-line pt-4">
                  {typeof account.limits.requests_per_day === "number"
                    ? <Metric label={signedIn ? "Runs left today" : "Free runs left today"} value={Math.max(0, account.limits.requests_per_day - account.usage.requests_today)} suffix={`of ${account.limits.requests_per_day}`} />
                    : <Metric label="Runs today" value={account.usage.requests_today} />}
                  <Metric label="Resets" value={resetsIn(account) ?? "—"} />
                </dl>}
                <Limits account={account} hideZero />
                <p className="text-xs text-muted">A restart clears sessions and model connections. Model keys stay with the service, never in your browser.</p>
              </>}
            </div>
          </Card>
          <Card title="Self-hosted" subtitle="Open source · you run it" headingLevel={3}>
            <KeyValues items={[
              { label: "Your originals", value: "Your own servers. Use local detectors to keep all raw processing local." },
              { label: "What leaves", value: "Masked text, to the model you choose." },
              { label: "Who runs it", value: <>You, under Apache-2.0. One command starts it:<code className="mt-1 block font-mono text-ui">uvx --from wattmind-pii-guard pii-guard up</code></> },
            ]} />
          </Card>
        </div>
      </section>
    </main>
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-[1280px] gap-4 px-4 py-8 sm:px-6 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <a href="#" className="flex h-9 items-center gap-2.5 rounded-sm text-base font-medium text-ink"><Logo />PII Guard</a>
          <ThemeToggle theme={theme} onTheme={setTheme} />
        </div>
        <p className="text-muted">Open-source privacy gateway for AI agents. Every example on this page is fictional.</p>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-2">
          <a className="text-ink hover:underline" href={SOURCE}>Source code</a>
          <a className="text-ink hover:underline" href={SELF_HOST}>Self-host</a>
          <a className="text-ink hover:underline" href={`${DOCS}/integrations/README.md`}>Integrate</a>
          <a className="text-ink hover:underline" href="#data">Your data</a>
          <a className="text-ink hover:underline" href={`${DOCS}/benchmarks.md`}>Benchmarks</a>
          {PRIVACY_NOTICE_URL && <a className="text-ink hover:underline" href={PRIVACY_NOTICE_URL}>Privacy notice</a>}
          <a className="text-ink hover:underline" href={CONTACT_URL ?? `${SOURCE}/issues`}>{CONTACT_URL ? "Contact" : "Questions and issues"}</a>
        </nav>
        <p className="text-xs text-muted">Apache-2.0 · Built for the Meta Global AI Developer Hackathon 2026</p>
        {OPERATOR && <p className="text-xs text-muted">Operated by {OPERATOR}.</p>}
      </div>
    </footer>
  </div>;
}

/**
 * A landing section's heading: a mono eyebrow that names the section in the nav's words, the
 * landing's 24→30/500 section title (one step above the console's page title, so a section never
 * reads at card-title weight) and a muted lead.
 */
function SectionHead({ id, eyebrow, title, lead, focusable }: { id: string; eyebrow: string; title: string; lead?: string; focusable?: boolean }) {
  return <div className="max-w-3xl">
    <p className="font-mono text-xs text-guard">{eyebrow}</p>
    <h2 id={id} tabIndex={focusable ? -1 : undefined} className="mt-2 text-2xl font-medium text-balance text-ink focus:outline-none sm:text-3xl">{title}</h2>
    {lead && <p className="mt-3 text-sm text-pretty text-muted sm:text-base">{lead}</p>}
  </div>;
}

/**
 * The section menu below md, where the nav's links don't fit (L1 carryover 3): a disclosure that
 * closes when a link is followed, on Escape (focus back on its toggle), on a tap outside it and
 * when the page scrolls, so it never sits over the content.
 */
function SectionMenu({ current }: { current: string | null }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const menu = ref.current;
    if (!menu) return;
    let openedAt = 0;
    const close = () => menu.removeAttribute("open");
    const onToggle = () => { openedAt = scrollY; };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && menu.open) { close(); menu.querySelector("summary")?.focus(); } };
    const onPointer = (e: PointerEvent) => { if (menu.open && !menu.contains(e.target as Node)) close(); };
    const onScroll = () => { if (menu.open && Math.abs(scrollY - openedAt) > 48) close(); };
    menu.addEventListener("toggle", onToggle);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    addEventListener("scroll", onScroll, { passive: true });
    return () => { menu.removeEventListener("toggle", onToggle); document.removeEventListener("keydown", onKey); document.removeEventListener("pointerdown", onPointer); removeEventListener("scroll", onScroll); };
  }, []);
  return <details ref={ref} className="group relative md:hidden">
    <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 rounded-md px-2 text-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink [&::-webkit-details-marker]:hidden">Sections<svg aria-hidden="true" viewBox="0 0 16 16" className="size-3.5 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m4 6 4 4 4-4" /></svg></summary>
    <ul className="absolute right-0 z-40 mt-2 w-52 rounded-lg border border-line bg-surface p-1.5 shadow-lg">
      {[...NAV.slice(0, 2), { href: "#europe", label: "Why Europe" }, ...NAV.slice(2), { href: "#account", label: "Get started" }].map((item) => <li key={item.href}><a href={item.href} aria-current={current === item.href.slice(1) ? "location" : undefined} onClick={() => ref.current?.removeAttribute("open")} className="flex min-h-10 items-center rounded-md px-3 text-ink hover:bg-surface-2 aria-[current]:font-medium aria-[current]:text-guard">{item.label}</a></li>)}
      <li><a href={SELF_HOST} onClick={() => ref.current?.removeAttribute("open")} className="flex min-h-10 items-center rounded-md px-3 text-ink hover:bg-surface-2">Self-host ↗</a></li>
    </ul>
  </details>;
}

/** One of the five differences: a short lead that links to the section that shows it. */
function Differentiator({ href, title, children }: { href: string; title: string; children: ReactNode }) {
  return <li className="border-l-2 border-guard/40 pl-3 text-xs text-muted sm:text-sm"><a href={href} className="block rounded-sm font-medium text-ink underline-offset-4 hover:underline">{title}{"\u00a0"}<span aria-hidden="true" className="text-muted">↓</span></a><span className="mt-0.5 block">{children}</span></li>;
}

/** A small results table: one row per system, values in percent; ours in ink. Fits a phone. */
function ResultTable({ caption, hideCaption = false, columns, rows }: { caption: string; hideCaption?: boolean; columns: string[]; rows: { name: string; title?: string; ours?: boolean; values: readonly string[] }[] }) {
  return <table className="w-full border-collapse text-sm">
    <caption className={hideCaption ? "sr-only" : "pb-1 text-left text-xs font-medium text-ink"}>{caption}</caption>
    <thead><tr className="border-b border-line text-xs text-muted"><th scope="col" className="py-1.5 pr-3 text-left font-normal">System</th>{columns.map((c) => <th key={c} scope="col" className="py-1.5 pl-2 text-right font-normal">{c}</th>)}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.name} className="border-b border-line last:border-0"><th scope="row" title={row.title} className={["py-1.5 pr-3 text-left", row.ours ? "font-medium text-ink" : "font-normal text-ink"].join(" ")}>{row.name}</th>{row.values.map((v, i) => <td key={i} className={["py-1.5 pl-2 text-right whitespace-nowrap tabular-nums", row.ours ? "font-medium text-ink" : "text-muted"].join(" ")}>{v}&nbsp;%</td>)}</tr>)}</tbody>
  </table>;
}

/** One audience in the "Who it's for" card: columns split by hairlines from md up. */
function Audience({ title, task, children }: { title: string; task: string; children: ReactNode }) {
  return <li className="min-w-0 md:px-5 md:first:pl-0 md:last:pr-0"><h3 className="text-sm font-medium text-ink">{title}</h3><p className="mt-2 border-l-2 border-line pl-2.5 font-mono text-2xs text-ink sm:text-xs">“{task}”</p><p className="mt-2 text-muted">{children}</p></li>;
}

/** One of the three Why Europe cards: what the rule asks, what PII Guard does, a link to the detail. */
function EuCard({ title, href, children }: { title: string; href: string; children: ReactNode }) {
  return <li className="min-w-0 bg-surface p-4 sm:p-5"><h3 className="text-sm font-medium text-ink"><a className="rounded-sm underline-offset-4 hover:underline" href={href}>{title}{"\u00a0"}<span aria-hidden="true" className="text-muted">↗</span></a></h3><p className="mt-2 text-muted">{children}</p></li>;
}

/** One of the three "Live in three steps": a numbered lead and what it means. */
function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return <li className="min-w-0 bg-surface p-4 sm:p-5"><p className="flex items-baseline gap-2.5"><span aria-hidden="true" className="inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-guard-soft font-mono text-xs text-guard">{n}</span><span className="font-medium text-ink"><span className="sr-only">Step {n}: </span>{title}</span></p><div className="mt-2 pl-8.5 text-muted">{children}</div></li>;
}

/** One list item with its lead in ink. */
function Point({ title, children }: { title: string; children: ReactNode }) {
  return <li className="text-muted"><span className="font-medium text-ink">{title}</span> {children}</li>;
}

/** One proof signal under the hero's call to action: a short claim that links to its evidence. */
function ProofItem({ href, children }: { href: string; children: ReactNode }) {
  return <li><a className="inline-flex min-h-6 items-center gap-1.5 rounded-sm underline-offset-4 hover:text-ink hover:underline" href={href}><span aria-hidden="true" className="size-1.5 rounded-full bg-guard-dot" />{children}</a></li>;
}

/** One model in the Meta strip: what it does and where it runs. */
function MetaModel({ name, where, role }: { name: string; where: string; role: ReactNode }) {
  return <li className="min-w-0 bg-surface p-4"><h3 className="text-sm font-medium text-ink">{name}</h3><p className="mt-0.5 font-mono text-2xs text-guard">{where}</p><p className="mt-2 text-muted">{role}</p></li>;
}
