import { useEffect, useRef, useState, type ReactNode } from "react";
import { createHttpChat, pickDefaultModel, SYSTEM_PROMPT } from "../api/chat";
import { Button, ButtonLink, Field, Notice, SegmentedControl, Select, Textarea } from "../components/ui";
import { metaFor } from "../lib/entities";
import { request, recovery, type Account, type DemoResult, type Requester } from "./api";
import { Limits } from "./AccountPanels";
import { OriginalText, PlaceholderText, RestoredAnswer } from "./Highlight";
import { friendlyModel, placeholderCounts, usageLine } from "./landing";
import { SITE_HASHES, SOURCE, useAccount, useHash, type HostedSession } from "./session";
import "./hosted.css";

// Without a return address Easy Auth ends on its own bare "signed in" page (LAB-1425);
// sign-in returns to the console (LAB-1430).
const LOGIN = "/.auth/login/google?post_login_redirect_uri=%2F%23overview";
const LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2F";
const NER_MODEL = "https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base";
const DOCS = `${SOURCE}/blob/develop/docs`;

// TODO(owner): operator name, privacy notice URL and contact address. Until they are set the
// footer says "coming soon"; never invent a legal entity here.
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
const STEPS = ["Detecting personal data", "Masking it", "Waiting for Meta’s model", "Putting the values back"];

