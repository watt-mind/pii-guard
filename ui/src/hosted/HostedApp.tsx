import { lazy, Suspense, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
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
import { consoleSectionOf } from "./consoleLink";
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

// Hand-written and fictional; the placeholders use the real format ([[TYPE_hex]]) so they highlight.
const EXAMPLES = {
  hu: { original: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: Minta Réka\nE-mail: reka.minta@example.com", masked: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: [[PERSON_3f9a1c]]\nE-mail: [[EMAIL_8b21de]]", answer: "Kedves [[PERSON_3f9a1c]]! A visszatérítésről a [[EMAIL_8b21de]] címre küldünk értesítést.", restored: "Kedves Minta Réka! A visszatérítésről a reka.minta@example.com címre küldünk értesítést." },
  en: { original: "Please draft a short refund reply.\n\nName: Robin Example\nEmail: robin.example@example.com", masked: "Please draft a short refund reply.\n\nName: [[PERSON_3f9a1c]]\nEmail: [[EMAIL_8b21de]]", answer: "Dear [[PERSON_3f9a1c]], we will send your refund update to [[EMAIL_8b21de]].", restored: "Dear Robin Example, we will send your refund update to robin.example@example.com." },
};
type Language = keyof typeof EXAMPLES;
const LANGUAGES = [{ value: "en", label: "English" }, { value: "hu", label: "Hungarian" }] as const;

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
  const [text, setText] = useState(EXAMPLES[language].original);
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
  // no live run, only the worked example and the way to sign in.
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
    setLanguage(nextLanguage); setText(EXAMPLES[nextLanguage].original); setResult(null); setFailed(false); setQuota(false); setError(""); setAnnounce("");
  }
  async function run() {
    setRunning(true); setStep(0); setError(""); setFailed(false); setQuota(false); setResult(null); setAnnounce("Running the live example…");
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

  // A run in flight or a failed one keeps the worked example on screen: a live failure never blanks it.
  const shown = result ?? (editable && signedIn && !needsKey ? null : EXAMPLES[language]);
  const counts = shown ? placeholderCounts(shown.masked) : [];
  const legend = new Map<EntityType, number>(counts.filter((c): c is [EntityType, string, number] => c[0] !== null).map(([type, , n]) => [type, n]));
  const masked = counts.reduce((sum, [, , n]) => sum + n, 0);
  const badge: { tone: BadgeTone; text: string } = running ? { tone: "neutral", text: "Live run in progress" } : result ? { tone: "live", text: `Live result · answered by ${friendlyModel(result.model)}` } : failed ? { tone: "failed", text: "Live run didn’t finish · showing the worked example" } : { tone: "neutral", text: "Worked example" };
  const heroCta = signedIn ? "Run your own text" : guestLive ? "Run the live demo" : "See how it works";
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

  return <div className="min-h-dvh bg-canvas text-sm text-ink">
    <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-40 focus:rounded focus:bg-surface focus:px-3 focus:py-1">Skip to content</a>
    <header className="sticky top-0 z-30 bg-canvas">
      <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-4 px-4 sm:px-6 lg:h-12 lg:px-10">
        <a href="#" className="flex h-9 min-w-0 items-center gap-2.5 rounded-sm text-base font-medium text-ink"><Logo />PII Guard</a>
        <nav aria-label="Main navigation" className="flex min-w-0 items-center gap-5">
          <a className="hidden text-muted hover:text-ink md:inline" href="#demo">Demo</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#images">Images</a>
          <a className="hidden text-muted hover:text-ink lg:inline" href="#meta">Meta models</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#results">Results</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#how">How it works</a>
          <a className="hidden text-muted hover:text-ink lg:inline" href="#data">Your data</a>
          <a className="hidden text-muted hover:text-ink md:inline" href={SELF_HOST}>Self-host</a>
          {signedIn ? <ButtonLink href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Console" : "Your account"}</ButtonLink> : <ButtonLink href={loginUrl}>Console</ButtonLink>}
        </nav>
      </div>
      <div aria-hidden="true" className="header-hairline" />
    </header>
    <main id="main" tabIndex={-1} className="mx-auto max-w-[1280px] space-y-16 px-4 pb-16 focus:outline-none sm:px-6 lg:space-y-24 lg:px-10">
      <section aria-labelledby="intro-heading" className="grid items-center gap-10 pt-10 sm:pt-16 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:pt-20">
        <div className="min-w-0 space-y-6">
          <p className="font-mono text-2xs text-muted sm:text-xs">Open source · OpenAI-compatible · Built on Meta’s XLM-RoBERTa, Muse Glimmer, Muse Spark and SAM&nbsp;3.1</p>
          <h1 id="intro-heading" className="text-3xl leading-tight font-medium text-balance text-ink sm:text-5xl"><span className="block">Send the work to the model.</span><span className="block">Keep the people out of it.</span></h1>
          <p className="max-w-2xl text-sm text-pretty text-muted sm:text-base"><span className="text-ink">Legal, HR and finance teams in the EU can’t send case files to a hosted model, so their agents stay off the useful work.</span> PII Guard is a privacy gateway: personal data in text, tool calls and images becomes placeholders before the request leaves, and the real values come back in the answer.</p>
          <div className="max-w-2xl space-y-3">
            <dl aria-label="Measured results" className="grid grid-cols-3 gap-3 sm:gap-6">{PROOF.map((p) => <Metric key={p.label} size="hero" label={p.label} value={p.value} hint={p.hint} />)}</dl>
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
          <div className="flex flex-wrap items-end gap-3">
            <div className="basis-full sm:order-last sm:ml-auto sm:basis-auto sm:self-center"><Badge tone={badge.tone}>{badge.text}</Badge></div>
            <div className="grid gap-1.5"><p aria-hidden="true" className="text-sm font-medium text-ink">Sample language</p><SegmentedControl label="Sample language" options={LANGUAGES.map((l) => ({ ...l, disabled: running }))} value={language} onChange={(v) => reset(v as Language)} /></div>
            {signedIn && !needsKey && <Field label="Input" className="min-w-36 max-w-56 flex-1"><Select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">Worked example</option><option value="custom">Your text</option></Select></Field>}
            {canRun && !quota && <Button variant="primary" busy={running} disabled={!running && editable && !text.trim()} onClick={() => void run()}>{running ? "Running…" : failed ? "Try again" : editable ? "Run your text" : "Run live example"}</Button>}
            {!account && accountError && <Button variant="primary" disabled>Run live example</Button>}
            {result && !running && <Button onClick={() => reset()}>Back to the worked example</Button>}
            {canRun && !running && !quota && <p className="w-full text-xs text-muted sm:w-auto sm:self-center">{ownConnection ? <>Runs through your {providerLabel(ownConnection.provider)} connection.{hasConsole && <> <a className={link} href="#connect">Change it in Connect</a></>}</> : <>Runs on {modelOr("Meta’s model")} · no key needed{account && runsLeft(account) && <> · <span className="tabular-nums">{runsLeft(account)}</span></>}</>}</p>}
          </div>
          <div className="mt-4 space-y-3 empty:hidden">
            {account && !signedIn && sponsoredOff && <Notice title="Free runs are paused right now" action={<ButtonLink variant="primary" href={loginUrl}>Sign in to run your own text</ButtonLink>}>The worked example below shows the same flow, step by step.</Notice>}
            {needsKey && <Notice title="Free runs are paused right now" action={<ButtonLink variant="primary" href={hasConsole ? "#connect" : "#account"}>Add a model key</ButtonLink>}>Add your own model key to run it, or follow the worked example below.</Notice>}
            {!account && accountError && <Notice title="The live service isn’t reachable">The worked example below still shows the whole flow. <a className={link} href="#account">Check the connection ↓</a></Notice>}
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
            <Pane id="demo-input" side="you" eyebrow="Stays with PII Guard" title="Your text" className="lg:flex-1" footer={result ? "A real guard and model produced this. Check the masked request: detection can miss values, and this is pseudonymisation, not anonymisation." : "Hand-written to show the flow. Run live example sends this fictional sample through the real gateway and model."}>
              {shown ? <YourText text={shown.original} masked={shown.masked} entities={result?.entities} /> : <Field label="Your text" hint="PII Guard receives this text in full on Azure in Sweden Central. Use fictional data while you evaluate."><Textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></Field>}
            </Pane>
            <Boundary direction="outbound" label="PII Guard boundary: only this crosses to the model">
              {shown && <dl className="text-center"><Metric label="masked" value={masked} className="min-w-12" /></dl>}
            </Boundary>
            <Pane id="demo-sent" side="model" eyebrow="Placeholders only" title="Sent to the model" className="lg:flex-1" footer={legend.size > 0 ? <Legend counts={legend} /> : undefined}>
              {shown ? <MaskedText text={shown.masked} /> : <p className="text-sm text-muted">Write or paste your text, then run it to see each step.</p>}
            </Pane>
          </div>
          <div className="flex flex-col lg:flex-row lg:items-stretch">
            <Pane id="demo-answer" side="model" eyebrow="Still placeholders" title="Model answer" className="lg:flex-1">
              {shown ? <MaskedText text={shown.answer} /> : <p className="text-sm text-muted">The model’s answer appears here.</p>}
            </Pane>
            <Boundary direction="inbound" label="PII Guard boundary: placeholders are restored on the way back" />
            <Pane id="demo-restored" side="you" eyebrow="Real values put back" title="Restored answer" className="lg:flex-1">
              {shown ? <RestoredText segments={restoredSegments(shown)} /> : <p className="text-sm text-muted">The answer with the real values appears here.</p>}
            </Pane>
          </div>
          <p className="text-xs text-muted">Blue marks a value and the placeholder that replaced it; green marks a value PII Guard put back.</p>
        </div>
      </section>

      <section id="for" aria-labelledby="for-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="for-heading" eyebrow="Who it’s for" title="Built for agents that work on people’s files." lead="Regulated teams keep their agents away from the useful input, because it is personal data: a case file, an HR folder, a client’s letter. PII Guard lets the agent use the model without handing over the person." />
        <Card as="div">
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-5 md:grid-cols-3 md:gap-0 md:divide-x md:divide-line">
            <Audience title="Legal" task="Summarise the case file and draft the reply to opposing counsel.">Parties, addresses and case-file IDs are masked; the model sees <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" />, not your client, and the draft comes back with the name.</Audience>
            <Audience title="HR" task="Answer this employee’s leave request from their folder.">Names, ID numbers, addresses and dates of birth are masked on the way out, in tool results as well as in the prompt.</Audience>
            <Audience title="Finance and back office" task="Match these invoices to the account letters and flag the gaps.">IBANs and tax IDs are caught by validated rules with checksums; names and companies by the NER.</Audience>
          </ul>
        </Card>
      </section>

      <section id="images" aria-labelledby="images-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="images-heading" eyebrow="Images" title="Images too: faces blocked, ID details tokenized." lead="Text-only gateways pass screenshots and scans through untouched. PII Guard blocks faces and ID photos and covers each printed detail with a placeholder, the same one that person gets in your text, so the model can still answer." />
        <Suspense fallback={<div className="h-[420px] rounded-xl border border-line bg-surface" aria-hidden="true" />}><ImageShowcase /></Suspense>
        <p className="max-w-3xl text-xs text-muted">A fictional specimen ID card, masked with the hosted preview’s setup. Through the gateway, the masked image and its masked transcript are what the model receives. In this hosted preview images are masked and returned to you, never sent to a model, and signatures stay visible; masking them takes a self-hosted install with SAM 3.1. {signedIn && hasConsole ? <a className={link} href="#playground/images">Try your own image in the Playground</a> : <><a className={link} href={loginUrl}>Sign in</a> to try your own image.</>}</p>
        <Card title="Measured on images" headingLevel={3} subtitle={`Same placeholder: ${VISUAL_PLACEHOLDERS.docs} fictional documents. Portraits and signatures: ${IMAGE_LIMITS.ids} official specimen ID documents from ${IMAGE_LIMITS.countries} countries, self-hosted, a region counted when the mask overlaps it at IoU ≥ 0.5. Runs of 27 Oct 2026.`}>
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">{IMAGE_PROOF.map((p) => <Metric key={p.label} label={p.label} value={p.value} hint={p.hint} />)}</dl>
          <p className="mt-4 text-xs text-muted">Printed text on real ID scans is still the weak spot; it’s listed under <a className={link} href="#privacy">limits</a>. <a className={link} href={`${DOCS}/benchmarks.md#image-masking`}>Image benchmark details ↗</a></p>
        </Card>
      </section>

      <section id="meta" aria-labelledby="meta-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="meta-heading" eyebrow="Built on Meta models" title="Open weights wherever real data goes. Hosted models see placeholders." lead="Anything that sees real personal data is an open-weight model you can run yourself." />
        <ul aria-label="Meta models and what each does" className="grid grid-cols-[minmax(0,1fr)] gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
          <MetaModel name="XLM-RoBERTa" where="Inside PII Guard, CPU" role={<>The base of our NER, fine-tuned for personal data. Runs on every request. <a className={link} href={NER_MODEL}>Published ↗</a></>} />
          <MetaModel name="Muse Glimmer 30B" where="Open weights, served on Modal" role="The teacher: it labelled 4,964 fictional documents, and our NER was distilled from its labels." />
          <MetaModel name="Muse Spark Open" where="Open weights, on Baseten" role="The opt-in audit detector, and the red team that tries to re-identify masked text." />
          <MetaModel name="SAM 3.1" where="Self-hosted installs" role="Finds signatures on scans, so they’re masked along with faces and ID photos." />
          <MetaModel name={modelOr("Muse Spark")} where="Meta Model API" role="Answers in this demo. It only ever sees placeholders." />
        </ul>
      </section>

      <section id="results" aria-labelledby="results-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="results-heading" eyebrow="Results" title="The lowest leak rate on all three test sets below." lead="Fictional and public test data, from committed run records of 27–28 Oct 2026. Leak counts personal values that still reach the model; F1 also counts over-masking. The sets are small, so a few points is noise; where it’s weaker is listed under limits." />
        <div className="grid grid-cols-[minmax(0,1fr)] items-stretch gap-6 lg:grid-cols-2">
          <Card title="Leak rate against detection time" headingLevel={3} subtitle="Hand-written German, English and Hungarian set (51 docs). Down and left is better. Time is detection per document, measured where each tool ran.">
            <Suspense fallback={<div className="h-[340px] rounded-lg bg-surface-2" aria-hidden="true" />}><ResultsChart /></Suspense>
          </Card>
          <Card title="Leak and F1 by dataset" headingLevel={3} subtitle="Leak: labelled personal values that still reach the model (lower is safer). F1: detection accuracy (higher is better)." className="flex flex-col">
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
              <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">{signedIn && hasConsole && <a className={link} href="#evaluation">Open the Evaluation page</a>}<a className={link} href={`${DOCS}/benchmarks.md`}>All benchmark results ↗</a><a className={link} href={`${DOCS}/evaluation.md`}>How we measure ↗</a><a className={link} href={MODEL_CARD}>NER model card ↗</a></p>
            </div>
          </Card>
        </div>
      </section>

      <section id="how" aria-labelledby="how-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="how-heading" eyebrow="How it works" title="Change one base URL. The model gets placeholders." lead="PII Guard sits between your agent and the model provider and speaks the OpenAI Chat Completions and Responses APIs." />
        <ol className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-3">
          <li><Card as="div" title="1 · Detect" headingLevel={3} className="h-full"><p className="text-muted"><span className="font-medium text-ink">No LLM in the masking path.</span> Validated rules for identifiers and our open encoder NER for names, addresses and dates, both inside PII Guard. An LLM detector is an opt-in audit mode.</p></Card></li>
          <li><Card as="div" title="2 · Swap" headingLevel={3} className="h-full"><p className="text-muted">Each value becomes a keyed placeholder such as <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" />. The same person gets the same placeholder for the whole session, and the mapping stays in PII Guard.</p></Card></li>
          <li><Card as="div" title="3 · Restore" headingLevel={3} className="h-full"><p className="text-muted">The answer comes back with the real values, restored as it streams, even when a placeholder is split across chunks. The model never saw them.</p></Card></li>
        </ol>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <Card title="One line in your client" headingLevel={3} subtitle="Tested with Codex, OpenCode, Muse Code, pi and the OpenAI SDK.">
            <pre tabIndex={0} aria-label="Python client example" className="overflow-x-auto rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-ui text-ink"><code>{"from openai import OpenAI\n\nclient = OpenAI(\n    base_url=\"https://<your-pii-guard>/v1\",\n    api_key=\"…\",\n)"}</code></pre>
            <p className="mt-4 text-xs text-muted"><a className={link} href={`${DOCS}/integrations/README.md`}>Integration guides ↗</a></p>
          </Card>
          <Card title="Made for agents" headingLevel={3}>
            <ul className="space-y-3">
              <Point title="Tool calls too.">Tool definitions, arguments and results are masked, not just the prompt.</Point>
              <Point title="Grammar-aware.">In Hungarian a name changes with every case. The ending stays outside the placeholder, so the model still writes correct sentences.</Point>
              <Point title="Images.">Faces are blocked; each printed detail gets the same placeholder as in the text.</Point>
              <Point title="Fails closed.">If anything can’t be masked, the request isn’t sent.</Point>
            </ul>
            <dl className="mt-5 border-t border-line pt-4"><Metric label={LATENCY.label} value={LATENCY.value} hint={LATENCY.hint} /></dl>
          </Card>
        </div>
      </section>

      <section id="run" aria-labelledby="run-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="run-heading" eyebrow="Self-host or hosted" title="Two ways to run it." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-2">
          <Card title="Self-hosted" subtitle="Open source" headingLevel={3} className="flex flex-col">
            <KeyValues items={[
              { label: "Your originals", value: "Your own servers. Use local detectors to keep all raw processing local." },
              { label: "What leaves", value: "Masked text, to the model you choose." },
              { label: "Who runs it", value: "You." },
            ]} />
            <div className="mt-auto pt-5"><ButtonLink href={SELF_HOST}>Self-host it ↗</ButtonLink></div>
          </Card>
          <Card title="Hosted preview" subtitle="For evaluation" headingLevel={3} className="flex flex-col">
            <KeyValues items={[
              { label: "Your originals", value: "Our service on Azure, Sweden Central (EU), in memory." },
              { label: "What leaves", value: `Masked text, to ${modelOr("Meta’s model")} or the provider you connect.` },
              { label: "Who runs it", value: "We run the guard. You bring text, a model key if you like, and your app." },
            ]} />
            <div className="mt-auto pt-5">{signedIn ? <ButtonLink href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Console" : "Your account"}</ButtonLink> : <ButtonLink href={loginUrl}>Console</ButtonLink>}</div>
          </Card>
        </div>
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
              { label: "What Meta receives", value: "Masked text only. Meta’s standard terms exclude training on it but allow retention as needed, and processing there isn’t guaranteed to stay in the EU." },
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
          <Card title="It pseudonymises; it doesn’t anonymise" headingLevel={3}><p className="text-muted">The data is still personal data, and PII Guard reduces exposure. Using it doesn’t by itself make a deployment compliant with any law.</p></Card>
          <Card title="Remote detectors join your trust boundary" headingLevel={3}><p className="text-muted">If you enable one, it sees originals. Don’t submit highly sensitive data, or content you aren’t authorised to process.</p></Card>
          <Card title="Weaker on some text" headingLevel={3}>
            <ul className="grid gap-2">
              <Point title="Finance text.">{WEAKER.gretel}&nbsp;% leak on Gretel finance, level with Presidio ({WEAKER.gretelPresidio}&nbsp;%).</Point>
              <Point title="Over-masking.">Reference numbers without a cue word can be masked as IDs ({WEAKER.ceeOverMasking}&nbsp;% on CEE-PII).</Point>
              <Point title="Other EU languages.">Trained on Hungarian, German and English; on EU legal text in 21 languages it leaks {WEAKER.mapaLeak}&nbsp;%.</Point>
            </ul>
          </Card>
          <Card title="Printed text on ID scans" headingLevel={3}><p className="text-muted">On {IMAGE_LIMITS.ids} official specimen IDs, {IMAGE_LIMITS.all}&nbsp;% of all labelled regions are covered (Presidio Image Redactor: {IMAGE_LIMITS.presidio}&nbsp;%). Printed text alone: {IMAGE_LIMITS.text}&nbsp;%. Faces and ID photos are the strong part; read the masked transcript before you rely on it.</p></Card>
        </div>
        <p className="text-xs text-muted"><a className={link} href={`${DOCS}/privacy-model.md`}>Read the privacy model ↗</a></p>
      </section>

      <section id="account" aria-labelledby="account-heading" className="scroll-mt-20 space-y-6">
        <SectionHead id="account-heading" eyebrow="Get started" title="Try it now. Connect your app when you’re ready." lead={signedIn ? "You’re signed in. Your projects, endpoints, model connections and activity are in the console." : sponsoredOff ? "Free runs are paused right now. Sign in with Google to run your own text with your own model key, create projects and point your app at your own PII Guard address." : "No sign-in needed for the live example. Sign in with Google to run your own text, create projects and point your app at your own PII Guard address."} />
        <div className="flex flex-wrap items-center gap-3">
          {signedIn ? <>{hasConsole && <ButtonLink variant="primary" href="#overview">Open console</ButtonLink>}<ButtonLink variant="ghost" href={account?.logout_url || LOGOUT}>Sign out</ButtonLink></> : <>{startsRun && <ButtonLink variant="primary" href="#demo" onClick={heroRun}>Run the live demo ↑</ButtonLink>}<ButtonLink variant={startsRun ? "secondary" : "primary"} href={loginUrl}>Sign in with Google</ButtonLink><ButtonLink href={SELF_HOST}>Self-host it ↗</ButtonLink></>}
        </div>
        <Card as="div" aria-label="Your runs and the server limits" className="max-w-3xl">
          <div className="space-y-4">
            {accountError ? <Notice tone="danger" live action={<Button size="sm" onClick={() => void refresh()}>Reconnect to API</Button>}>{accountError}</Notice> : !account ? <p className="text-muted">Checking live availability…</p> : <>
              {(!sponsoredOff || signedIn) && <dl className="grid max-w-md grid-cols-2 gap-4">
                {typeof account.limits.requests_per_day === "number"
                  ? <Metric label={signedIn ? "Runs left today" : "Free runs left today"} value={Math.max(0, account.limits.requests_per_day - account.usage.requests_today)} suffix={`of ${account.limits.requests_per_day}`} />
                  : <Metric label="Runs today" value={account.usage.requests_today} />}
                <Metric label="Resets" value={resetsIn(account) ?? "—"} />
              </dl>}
              <Limits account={account} hideZero />
              <p className="max-w-3xl text-xs text-muted">Sessions and model connections are temporary: a restart clears them, and you’ll need to start a fresh request. Model keys are held by the service for the connection’s lifetime and never stored in your browser.</p>
            </>}
          </div>
        </Card>
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
