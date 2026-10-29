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
import { COMPARISON, IMAGE_PROOF, LATENCY, MEASURED, OPEN_MODELS, PROOF, SETS } from "./proof";
import { SITE_HASHES, SOURCE, useAccount, useHash, type HostedSession } from "./session";

// Without a return address Easy Auth ends on its own bare "signed in" page (LAB-1425);
// sign-in returns to the console (LAB-1430).
const LOGIN = "/.auth/login/google?post_login_redirect_uri=%2F%23overview";
const LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2F";
const NER_MODEL = "https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base";
const DOCS = `${SOURCE}/blob/develop/docs`;
const SELF_HOST = `${SOURCE}#try-it`;
const MODEL_CARD = `${NER_MODEL}#model-card`;

// Below the fold and heavier than the rest of the page: loaded on demand, so the first paint
// stays small (Lighthouse, LAB-1466).
const ImageShowcase = lazy(() => import("./ImageShowcase"));
const ResultsChart = lazy(() => import("./ResultsChart"));
const HeroImage = lazy(() => import("./HeroImage"));

// TODO(owner): operator name, privacy notice URL and contact address. Until they are set the
// footer says they are being finalised; never invent a legal entity here.
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
  if (renderConsole && account?.authenticated && !SITE_HASHES.has(hash)) return renderConsole({ account, error, refresh, call });
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
  const badge: { tone: BadgeTone; text: string } = running ? { tone: "neutral", text: "Live run in progress" } : result ? { tone: "live", text: `Live result · answered by ${friendlyModel(result.model)}` } : failed ? { tone: "failed", text: "Live run didn’t finish · showing the worked example" } : { tone: "neutral", text: "Worked example · not a live run" };
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
    <header className="bg-canvas">
      <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-4 px-4 sm:px-6 lg:h-12">
        <a href="#" className="flex h-9 min-w-0 items-center gap-2.5 rounded-sm text-base font-medium text-ink"><Logo />pii-guard</a>
        <nav aria-label="Main navigation" className="flex min-w-0 items-center gap-5">
          <a className="hidden text-muted hover:text-ink md:inline" href="#demo">Demo</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#images">Images</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#results">Results</a>
          <a className="hidden text-muted hover:text-ink md:inline" href="#how">How it works</a>
          <a className="hidden text-muted hover:text-ink lg:inline" href="#data">Your data</a>
          <a className="hidden text-muted hover:text-ink md:inline" href={SELF_HOST}>Self-host</a>
          {signedIn ? <ButtonLink href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Open console" : "Your account"}</ButtonLink> : <ButtonLink href={loginUrl}>Sign in with Google</ButtonLink>}
        </nav>
      </div>
      <div aria-hidden="true" className="header-hairline" />
    </header>
    <main id="main" tabIndex={-1} className="mx-auto max-w-[1280px] space-y-16 px-4 pb-16 focus:outline-none sm:px-6 lg:space-y-24">
      <section aria-labelledby="intro-heading" className="grid items-center gap-10 pt-10 sm:pt-16 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:pt-20">
        <div className="min-w-0 space-y-6">
          <p className="font-mono text-2xs text-muted">Open source · OpenAI-compatible · Built on Meta models</p>
          <h1 id="intro-heading" className="text-3xl leading-tight font-medium text-balance text-ink sm:text-5xl"><span className="block">Send the work to the model.</span><span className="block">Keep the people out of it.</span></h1>
          <p className="max-w-2xl text-sm text-pretty text-muted sm:text-base">An OpenAI-compatible privacy gateway for AI agents. Names, emails and IDs in text, and faces in images, become placeholders before the request leaves; the real values come back in the answer.</p>
          <ul aria-label="What makes it different" className="grid max-w-2xl gap-3 sm:grid-cols-3">
            <Differentiator href="#images" title="Images too">Faces are blocked and printed ID details become placeholders before an image is sent.</Differentiator>
            <Differentiator href="#how" title="No LLM in the masking path">Rules and a small encoder NER run on the gateway itself.</Differentiator>
            <Differentiator href="#how" title="Your agent keeps working">Codex, OpenCode, Muse Code, pi or the OpenAI SDK: change one base URL.</Differentiator>
          </ul>
          <div className="flex flex-wrap items-center gap-3"><ButtonLink variant="primary" href="#demo" onClick={heroRun}>{heroCta}</ButtonLink><ButtonLink href={SELF_HOST}>Self-host it ↗</ButtonLink></div>
          <div className="space-y-2">
            <dl aria-label="Measured results" className="grid max-w-2xl grid-cols-3 gap-3 sm:gap-4">{PROOF.map((p) => <Metric key={p.label} label={p.label} value={p.value} hint={p.hint} />)}</dl>
            <p className="text-xs text-muted">{MEASURED} · <a className={link} href={`${DOCS}/benchmarks.md`}>All results ↗</a></p>
          </div>
          <p className="max-w-2xl text-sm text-muted">Answers by Meta’s <span className="font-medium text-ink">{modelOr("model")}</span>. Detection by our <a className={link} href={NER_MODEL}>open NER on Hugging Face ↗</a>, fine-tuned from Meta’s <span className="font-medium text-ink">XLM-RoBERTa</span>.</p>
        </div>
        <MiniFlow model={model} name={language === "hu" ? "Minta Réka" : "Robin Example"} />
      </section>

      <section id="demo" aria-labelledby="demo-heading" aria-busy={running} className="scroll-mt-6 space-y-4">
        <SectionHead id="demo-heading" focusable title="See exactly what the model sees." lead={`Your text, what pii-guard sends to ${modelOr("the model")}, its answer, and the answer with the real values put back.`} />
        <Card aria-label="Run the example">
          <div className="flex flex-wrap items-end gap-3">
            <div className="basis-full sm:order-last sm:ml-auto sm:basis-auto sm:self-center"><Badge tone={badge.tone}>{badge.text}</Badge></div>
            <div className="grid gap-1.5"><p aria-hidden="true" className="text-sm font-medium text-ink">Sample language</p><SegmentedControl label="Sample language" options={LANGUAGES.map((l) => ({ ...l, disabled: running }))} value={language} onChange={(v) => reset(v as Language)} /></div>
            {signedIn && !needsKey && <Field label="Input" className="min-w-36 max-w-56 flex-1"><Select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">Worked example</option><option value="custom">Your text</option></Select></Field>}
            {canRun && !quota && <Button variant="primary" busy={running} disabled={!running && editable && !text.trim()} onClick={() => void run()}>{running ? "Running…" : failed ? "Try again" : editable ? "Run your text" : "Run live example"}</Button>}
            {!account && <Button variant="primary" disabled>{accountError ? "Run live example" : "Checking availability…"}</Button>}
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
            <Pane id="demo-input" side="you" eyebrow="Stays with pii-guard" title="Your text" className="lg:flex-1" footer={result ? "A real guard and model produced this. Check the masked request: detection can miss values, and this is pseudonymisation, not anonymisation." : "Hand-written, fictional example: nothing was detected or sent. Live runs use fictional samples chosen by the server."}>
              {shown ? <YourText text={shown.original} masked={shown.masked} entities={result?.entities} /> : <Field label="Your text" hint="pii-guard receives this text in full on Azure in Sweden Central. Use fictional data while you evaluate."><Textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></Field>}
            </Pane>
            <Boundary direction="outbound" label="pii-guard boundary: only this crosses to the model">
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
            <Boundary direction="inbound" label="pii-guard boundary: placeholders are restored on the way back" />
            <Pane id="demo-restored" side="you" eyebrow="Real values put back" title="Restored answer" className="lg:flex-1">
              {shown ? <RestoredText segments={restoredSegments(shown)} /> : <p className="text-sm text-muted">The answer with the real values appears here.</p>}
            </Pane>
          </div>
          <p className="text-xs text-muted">Blue marks a value and the placeholder that replaced it; green marks a value pii-guard put back.</p>
        </div>
      </section>

      <section id="images" aria-labelledby="images-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="images-heading" title="Images too: faces blocked, ID details tokenized." lead="A gateway that only reads text passes screenshots and scans on untouched. pii-guard reads the image itself: faces and ID photos are covered, and each printed name and number is covered by a box with its placeholder. The same person gets the same placeholder in your text and in the image, so the model can still answer, and the answer comes back to you with the real values." />
        <Suspense fallback={<div className="h-[420px] rounded-xl border border-line bg-surface" aria-hidden="true" />}><ImageShowcase /></Suspense>
        <p className="max-w-3xl text-xs text-muted">A fictional specimen ID card. Through the gateway, the masked image goes to the model in place of the original, followed by its masked transcript and summary. On 24 fictional documents, 98&nbsp;% of the values on an image got the same placeholder as in the text, with no false merges (<a className={link} href={`${DOCS}/benchmarks.md#visual-placeholders`}>benchmark</a>).</p>
        <p className="max-w-3xl text-xs text-muted">In the hosted preview, masking runs on the service and the masked image comes back to you; it isn’t sent to a model. It doesn’t look for signatures or stamps (on this card the photo cover happens to take the signature too); a self-hosted install masks them. {signedIn && hasConsole ? <a className={link} href="#playground/images">Try your own image in the Playground</a> : <><a className={link} href={loginUrl}>Sign in</a> to try your own image.</>}</p>
        <Card title="Measured on 65 official specimen ID documents from 24 countries" headingLevel={3} subtitle="Self-hosted run with SAM 3.1, Tesseract OCR and the rules, 27 Oct 2026. A region counts as covered when the mask overlaps it at IoU ≥ 0.5.">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">{IMAGE_PROOF.map((p) => <Metric key={p.label} label={p.label} value={p.value} hint={p.hint} />)}</dl>
          <p className="mt-4 text-xs text-muted"><a className={link} href={`${DOCS}/benchmarks.md#image-masking`}>Image benchmark details ↗</a></p>
        </Card>
      </section>

      <section id="results" aria-labelledby="results-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="results-heading" title="Among the best at keeping personal data out." lead="The lowest leak rate of the tools we compared on every set in the table below. It is not the lowest everywhere: on Gretel finance, Presidio leaks slightly less (18.8 % against 19.0 %). Fictional data only, from committed run records of 27–28 October 2026. The sets are small: a few points’ difference is noise." />
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-2">
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
            <Card title="Leak rate against detection time" headingLevel={3} subtitle="Hand-written German, English and Hungarian set (51 docs). Down and left is better; each tool’s time was measured where it ran.">
              <Suspense fallback={<div className="h-[340px] rounded-lg bg-surface-2" aria-hidden="true" />}><ResultsChart /></Suspense>
            </Card>
          <Card title="Where it’s weaker" headingLevel={3}>
            <ul className="grid gap-3">
              <Point title="Finance text.">19.0 % leak on Gretel finance, level with Presidio (18.8 %).</Point>
              <Point title="Over-masking.">It can mask too much: reference numbers without a cue word can be masked as IDs (26.4 % over-masking on CEE-PII).</Point>
              <Point title="Other EU languages.">Trained on Hungarian, German and English. On EU legal text in 21 languages it leaks 8.5 % (MAPA EUR-Lex, 42 docs).</Point>
            </ul>
            <p className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">{signedIn && hasConsole && <a className={link} href="#evaluation">Open the Evaluation page</a>}<a className={link} href={`${DOCS}/benchmarks.md`}>All benchmark results ↗</a><a className={link} href={`${DOCS}/evaluation.md`}>How we measure ↗</a><a className={link} href={MODEL_CARD}>NER model card ↗</a></p>
          </Card>
          </div>
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
            <Card title="Leak and F1 by dataset" headingLevel={3} subtitle="Leak: labelled personal values that still reach the model (lower is safer). F1: detection accuracy (higher is better).">
              <div tabIndex={0} role="region" aria-label="Leak and F1 by dataset, scrollable" className="hidden overflow-x-auto rounded-md sm:block">
                <table className="w-full min-w-[28rem] border-collapse text-sm">
                  <caption className="sr-only">Leak rate and F1 in percent, by dataset, for pii-guard and three comparison tools</caption>
                  <thead><tr className="border-b border-line text-xs text-muted"><th scope="col" className="py-2 pr-3 text-left font-normal">System</th>{SETS.map((set) => <th key={set} scope="col" className="px-2 py-2 text-right font-normal last:pr-0">{set}<span className="block">leak · F1</span></th>)}</tr></thead>
                  <tbody>{COMPARISON.map((row) => <tr key={row.system} className="border-b border-line last:border-0"><th scope="row" className={["py-2 pr-3 text-left", row.ours ? "font-medium" : "font-normal"].join(" ")}>{row.system}</th>{row.leak.map((v, i) => <td key={i} className={["px-2 py-2 text-right whitespace-nowrap tabular-nums last:pr-0", row.ours ? "font-medium text-ink" : "text-muted"].join(" ")}>{v}&nbsp;% · {row.f1[i]}&nbsp;%</td>)}</tr>)}</tbody>
                </table>
              </div>
              <div className="space-y-5 sm:hidden">{SETS.map((set, i) => <ResultTable key={set} caption={set} columns={["Leak", "F1"]} rows={COMPARISON.map((row) => ({ name: row.system, ours: row.ours, values: [row.leak[i]!, row.f1[i]!] }))} />)}</div>
              <p className="mt-3 text-xs text-muted">pii-guard runs of 28 Oct 2026, the other tools 27 Oct 2026. CEE-PII and Nemotron-PII are public test splits pii-guard was not trained on.</p>
            </Card>
            <Card title="Our NER against other open PII models" headingLevel={3} subtitle="The same rules and the same 51 hand-written documents; only the NER model differs. Over-masking: text masked that wasn’t personal data.">
              <ResultTable hideCaption caption="Leak, F1 and over-masking in percent, by NER model, with the same rules" columns={["Leak", "F1", "Over-masking"]} rows={OPEN_MODELS.map((m) => ({ name: m.model, title: m.id, ours: "ours" in m, values: [m.leak, m.f1, m.over] }))} />
              <p className="mt-3 text-xs text-muted">Runs of 28 Oct 2026. The closest, bardsai multilang v1, leaks 1.2 % but masks about nine times as much text that isn’t personal data. <a className={link} href={MODEL_CARD}>NER model card ↗</a></p>
            </Card>
          </div>
        </div>
      </section>

      <section id="how" aria-labelledby="how-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="how-heading" title="Change one base URL. The model gets placeholders." lead="pii-guard sits between your agent and the model provider. It speaks the OpenAI Chat Completions and Responses APIs." />
        <ol className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-3">
          <li><Card as="div" title="1 · Detect" headingLevel={3} className="h-full"><p className="text-muted"><span className="font-medium text-ink">No LLM in the masking path.</span> Validated rules for identifiers, plus our open multilingual NER, a small encoder model, for names, addresses and dates. Both run inside pii-guard, with no API call. An LLM detector is an opt-in audit mode, off by default.</p></Card></li>
          <li><Card as="div" title="2 · Swap" headingLevel={3} className="h-full"><p className="text-muted">Each value becomes a keyed placeholder such as <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" />. The same person gets the same placeholder for the whole session, and the mapping stays in pii-guard.</p></Card></li>
          <li><Card as="div" title="3 · Restore" headingLevel={3} className="h-full"><p className="text-muted">The answer comes back with the real values, chunk by chunk as it streams.</p></Card></li>
        </ol>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <Card title="One line in your client" headingLevel={3} subtitle="Tested with Codex, OpenCode, Muse Code, pi and the OpenAI SDK.">
            <pre tabIndex={0} aria-label="Python client example" className="overflow-x-auto rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-ui text-ink"><code>{"from openai import OpenAI\n\nclient = OpenAI(\n    base_url=\"https://<your-pii-guard>/v1\",\n    api_key=\"…\",\n)"}</code></pre>
            <dl className="mt-4"><Metric label={LATENCY.label} value={LATENCY.value} hint={LATENCY.hint} /></dl>
            <p className="mt-3 text-xs text-muted"><a className={link} href={`${DOCS}/integrations/README.md`}>Integration guides ↗</a></p>
          </Card>
          <Card title="Made for agents" headingLevel={3}>
            <ul className="space-y-3">
              <Point title="Tool calls too.">Tool definitions, arguments and results are masked, not just the prompt.</Point>
              <Point title="Streaming.">Placeholders are restored mid-stream, even when one is split across chunks.</Point>
              <Point title="Grammar-aware.">In Hungarian a name changes with every case. The ending stays outside the placeholder, so the model still writes correct sentences.</Point>
              <Point title="Images.">Faces, ID photos and printed personal data are covered before an image goes anywhere (see above).</Point>
              <Point title="Fails closed.">If anything can’t be masked, the request isn’t sent.</Point>
            </ul>
          </Card>
        </div>
      </section>

      <section id="for" aria-labelledby="for-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="for-heading" title="Built for agents that work on people’s files." lead="The useful input is personal data: a case file, an HR folder, a client’s letter. Sending it to a third-party model is the risk; not sending it means the agent can’t do the job. pii-guard lets the agent use the model without handing over the person." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-3">
          <Card title="Legal" headingLevel={3}><p className="text-muted">Draft from case files and correspondence; the model sees <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" />, not your client.</p></Card>
          <Card title="HR" headingLevel={3}><p className="text-muted">Summarise employee folders and write replies, with names, IDs and addresses masked on the way out.</p></Card>
          <Card title="Finance and back office" headingLevel={3}><p className="text-muted">Work through invoices and account correspondence. Bank accounts and tax IDs are caught by validated rules.</p></Card>
        </div>
      </section>

      <section id="meta" aria-labelledby="meta-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="meta-heading" title="Built on Meta models, each where it fits." lead="Anything that sees real personal data is an open-weight model you can run yourself. Hosted models only see fictional or masked text." />
        <Card>
          <KeyValues className="sm:grid-cols-[12rem_minmax(0,1fr)]" items={[
            { key: "xlmr", label: <span className="font-medium text-ink">XLM-RoBERTa</span>, value: <>Open, MIT. Our fine-tuned NER runs inside pii-guard on every request. <a className={link} href={NER_MODEL}>On Hugging Face ↗</a></> },
            { key: "glimmer", label: <span className="font-medium text-ink">Muse Glimmer 30B</span>, value: "Open weights. The teacher: it labelled 4,964 fictional documents to train the NER." },
            { key: "spark", label: <span className="font-medium text-ink">{modelOr("Muse Spark")}</span>, value: "Answers in this demo, seeing placeholders only." },
            { key: "sam", label: <span className="font-medium text-ink">SAM 3.1</span>, value: "Finds signatures so a self-hosted install can mask them too." },
            { key: "open", label: <span className="font-medium text-ink">Muse Spark Open</span>, value: "The optional audit mode and the red team." },
          ]} />
        </Card>
      </section>

      <section id="run" aria-labelledby="run-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="run-heading" title="Two ways to run it." />
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
            <div className="mt-auto pt-5">{signedIn ? <ButtonLink href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Open console" : "Your account"}</ButtonLink> : <ButtonLink href={loginUrl}>Sign in with Google</ButtonLink>}</div>
          </Card>
        </div>
      </section>

      <section id="data" aria-labelledby="data-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="data-heading" title="What happens to your data here." lead="This covers the hosted preview. If you self-host, all of it stays on your own servers." />
        <Card>
          <KeyValues items={[
            { label: "Where", value: "Microsoft Azure, Sweden Central (EU). Processed in memory. No content archive, and no backup of the mappings. Azure operators can access process memory." },
            { label: "As a guest", value: `You can’t type anything. A fixed, fictional sample is masked here, and only the masked version goes to ${modelOr("Meta’s model")}, when free runs are on.` },
            { label: "Signed in", value: `Google receives your sign-in (name, email, profile). pii-guard receives your text in full; only the masked text goes to ${modelOr("Meta’s model")} or to the provider you connect.` },
            { label: "Images", value: "Signed in only. Read and masked inside the service: faces and ID photos are covered, and signatures and stamps stay visible. Images are never stored or sent to a model." },
            { label: "How long", value: "Placeholder mappings expire after 1 hour without use. Your last 50 masked requests are kept in memory for your activity log. A restart clears both. Expiry makes them unavailable; it doesn’t prove the memory is erased." },
            { label: "What Meta receives", value: "Masked text only. Meta’s standard terms exclude training on it but allow retention as needed, and processing there isn’t guaranteed to stay in the EU." },
          ]} />
          <p className="mt-4 text-xs text-muted"><a className={link} href={`${DOCS}/hosted.md`}>Full processing and retention details ↗</a></p>
        </Card>
      </section>

      <section id="account" aria-labelledby="account-heading" className="scroll-mt-6">
        <Card as="div" title="Try it now. Connect your app when you’re ready." titleId="account-heading" actions={account && (signedIn ? <>{hasConsole && <ButtonLink variant="primary" href="#overview">Open console</ButtonLink>}<ButtonLink variant="ghost" href={account.logout_url || LOGOUT}>Sign out</ButtonLink></> : <ButtonLink variant="primary" href={loginUrl}>Sign in with Google</ButtonLink>)}>
          <div className="space-y-4">
            {!signedIn && <p className="max-w-3xl text-muted">{sponsoredOff ? "Free runs are paused right now. Sign in with Google to run your own text with your own model key, create projects and point your app at your own pii-guard address." : "No sign-in needed for the live example. Sign in with Google to run your own text, create projects and point your app at your own pii-guard address."}</p>}
            {signedIn && <p className="max-w-3xl text-muted">You’re signed in. Your projects, endpoints, model connections and activity are in the console.</p>}
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

      <section id="privacy" aria-labelledby="privacy-heading" className="scroll-mt-6 space-y-6">
        <SectionHead id="privacy-heading" title="What pii-guard doesn’t promise." />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-2">
          <Card title="Detection can miss" headingLevel={3}><p className="text-muted">A missed value goes to the model. That’s why we publish leak rates and show you the masked request.</p></Card>
          <Card title="Context can identify" headingLevel={3}><p className="text-muted">Even with names removed, surrounding detail can point to a person.</p></Card>
          <Card title="It pseudonymises; it doesn’t anonymise" headingLevel={3}><p className="text-muted">The data is still personal data, and pii-guard reduces exposure. Using it doesn’t by itself make a deployment compliant with any law.</p></Card>
          <Card title="Remote detectors join your trust boundary" headingLevel={3}><p className="text-muted">If you enable one, it sees originals. Don’t submit highly sensitive data, or content you aren’t authorised to process.</p></Card>
        </div>
        <p className="text-xs text-muted"><a className={link} href={`${DOCS}/privacy-model.md`}>Read the privacy model ↗</a></p>
      </section>
    </main>
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-[1280px] gap-4 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <a href="#" className="flex h-9 items-center gap-2.5 rounded-sm text-base font-medium text-ink"><Logo />pii-guard</a>
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
          {CONTACT_URL && <a className="text-ink hover:underline" href={CONTACT_URL}>Contact</a>}
        </nav>
        <p className="text-xs text-muted">Apache-2.0 · Built for the Meta Global AI Developer Hackathon 2026</p>
        <p className="text-xs text-muted">{OPERATOR ? `Operated by ${OPERATOR}.` : "Operator details, privacy notice and contact are being finalised."}</p>
      </div>
    </footer>
  </div>;
}

/** A landing section's heading: the console's 24/500 section title and a muted lead. */
function SectionHead({ id, title, lead, focusable }: { id: string; title: string; lead?: string; focusable?: boolean }) {
  return <div className="max-w-3xl"><h2 id={id} tabIndex={focusable ? -1 : undefined} className="text-2xl font-medium text-balance text-ink focus:outline-none">{title}</h2>{lead && <p className="mt-2 text-sm text-pretty text-muted sm:text-base">{lead}</p>}</div>;
}

/** One of the hero's three differences: a short lead that links to the section that shows it. */
function Differentiator({ href, title, children }: { href: string; title: string; children: ReactNode }) {
  return <li className="border-l-2 border-guard/40 pl-3 text-xs text-muted sm:text-sm"><a href={href} className="block rounded-sm font-medium text-ink hover:underline">{title}</a><span className="mt-0.5 block">{children}</span></li>;
}

/** A small results table: one row per system, values in percent; ours in ink. Fits a phone. */
function ResultTable({ caption, hideCaption = false, columns, rows }: { caption: string; hideCaption?: boolean; columns: string[]; rows: { name: string; title?: string; ours?: boolean; values: readonly string[] }[] }) {
  return <table className="w-full border-collapse text-sm">
    <caption className={hideCaption ? "sr-only" : "pb-1 text-left text-xs font-medium text-ink"}>{caption}</caption>
    <thead><tr className="border-b border-line text-xs text-muted"><th scope="col" className="py-1.5 pr-3 text-left font-normal">System</th>{columns.map((c) => <th key={c} scope="col" className="py-1.5 pl-2 text-right font-normal">{c}</th>)}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.name} className="border-b border-line last:border-0"><th scope="row" title={row.title} className={["py-1.5 pr-3 text-left", row.ours ? "font-medium text-ink" : "font-normal text-ink"].join(" ")}>{row.name}</th>{row.values.map((v, i) => <td key={i} className={["py-1.5 pl-2 text-right whitespace-nowrap tabular-nums", row.ours ? "font-medium text-ink" : "text-muted"].join(" ")}>{v}&nbsp;%</td>)}</tr>)}</tbody>
  </table>;
}