const initialLanguage = (): Language => (globalThis.navigator?.language ?? "").toLowerCase().startsWith("hu") ? "hu" : "en";

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
  const [language, setLanguage] = useState<Language>(initialLanguage);
  const [result, setResult] = useState<DemoResult | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState("");
  const [announce, setAnnounce] = useState("");
  const [text, setText] = useState(EXAMPLES[language].original);
  const [editable, setEditable] = useState(false);
  const [connection, setConnection] = useState("");
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
  const canRun = signedIn || guestLive;

  function reset(nextLanguage = language) {
    setLanguage(nextLanguage); setText(EXAMPLES[nextLanguage].original); setResult(null); setFailed(false); setError(""); setAnnounce("");
  }
  async function run() {
    setRunning(true); setStep(0); setError(""); setFailed(false); setResult(null); setAnnounce("Running the live example…");
    try {
      let next: DemoResult;
      if (editable && signedIn) {
        const abort = new AbortController(); controller.current = abort;
        const timeout = setTimeout(() => abort.abort(), 180_000);
        const doFetch: typeof fetch = (input, init) => {
          const headers = new Headers(init?.headers);
          headers.set("X-PII-Guard-Mode", "fast");
          if (connection) headers.set("X-PII-Guard-Connection", connection);
          return fetch(input, { ...init, credentials: "same-origin", headers });
        };
        try {
          const chat = createHttpChat({ fetch: doFetch });
          const models = await chat.listModels!(abort.signal);
          const model = pickDefaultModel(models, null);
          if (!model) throw new Error("No available model");
          const turn = await chat.send({ model, mode: "fast", language, sessionId: null, signal: abort.signal, messages: [{ role: "system", content: SYSTEM_PROMPT }, { role: "user", content: text }] });
          if (!turn.answer || !turn.maskedAnswer || !turn.maskedMessages.length || turn.finishReason === "length") throw new Error("Incomplete answer");
          next = { sample_id: "custom", language, original: text, masked: turn.maskedMessages.filter((m) => m.role !== "system").map((m) => m.content).join("\n"), answer: turn.maskedAnswer, restored: turn.answer, entities: [], model, session_id: turn.sessionId, request_id: "" };
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
    } catch (e) { setFailed(true); setAnnounce(""); setError(recovery(e, "site")); }
    finally { setRunning(false); }
  }

  // A run in flight or a failed one keeps the worked example on screen: a live failure never blanks it.
  const shown = result ?? (editable && signedIn ? null : EXAMPLES[language]);
  const counts = shown ? placeholderCounts(shown.masked) : [];
  const badge = running ? { tone: "", text: "Live run in progress" } : result ? { tone: "live", text: `Live result · answered by ${friendlyModel(result.model)}` } : failed ? { tone: "failed", text: "Live run did not complete · showing the example" } : { tone: "", text: "Example · not a live run" };

  return <div className="hosted">
    <a className="skip" href="#main">Skip to content</a>
    <div className="wrap">
      <header className="nav">
        <a className="brand" href="#">pii-guard</a>
        <nav aria-label="Main navigation" className="nav-links">
          <a className="nav-text" href="#demo">How it works</a><a className="nav-text" href="#data">Your data</a><a className="nav-text" href={`${SOURCE}#quick-start`}>Self-host</a>
          {signedIn ? <ButtonLink variant="primary" href={hasConsole ? "#overview" : "#account"}>{hasConsole ? "Open console" : "Your account"}</ButtonLink> : <ButtonLink variant="primary" href={loginUrl}>Sign in with Google</ButtonLink>}
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <section className="intro" aria-labelledby="intro-heading">
          <div className="intro-copy">
            <h1 id="intro-heading">Reduce personal data<br /><span>exposure to AI.</span></h1>
            <p className="lead">A privacy firewall between your app and an AI model. pii-guard swaps names, e-mails and IDs for reversible placeholders before the request leaves, then puts the real values back in the answer. Hungarian first.</p>
            <ul className="proof" aria-label="Built on Meta’s models">
              <li>Answers from <strong>Meta’s Muse Spark</strong>, which only ever sees placeholders</li>
              <li>Open NER model on <a href={NER_MODEL}>Hugging Face ↗</a>, fine-tuned from Meta’s XLM-RoBERTa</li>
              <li>Apache-2.0 · self-host it or try it here</li>
            </ul>
            <div className="actions"><ButtonLink variant="primary" href="#demo">See the demo ↓</ButtonLink><a href={SOURCE}>Source on GitHub ↗</a></div>
            <p className="compliance-note">Helps with data minimisation. Using pii-guard does not by itself make a deployment GDPR or EU AI Act compliant.</p>
          </div>
          <MiniFlow />
        </section>
        <section className="demo" id="demo" aria-labelledby="demo-heading" aria-busy={running}>
          <div className="demo-head">
            <div className="stack"><h2 id="demo-heading">Follow the data, both ways.</h2><p className="muted">Your text → pii-guard masks it → Meta’s model answers → pii-guard puts the values back.</p></div>
            <span className={`badge ${badge.tone}`}>{badge.text}</span>
          </div>
          <div className="controls">
            <div className="field-group"><span className="field-label" id="language-label">Sample language</span><SegmentedControl label="Sample language" options={LANGUAGES.map((l) => ({ ...l, disabled: running }))} value={language} onChange={(v) => reset(v as Language)} /></div>
            {signedIn && <Field label="Input" className="min-w-36 max-w-56 flex-1"><Select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">Curated scenario</option><option value="custom">Your text</option></Select></Field>}
            {canRun && <Button variant="primary" busy={running} disabled={!running && editable && !text.trim()} onClick={() => void run()}>{running ? "Running…" : editable ? "Run your text" : "Run live example"}</Button>}
            {!account && <Button variant="primary" disabled>{accountError ? "Run live example" : "Checking availability…"}</Button>}
            {(result || failed) && !running && <Button onClick={() => reset()}>Show the example</Button>}
          </div>
          {account && !signedIn && sponsoredOff && <div className="notice paused"><p>Live guest runs are paused right now. The worked example below shows the same flow, step by step.</p><ButtonLink href={loginUrl}>Sign in with Google to run your own text</ButtonLink></div>}
          {!account && accountError && <p className="notice">Live API unavailable. The worked example below still shows the flow. <a href="#account">Check the connection ↓</a></p>}
          {editable && signedIn && <div className="stage editor"><Field label="Your text"><Textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></Field><Field label="Model connection" hint="The Azure-hosted guard receives this text. Use synthetic data while evaluating."><Select value={connection} disabled={running} onChange={(e) => setConnection(e.target.value)}><option value="">Sponsored Meta</option>{account!.connections.map((c) => <option key={c.id} value={c.id}>{c.provider} · {c.origin}</option>)}</Select></Field></div>}
          <p className="sr-only" role="status" aria-live="polite">{announce}</p>
          {running && <div className="notice progress"><ol aria-label="Live run progress">{STEPS.map((label, i) => <li key={label} data-state={i < step ? "done" : i === step ? "active" : "todo"}>{label}{i === step && <span className="sr-only"> (in progress)</span>}</li>)}</ol><p className="muted">Usually a few seconds. If the service has been idle, the first run can take a minute while it starts.</p></div>}
          {error && <Notice tone="danger" live className="m-4 sm:m-6">{error}</Notice>}
          <div className={`legend ${shown ? "" : "hidden"}`} aria-hidden="true"><span><i className="hl hl-original">Minta</i> personal data in your text</span><span><i className="hl hl-placeholder">[[PERSON_…]]</i> what the model sees</span><span><i className="hl hl-restored">Minta</i> value put back</span></div>
          {shown ? <div className={`flow ${running ? "dimmed" : ""}`}>
            <Stage number="1" title="Your text" side="Stays with pii-guard"><OriginalText text={shown.original} masked={shown.masked} entities={result?.entities} /></Stage>
            <div className="model-band" role="group" aria-labelledby="band-label">
              <p className="band-label" id="band-label">Model boundary: only this crosses to Meta’s model</p>
              <Stage number="2" title="Sent to the model" side="Masked request" extra={counts.length > 0 && <ul className="entities" aria-label="Detected entity types">{counts.map(([type, key, n]) => <li key={key}>{metaFor(type).label} <span className="count">{n}</span></li>)}</ul>}>
                <PlaceholderText text={shown.masked} />
              </Stage>
              <Stage number="3" title="Model answer" side="Placeholders only"><PlaceholderText text={shown.answer} /></Stage>
            </div>
            <Stage number="4" title="Restored answer" side="Values put back by pii-guard"><RestoredAnswer answer={shown.answer} restored={shown.restored} masked={shown.masked} original={shown.original} /></Stage>
          </div> : <p className="notice">Write your text above and run it to see each step.</p>}
          <p className="notice note">{result ? "A real guard and model completed this request. Inspect the masked request: detection can miss values. This is pseudonymisation, not anonymisation." : "Hand-written example: no detection or model ran. Live runs use server-curated synthetic samples and may produce different results."}</p>
        </section>
        <section className="deployment stack" aria-labelledby="deployment-heading">
          <h2 id="deployment-heading">Text and images. Two ways to host.</h2>
          <p className="muted">The self-hosted stack can link detected image text and text pseudonyms in a shared session. Image regions are masked; their original pixels are not reconstructed when an answer is restored. <a href={`${DOCS}/why-pii-guard.md#9-images-faces-signatures-machine-readable-zones`}>Explore image masking ↗</a></p>
          <table className="mode-comparison">
            <caption className="sr-only">Deployment modes, availability and trust boundaries</caption>
            <thead><tr><th scope="col">Mode and availability</th><th scope="col">Where originals are processed</th><th scope="col">Who operates it</th></tr></thead>
            <tbody>
              <tr><th scope="row">Self-hosted<span className="mode-status">Available · open source</span></th><td data-label="Originals">The guard and vault run on your infrastructure. Keeping all raw processing local requires local detectors and models. Some detector services receive originals, including remote SAM image segmentation.</td><td data-label="Operations">You operate the full stack: guard, dashboard and vault. You choose the upstream model and its data-use terms.</td></tr>
              <tr><th scope="row">Hosted gateway<span className="mode-status">Preview · the example for everyone; your own text and images after sign-in</span></th><td data-label="Originals">Our Azure-hosted guard receives raw prompts and holds the restoration mappings. It masks detected values before forwarding to the upstream model.</td><td data-label="Operations">We operate the guard. You use the hosted interface and choose an available upstream or connect a provider key. Evaluate with synthetic data.</td></tr>
            </tbody>
          </table>
        </section>
        <section className="data stack" id="data" aria-labelledby="data-heading">
          <h2 id="data-heading">What happens to your data</h2>
          <p className="muted">How this hosted preview handles what you send. Self-hosting keeps all of it on your own infrastructure.</p>
          <dl className="data-list">
            <div><dt>Where it runs</dt><dd>On Microsoft Azure in Sweden Central (EU). Text and images are processed in the service’s memory; there is no content archive and no backup of the mappings. Azure operators can access process memory.</dd></div>
            <div><dt>Guest demo</dt><dd>You can’t type anything. A fixed, fictional sample is masked here, and only the masked sample goes to Meta’s model, when the sponsored budget allows.</dd></div>
            <div><dt>Signed in</dt><dd>Google receives your sign-in (name, e-mail and profile only). Your text reaches our Azure service in full; only the masked text goes to Meta’s model or to the provider you connect.</dd></div>
            <div><dt>Images</dt><dd>Signed-in users only. Read and masked inside the service with local OCR and an on-device face and ID-photo detector, never stored and never sent to a model. Signatures and stamps stay visible.</dd></div>
            <div><dt>How long</dt><dd>Placeholder mappings expire after 1 hour without use. Your last 50 masked requests are kept in memory for your activity log. A restart clears both. Expiry makes them unavailable, but doesn’t prove the memory is physically erased.</dd></div>
            <div><dt>What Meta receives</dt><dd>Masked text only. Detection can miss values, and context can still identify someone. Meta’s standard terms exclude training on submitted content but allow retention as needed; processing there isn’t guaranteed to stay in the EU.</dd></div>
            <div><dt>Limits of the promise</dt><dd>Pseudonymisation is not anonymisation. Don’t submit highly sensitive data or content you lack the authority to process.</dd></div>
          </dl>
          <a href={`${DOCS}/hosted.md`}>Hosted processing and retention, in full ↗</a>
        </section>
        <section className="account-panel stack" id="account" aria-labelledby="account-heading">
          <h2 id="account-heading">Try it now. Connect when you’re ready.</h2>
          {!signedIn && <p className="measure">{sponsoredOff ? "Live guest runs are paused. Sign in with Google to run your own text with your own provider key, create projects and connect your application through a gateway endpoint." : "No login needed for the curated live example. Sign in with Google to run your own text, create projects and connect your application through a gateway endpoint."}</p>}
          {accountError ? <Notice tone="danger" live action={<Button size="sm" onClick={() => void refresh()}>Reconnect to API</Button>}>{accountError}</Notice> : !account ? <p className="muted">Checking live availability…</p> : <>
            {(!sponsoredOff || signedIn) && <p className="muted tabular-nums">{usageLine(account)}</p>}
            <Limits account={account} hideZero />
            {signedIn ? <><p>You’re signed in. Your projects, endpoints, provider connections and activity are in the console.</p><div className="actions">{hasConsole && <ButtonLink variant="primary" href="#overview">Open console</ButtonLink>}<a href={account.logout_url || LOGOUT}>Sign out</a></div></> : <div><ButtonLink variant="primary" href={loginUrl}>Sign in with Google</ButtonLink></div>}
            <p className="note measure">Sessions and provider connections are temporary. A guard restart loses ephemeral state; start a fresh request if restoration expires. Provider keys are kept by the guard for the connection lifetime, never saved in browser storage.</p>
          </>}
        </section>
        <section className="privacy" id="privacy" aria-label="Privacy and evidence">
          <div className="stack"><h2>Know the trust boundary.</h2><p>A missed value can reach the model. Even with names removed, surrounding context can identify a person. Inspect the masked request and evaluate the detector for your workload.</p><p>Fail-closed handling blocks requests when processing fails; it does not eliminate leaks from missed detections. Reversible pseudonymisation reduces exposure, but it is not anonymity.</p><p>Any remote detector you enable also receives raw data and becomes part of your trust boundary. Choose its deployment and terms accordingly.</p><a href={`${DOCS}/privacy-model.md`}>Read the privacy model ↗</a></div>
          <div className="stack"><h2>Measured, not guaranteed.</h2><p>Hungarian names, identifiers and inflections need more than an English rule list. Evaluate recall and leak rate against the versioned synthetic benchmark before using real data.</p><p>Results depend on the detector, mode, corpus and model. The source reports include run dates and configuration; this page does not present an undated headline score.</p><div className="actions"><a href={`${DOCS}/benchmarks.md`}>Benchmark results ↗</a><a href={`${DOCS}/evaluation.md`}>Evaluation method ↗</a></div></div>
        </section>
      </main>
      <footer>
        <a className="brand" href="#">pii-guard</a>
        <p className="muted">Open-source privacy firewall for AI agents. All examples on this page are fictional.</p>
        <div className="actions"><a href={SOURCE}>Source code</a><a href={`${SOURCE}#quick-start`}>Self-host</a><a href={`${DOCS}/architecture.md`}>Integrate</a><a href="#data">Your data</a>
          {PRIVACY_NOTICE_URL ? <a href={PRIVACY_NOTICE_URL}>Privacy notice</a> : <span className="muted">Privacy notice (coming soon)</span>}
          {CONTACT_URL ? <a href={CONTACT_URL}>Contact</a> : <span className="muted">Contact (coming soon)</span>}
        </div>
        <p className="note">{OPERATOR ? `Operated by ${OPERATOR}` : "Operator details (coming soon)"} · Apache-2.0 · Hungarian first, other EU languages next.</p>
      </footer>
    </div>
  </div>;
}

function Stage({ number, title, side, className = "", extra, children }: { number: string; title: string; side: string; className?: string; extra?: ReactNode; children?: ReactNode }) {
  return <article className={`stage ${className}`} aria-labelledby={`stage-${number}`}><div className="stage-title"><span className="step" aria-hidden="true">{number}</span><div><h3 id={`stage-${number}`}><span className="sr-only">Step {number}: </span>{title}</h3><p className="stage-side">{side}</p></div></div><p className="document">{children}</p>{extra}</article>;
}

/** The hero's picture of the product: one value, there and back. Fictional. */
function MiniFlow() {
  return <figure className="mini-flow" aria-labelledby="mini-flow-caption">
    <figcaption id="mini-flow-caption" className="sr-only">One name, there and back: you send it, the model sees only a placeholder, and you get the real name back.</figcaption>
    <div className="mini-row"><span className="mini-label">You send</span><p className="document">Name: <mark className="hl hl-original">Minta Réka</mark></p></div>
    <div className="mini-guard" aria-hidden="true"><span>pii-guard masks</span></div>
    <div className="mini-row model"><span className="mini-label">Meta’s model sees</span><p className="document">Name: <mark className="hl hl-placeholder">[[PERSON_3f9a1c]]</mark></p></div>
    <div className="mini-guard" aria-hidden="true"><span>pii-guard restores</span></div>
    <div className="mini-row"><span className="mini-label">You get back</span><p className="document">Dear <mark className="hl hl-restored">Minta Réka</mark>, …</p></div>
  </figure>;
}
