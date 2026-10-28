import { useEffect, useRef, useState, type ReactNode } from "react";
import { createHttpChat, pickDefaultModel, SYSTEM_PROMPT } from "../api/chat";
import { Button, ButtonLink, Field, Notice, Select, Textarea } from "../components/ui";
import { request, recovery, type Account, type DemoResult, type Requester } from "./api";
import { Limits } from "./AccountPanels";
import { SITE_HASHES, SOURCE, time, useAccount, useHash, type HostedSession } from "./session";
import "./hosted.css";

// Without a return address Easy Auth ends on its own bare "signed in" page (LAB-1425);
// sign-in returns to the console (LAB-1430).
const LOGIN = "/.auth/login/google?post_login_redirect_uri=%2F%23overview";
const LOGOUT = "/.auth/logout?post_logout_redirect_uri=%2F";
const EXAMPLES = {
  hu: { original: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: Minta Réka\nE-mail: reka.minta@example.com", masked: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: [[PERSON_example]]\nE-mail: [[EMAIL_example]]", answer: "Kedves [[PERSON_example]]! A visszatérítésről a [[EMAIL_example]] címre küldünk értesítést.", restored: "Kedves Minta Réka! A visszatérítésről a reka.minta@example.com címre küldünk értesítést." },
  en: { original: "Please draft a short refund reply.\n\nName: Robin Example\nEmail: robin.example@example.com", masked: "Please draft a short refund reply.\n\nName: [[PERSON_example]]\nEmail: [[EMAIL_example]]", answer: "Dear [[PERSON_example]], we will send your refund update to [[EMAIL_example]].", restored: "Dear Robin Example, we will send your refund update to robin.example@example.com." },
};

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
  const [language, setLanguage] = useState<"hu" | "en">("hu");
  const [result, setResult] = useState<DemoResult | null>(null);
  const [kind, setKind] = useState<"static" | "live">("static");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState(EXAMPLES.hu.original);
  const [editable, setEditable] = useState(false);
  const [connection, setConnection] = useState("");
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  function reset(nextLanguage = language) {
    setLanguage(nextLanguage); setText(EXAMPLES[nextLanguage].original); setResult(null); setKind("static"); setError("");
  }
  async function run() {
    setRunning(true); setError(""); setResult(null); setKind("live");
    try {
      let next: DemoResult;
      if (editable && account?.authenticated) {
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
      void refresh();
    } catch (e) { setError(recovery(e, "site")); }
    finally { setRunning(false); }
  }
  const shown = kind === "static" ? EXAMPLES[language] : result;
  const types = result ? [...new Set(result.entities.map((e) => e.type))] : ["PERSON", "EMAIL"];

  return <div className="hosted">
    <a className="skip" href="#main">Skip to content</a>
    <div className="wrap">
      <header className="nav">
        <a className="brand" href="#">pii-guard</a>
        <nav aria-label="Main navigation" className="nav-links">
          <a href="#demo">Try demo</a><a href="#privacy">Privacy</a><a href={`${SOURCE}#quick-start`}>Self-host</a>
          <ButtonLink href={account?.authenticated ? (hasConsole ? "#overview" : "#account") : account?.login_url ?? LOGIN}>{account?.authenticated ? (hasConsole ? "Open console" : "Your account") : "Sign in"}</ButtonLink>
        </nav>
      </header>
      <main id="main">
        <section className="intro">
          <h1>Reduce personal data<br /><span>exposure to AI.</span></h1>
          <p>A privacy firewall between your application and an AI model. Replace detected personal data with keyed placeholders before forwarding the request, then restore the values in the answer. Built for Hungarian first. The self-hosted stack masks text and images; in this hosted preview, image masking is available after you sign in.</p>
          <p className="compliance-note">Support data minimisation in your privacy and compliance work. pii-guard does not automatically make a deployment GDPR or EU AI Act compliant.</p>
          <div className="actions"><ButtonLink variant="primary" href="#demo">Try the demo ↓</ButtonLink><a href={SOURCE}>Explore on GitHub ↗</a></div>
        </section>
        <section className="demo" id="demo" aria-labelledby="demo-heading">
          <div className="demo-head">
            <div className="stack"><h2 id="demo-heading">Follow the data, both ways.</h2><p className="muted">Original → detected and masked → model answer → restored.</p></div>
            <span className={`badge ${result ? "live" : ""}`}>{kind === "static" ? "Static illustration · synthetic" : running ? "Live request in progress" : result ? `Live result · ${result.model}` : "Live request did not complete"}</span>
          </div>
          <div className="controls">
            <Field label="Scenario language" className="min-w-36 flex-1"><Select value={language} disabled={running} onChange={(e) => reset(e.target.value as "hu" | "en")}><option value="hu">Hungarian</option><option value="en">English</option></Select></Field>
            {account?.authenticated && <Field label="Input" className="min-w-36 flex-1"><Select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">Curated scenario</option><option value="custom">Your text</option></Select></Field>}
            <Button variant="primary" busy={running} disabled={!running && (!account || (editable && !text.trim()))} onClick={() => void run()}>{running ? "Processing…" : editable ? "Run your text" : "Run live example"}</Button>
            {kind === "live" && !running && <Button onClick={() => reset()}>Show static example</Button>}
          </div>
          {!account && <p className="notice" role="status">{accountError ? <>Live API unavailable. <a href="#account">Check connection and retry ↓</a></> : "Checking live availability…"}</p>}
          {editable && account?.authenticated && <div className="stage"><Field label="Your text"><Textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></Field><Field label="Model connection" hint="The Azure-hosted guard receives this text. Use synthetic data while evaluating."><Select value={connection} disabled={running} onChange={(e) => setConnection(e.target.value)}><option value="">Sponsored Meta</option>{account.connections.map((c) => <option key={c.id} value={c.id}>{c.provider} · {c.origin}</option>)}</Select></Field></div>}
          <div aria-live="polite">{running && <p className="notice" role="status">The guard is detecting and masking, then waiting for the model. This can take a few minutes.</p>}{error && <Notice tone="danger" live className="m-4 sm:m-6">{error}</Notice>}</div>
          <div className="flow">
            <Stage number="1" title="Original input" text={shown?.original} fallback="A fresh original will appear only when the live request completes." />
            <Stage number="2" title="Exact masked request" text={shown?.masked} className="model" fallback="No completed masked request is available."><div className="entities" aria-label="Detected entity types">{shown && types.map((type) => <span key={type}>{type}</span>)}{result?.sample_id === "custom" && <span>Placeholder types are visible in the request above.</span>}</div></Stage>
            <Stage number="3" title="Model answer" text={shown?.answer} className="model" fallback="No completed model answer is available." />
            <Stage number="4" title="Restored answer" text={shown?.restored} className="restored" fallback="No completed restored answer is available." />
          </div>
          <p className="notice note">{kind === "static" ? "This hand-written illustration explains the mechanism. No detection or model ran. Live requests use server-curated synthetic scenarios and may produce different results." : result ? "A real guard and model completed this request. Inspect the masked request: detection can miss values. This is pseudonymization, not anonymization." : "No static answer is substituted for a failed live request."}</p>
        </section>
        <section className="deployment stack" aria-labelledby="deployment-heading">
          <h2 id="deployment-heading">Text and images. Two ways to host.</h2>
          <p className="muted">The self-hosted stack can link detected image text and text pseudonyms in a shared session. Image regions are masked; their original pixels are not reconstructed when an answer is restored. <a href={`${SOURCE}/blob/develop/docs/why-pii-guard.md#9-images-faces-signatures-machine-readable-zones`}>Explore image masking ↗</a></p>
          <table className="mode-comparison">
            <caption className="sr-only">Deployment modes, availability and trust boundaries</caption>
            <thead><tr><th scope="col">Mode and availability</th><th scope="col">Where originals are processed</th><th scope="col">Who operates it</th></tr></thead>
            <tbody>
              <tr><th scope="row">Self-hosted<span className="mode-status">Available · open source</span></th><td data-label="Originals">The guard and vault run on your infrastructure. Keeping all raw processing local requires local detectors and models. Some detector services receive originals, including remote SAM image segmentation.</td><td data-label="Operations">You operate the full stack: guard, dashboard and vault. You choose the upstream model and its data-use terms.</td></tr>
              <tr><th scope="row">Hosted gateway<span className="mode-status">Preview · text for everyone, images after sign-in</span></th><td data-label="Originals">Our Azure-hosted guard receives raw prompts and holds the restoration mappings. It masks detected values before forwarding to the upstream model.</td><td data-label="Operations">We operate the guard. You use the hosted interface and choose an available upstream or connect a provider key. Evaluate with synthetic data.</td></tr>
            </tbody>
          </table>
        </section>
        <section className="account-panel stack" id="account" aria-labelledby="account-heading">
          <h2 id="account-heading">Try it now. Connect when you’re ready.</h2>
          {!account?.authenticated && <p>No login needed for curated live examples. Sign in with Google to edit text, create projects and connect your application through a gateway endpoint.</p>}
          {accountError ? <Notice tone="danger" live action={<Button size="sm" onClick={() => void refresh()}>Reconnect to API</Button>}>{accountError}</Notice> : !account ? <p role="status">Checking live availability…</p> : <>
            <p className="muted">{account.usage.requests_today} requests used today. Allowance resets: {time(account.usage.resets_at)}.</p>
            <Limits account={account} />
            {account.authenticated ? <><p>You’re signed in. Your projects, endpoints, provider connections and activity are in the console.</p><div className="actions">{hasConsole && <ButtonLink variant="primary" href="#overview">Open console</ButtonLink>}<a href={account.logout_url || LOGOUT}>Sign out</a></div></> : <div><ButtonLink variant="primary" href={account.login_url || LOGIN}>Continue with Google</ButtonLink></div>}
            <p className="note">Sessions and provider connections are temporary. A guard restart loses ephemeral state; start a fresh request if restoration expires. Provider keys are kept by the guard for the connection lifetime, never saved in browser storage.</p>
          </>}
        </section>
        <section className="privacy" id="privacy" aria-label="Privacy and evidence">
          <div className="stack"><h2>Know the trust boundary.</h2><p>A missed value can reach the model. Even with names removed, surrounding context can identify a person. Inspect the masked request and evaluate the detector for your workload.</p><p>Fail-closed handling blocks requests when processing fails; it does not eliminate leaks from missed detections. Reversible pseudonymisation reduces exposure, but it is not anonymity.</p><p>Any remote detector you enable also receives raw data and becomes part of your trust boundary. Choose its deployment and terms accordingly.</p><a href={`${SOURCE}/blob/develop/docs/privacy-model.md`}>Read the privacy model ↗</a></div>
          <div className="stack"><h2>Measured, not guaranteed.</h2><p>Hungarian names, identifiers and inflections need more than an English rule list. Evaluate recall and leak rate against the versioned synthetic benchmark before using real data.</p><p>Results depend on the detector, mode, corpus and model. The source reports include run dates and configuration; this page does not present an undated headline score.</p><div className="actions"><a href={`${SOURCE}/tree/develop/eval/results/runs`}>Benchmark runs ↗</a><a href={`${SOURCE}/blob/develop/docs/evaluation.md`}>Evaluation method ↗</a></div></div>
        </section>
      </main>
      <footer><a className="brand" href="#">pii-guard</a><p className="muted">Open-source privacy firewall for AI agents. All examples on this page are fictional.</p><div className="actions"><a href={SOURCE}>Source code</a><a href={`${SOURCE}#quick-start`}>Self-host</a><a href={`${SOURCE}/blob/develop/docs/architecture.md`}>Integrate</a><a href="#privacy">Privacy</a></div><p className="note">Apache-2.0 · Hungarian first, other EU languages next.</p></footer>
    </div>
  </div>;
}

function Stage({ number, title, text, fallback, className = "", children }: { number: string; title: string; text?: string; fallback: string; className?: string; children?: React.ReactNode }) {
  return <article className={`stage ${className}`}><div className="stage-title"><span>{number}</span><h3>{title}</h3></div><p className="document">{text ?? fallback}</p>{children}</article>;
}