/** One list item with its lead in ink. */
function Point({ title, children }: { title: string; children: ReactNode }) {
  return <li className="text-muted"><span className="font-medium text-ink">{title}</span> {children}</li>;
}

/** The hero's picture of the product: one value, there and back. Fictional. Desktop only: phones go straight to the demo. */
function MiniFlow({ model, name }: { model: string | null; name: string }) {
  const masked = metaFor("PERSON");
  return <figure className="hidden min-w-0 space-y-2 lg:block" aria-labelledby="mini-flow-caption">
    <figcaption id="mini-flow-caption" className="sr-only">One name, there and back: you send it, the model sees only a placeholder, and you get the real name back. Below it, a fictional ID card before and after masking: the face is blocked and each ID detail is covered by a box printed with its placeholder.</figcaption>
    <div aria-hidden="true" className="space-y-2">
      <div className="rounded-xl border border-line bg-surface px-4 py-3 sm:px-5"><p className="font-mono text-2xs text-guard">You send</p><p className="doc mt-1">Name: <mark className={["rounded-md px-0.5 -mx-0.5 ring-1 ring-inset", masked.mark].join(" ")}>{name}</mark></p></div>
      <p className="text-center font-mono text-2xs text-guard">↓ pii-guard masks</p>
      <div className="rounded-xl border border-model/25 bg-model-soft/60 px-4 py-3 sm:px-5"><p className="font-mono text-2xs text-model">{model ?? "The model"} sees</p><p className="doc mt-1">Name: <Placeholder text="[[PERSON_3f9a1c]]" entityType="PERSON" /></p></div>
      <p className="text-center font-mono text-2xs text-guard">↓ pii-guard restores</p>
      <div className="rounded-xl border border-line bg-surface px-4 py-3 sm:px-5"><p className="font-mono text-2xs text-guard">You get back</p><p className="doc mt-1">Dear <mark className="rounded-md bg-restored-soft px-0.5 -mx-0.5 text-ink ring-1 ring-restored/45 ring-inset">{name}</mark>, …</p></div>
      <p className="text-center font-mono text-2xs text-guard">↓ and in images</p>
      <div className="rounded-xl border border-line bg-surface px-4 py-3 sm:px-5"><p className="font-mono text-2xs text-guard">Faces blocked · ID details tokenized</p><div className="mt-2"><Suspense fallback={<div className="aspect-[3/1] rounded-md bg-surface-2" />}><HeroImage /></Suspense></div></div>
    </div>
  </figure>;
}
