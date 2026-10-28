import { Workspace } from "../projects/Workspace";
import { setSelectedProject, useSelectedProject } from "../projects/selection";
import { useEffect, useRef, useState } from "react";
import { createHttpChat, pickDefaultModel, SYSTEM_PROMPT } from "../api/chat";
import { request, recovery, type Account, type DemoResult, type Requester } from "./api";
import "./hosted.css";

const SOURCE = "https://github.com/watt-mind/pii-guard";
const EXAMPLES = {
  hu: { original: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: Minta Réka\nE-mail: reka.minta@example.com", masked: "Kérlek, írj rövid választ a visszatérítésről.\n\nNév: [[PERSON_example]]\nE-mail: [[EMAIL_example]]", answer: "Kedves [[PERSON_example]]! A visszatérítésről a [[EMAIL_example]] címre küldünk értesítést.", restored: "Kedves Minta Réka! A visszatérítésről a reka.minta@example.com címre küldünk értesítést." },
  en: { original: "Please draft a short refund reply.\n\nName: Robin Example\nEmail: robin.example@example.com", masked: "Please draft a short refund reply.\n\nName: [[PERSON_example]]\nEmail: [[EMAIL_example]]", answer: "Dear [[PERSON_example]], we will send your refund update to [[EMAIL_example]].", restored: "Dear Robin Example, we will send your refund update to robin.example@example.com." },
};

function time(value: string | undefined) {
  if (!value) return "not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "not available" : date.toLocaleString();
}

export function HostedApp({ call = request }: { call?: Requester }) {
  const project = useSelectedProject();
  return <HostedContent key={project ?? "default"} call={call} projectId={project ?? undefined} />;
}
const selectProject = (project: { id: string }) => setSelectedProject(project.id);

function HostedContent({ call, projectId }: { call: Requester; projectId?: string }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [accountError, setAccountError] = useState("");
  const [language, setLanguage] = useState<"hu" | "en">("hu");
  const [result, setResult] = useState<DemoResult | null>(null);
  const [kind, setKind] = useState<"static" | "live">("static");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState(EXAMPLES.hu.original);
  const [editable, setEditable] = useState(false);
  const [connection, setConnection] = useState("");
  const controller = useRef<AbortController | null>(null);

  async function refresh() {
    try { const next = await call<Account>("/v1/account"); if (next.mode !== "hosted") throw new Error(); setAccount(next); setAccountError(""); }
    catch (e) { setAccount(null); setAccountError(recovery(e)); }
  }
  useEffect(() => {
    let active = true;
    call<Account>("/v1/account").then((next) => { if (next.mode !== "hosted") throw new Error(); if (active) setAccount(next); }).catch((e: unknown) => { if (active) setAccountError(recovery(e)); });
    return () => { active = false; controller.current?.abort(); };
  }, [call]);

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
    } catch (e) { setError(recovery(e)); }
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
          <a className="button" href={account?.authenticated ? "#account" : "/.auth/login/google"}>{account?.authenticated ? "Your account" : "Sign in"}</a>
        </nav>
      </header>
      <main id="main">
        <section className="intro">
          <h1>Reduce personal data<br /><span>exposure to AI.</span></h1>
          <p>A privacy firewall between your application and an AI model. Replace detected personal data with keyed placeholders before forwarding the request, then restore the values in the answer. Built for Hungarian first. The self-hosted stack supports text and image masking; this hosted preview is text-only.</p>
          <p className="compliance-note">Support data minimisation in your privacy and compliance work. PII Guard does not automatically make a deployment GDPR or EU AI Act compliant.</p>
          <div className="actions"><a className="button primary" href="#demo">Try the demo ↓</a><a href={SOURCE}>Explore on GitHub ↗</a></div>
        </section>
        <section className="demo" id="demo" aria-labelledby="demo-heading">
          <div className="demo-head">
            <div className="stack"><h2 id="demo-heading">Follow the data, both ways.</h2><p className="muted">Original → detected and masked → model answer → restored.</p></div>
            <span className={`badge ${result ? "live" : ""}`}>{kind === "static" ? "Static illustration · synthetic" : running ? "Live request in progress" : result ? `Live result · ${result.model}` : "Live request did not complete"}</span>
          </div>
          <div className="controls">
            <label>Scenario language<select value={language} disabled={running} onChange={(e) => reset(e.target.value as "hu" | "en")}><option value="hu">Hungarian</option><option value="en">English</option></select></label>
            {account?.authenticated && <label>Input<select disabled={running} value={editable ? "custom" : "curated"} onChange={(e) => { setEditable(e.target.value === "custom"); reset(); }}><option value="curated">Curated scenario</option><option value="custom">Your text</option></select></label>}
            <button className="primary" disabled={running || !account || (editable && !text.trim())} onClick={() => void run()}>{running ? "Processing…" : editable ? "Run your text" : "Run live example"}</button>
            {kind === "live" && !running && <button onClick={() => reset()}>Show static example</button>}
          </div>
          {!account && <p className="notice" role="status">{accountError ? <>Live API unavailable. <a href="#account">Check connection and retry ↓</a></> : "Checking live availability…"}</p>}
          {editable && account?.authenticated && <div className="stage stack"><label>Your text<textarea value={text} disabled={running} onChange={(e) => { setText(e.target.value); setResult(null); }} /></label><label>Model connection<select value={connection} disabled={running} onChange={(e) => setConnection(e.target.value)}><option value="">Sponsored Meta</option>{account.connections.map((c) => <option key={c.id} value={c.id}>{c.provider} · {c.origin}</option>)}</select></label><small>The Azure-hosted guard receives this text. Use synthetic data while evaluating.</small></div>}
          <div aria-live="polite">{running && <p className="notice" role="status">The guard is detecting and masking, then waiting for the model. This can take a few minutes.</p>}{error && <p className="error" role="alert">{error}</p>}</div>
          <div className="flow">
            <Stage number="1" title="Original input" text={shown?.original} fallback="A fresh original will appear only when the live request completes." />
            <Stage number="2" title="Exact masked request" text={shown?.masked} className="model" fallback="No completed masked request is available."><div className="entities" aria-label="Detected entity types">{shown && types.map((type) => <span key={type}>{type}</span>)}{result?.sample_id === "custom" && <span>Placeholder types are visible in the request above.</span>}</div></Stage>
            <Stage number="3" title="Model answer" text={shown?.answer} className="model" fallback="No completed model answer is available." />
            <Stage number="4" title="Restored answer" text={shown?.restored} className="restored" fallback="No completed restored answer is available." />
          </div>
          <p className="notice"><small>{kind === "static" ? "This hand-written illustration explains the mechanism. No detection or model ran. Live requests use server-curated synthetic scenarios and may produce different results." : result ? "A real guard and model completed this request. Inspect the masked request: detection can miss values. This is pseudonymization, not anonymization." : "No static answer is substituted for a failed live request."}</small></p>
        </section>
        <section className="deployment stack" aria-labelledby="deployment-heading">
          <h2 id="deployment-heading">Text and images. Two ways to host.</h2>
          <p className="muted">The self-hosted stack can link detected image text and text pseudonyms in a shared session. Image regions are masked; their original pixels are not reconstructed when an answer is restored. <a href={`${SOURCE}/blob/develop/docs/why-pii-guard.md#9-images-faces-signatures-machine-readable-zones`}>Explore image masking ↗</a></p>
          <table className="mode-comparison">
            <caption className="sr-only">Deployment modes, availability and trust boundaries</caption>
            <thead><tr><th scope="col">Mode and availability</th><th scope="col">Where originals are processed</th><th scope="col">Who operates it</th></tr></thead>
            <tbody>
              <tr><th scope="row">Self-hosted<span className="mode-status">Available · open source</span></th><td data-label="Originals">The guard and vault run on your infrastructure. Keeping all raw processing local requires local detectors and models. Some detector services receive originals, including remote SAM image segmentation.</td><td data-label="Operations">You operate the full stack: guard, dashboard and vault. You choose the upstream model and its data-use terms.</td></tr>
              <tr><th scope="row">Hosted gateway<span className="mode-status">Text-only preview · not publicly live</span></th><td data-label="Originals">Our Azure-hosted guard receives raw prompts and holds the restoration mappings. It masks detected values before forwarding to the upstream model.</td><td data-label="Operations">We operate the guard. You use the hosted interface and choose an available upstream or connect a provider key. Evaluate with synthetic data.</td></tr>
            </tbody>
          </table>
        </section>
        <section className="account-panel stack" id="account" aria-labelledby="account-heading">
          <h2 id="account-heading">Try it now. Connect when you’re ready.</h2>
          {!account?.authenticated && <p>No login needed for curated live examples. Sign in with Google to edit text, create projects and connect your application through a gateway endpoint.</p>}
          {accountError ? <div className="stack"><p className="error" role="alert">{accountError}</p><div><button onClick={() => void refresh()}>Reconnect to API</button></div></div> : !account ? <p role="status">Checking live availability…</p> : <>
            <p className="muted">{account.usage.requests_today} requests used today. Allowance resets: {time(account.usage.resets_at)}.</p>
            <Limits account={account} />
            {account.authenticated ? <><p>You’re signed in. Each project keeps its endpoints, policies and temporary sessions together.</p><Workspace call={call} hosted projectId={projectId} onProject={selectProject} /><Settings call={call} account={account} refresh={refresh} onDisconnect={(id) => { if (connection === id) setConnection(""); }} /><a href="/.auth/logout">Sign out</a></> : <div className="stack"><div><a className="button primary" href="/.auth/login/google">Continue with Google</a></div></div>}
            <small>Sessions and provider connections are temporary. A guard restart loses ephemeral state; start a fresh request if restoration expires. Provider keys are kept by the guard for the connection lifetime, never saved in browser storage.</small>
          </>}
        </section>
        <section className="privacy" id="privacy" aria-label="Privacy and evidence">
          <div className="stack"><h2>Know the trust boundary.</h2><p>A missed value can reach the model. Even with names removed, surrounding context can identify a person. Inspect the masked request and evaluate the detector for your workload.</p><p>Fail-closed handling blocks requests when processing fails; it does not eliminate leaks from missed detections. Reversible pseudonymisation reduces exposure, but it is not anonymity.</p><p>Any remote detector you enable also receives raw data and becomes part of your trust boundary. Choose its deployment and terms accordingly.</p><a href={`${SOURCE}/blob/develop/docs/privacy-model.md`}>Read the privacy model ↗</a></div>
          <div className="stack"><h2>Measured, not guaranteed.</h2><p>Hungarian names, identifiers and inflections need more than an English rule list. Evaluate recall and leak rate against the versioned synthetic benchmark before using real data.</p><p>Results depend on the detector, mode, corpus and model. The source reports include run dates and configuration; this page does not present an undated headline score.</p><div className="actions"><a href={`${SOURCE}/tree/develop/eval/results/runs`}>Benchmark runs ↗</a><a href={`${SOURCE}/blob/develop/docs/evaluation.md`}>Evaluation method ↗</a></div></div>
        </section>
      </main>
      <footer><a className="brand" href="#">pii-guard</a><p className="muted">Open-source privacy firewall for AI agents. All examples on this page are fictional.</p><div className="actions"><a href={SOURCE}>Source code</a><a href={`${SOURCE}#quick-start`}>Self-host</a><a href={`${SOURCE}/blob/develop/docs/architecture.md`}>Integrate</a><a href="#privacy">Privacy</a></div><small>Apache-2.0 · Hungarian first, other EU languages next.</small></footer>
    </div>
  </div>;
}

function Stage({ number, title, text, fallback, className = "", children }: { number: string; title: string; text?: string; fallback: string; className?: string; children?: React.ReactNode }) {
  return <article className={`stage ${className}`}><div className="stage-title"><span>{number}</span><h3>{title}</h3></div><p className="document">{text ?? fallback}</p>{children}</article>;
}
function Limits({ account }: { account: Account }) {
  const entries = Object.entries(account.limits).filter(([, value]) => value !== null && typeof value !== "boolean");
  return <details><summary>Current server limits</summary><ul className="list">{entries.map(([key, value]) => <li key={key}><span>{key.replaceAll("_", " ")}</span><span>{String(value)}</span></li>)}</ul></details>;
}

function Settings({ call, account, refresh, onDisconnect }: { call: Requester; account: Account; refresh: () => Promise<void>; onDisconnect: (id: string) => void }) {
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function action(run: () => Promise<void>) { setBusy(true); setError(""); try { await run(); } catch (e) { setError(recovery(e)); } finally { setBusy(false); } }
  return <div className="stack settings">
    <div className="account-columns">
      <div className="stack"><h3>Bring your own model key</h3><p className="muted">Connections are held in memory by the hosted guard. Disconnect to remove a key. Requests use your provider’s terms and billing.</p>
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void action(async () => { const secret = apiKey; setApiKey(""); await call("/v1/account/connections", { provider, api_key: secret, ...(provider === "custom" ? { base_url: baseUrl } : {}) }); await refresh(); }); }}>
          <label>Provider<select disabled={busy} value={provider} onChange={(e) => setProvider(e.target.value)}>{["meta", "openai", "fireworks", "openrouter", "custom"].map((p) => <option key={p} value={p}>{p === "custom" ? "Custom public HTTPS endpoint" : p}</option>)}</select></label>
          {provider === "custom" && <label>Base URL<input required type="url" placeholder="https://api.example.com/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} pattern="https://.*" /><small>Public HTTPS only. Private and local network addresses are refused by the guard.</small></label>}
          <label>Provider API key<input required type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label><button disabled={busy || !apiKey} type="submit">{busy ? "Working…" : "Connect provider"}</button>
        </form>
        <ul className="list">{account.connections.map((c) => <li key={c.id}><div>{c.provider} · {c.origin}<br /><small>Expires {time(c.expires_at)}</small></div><button disabled={busy} onClick={() => void action(async () => { await call(`/v1/account/connections/${encodeURIComponent(c.id)}`, undefined, "DELETE"); onDisconnect(c.id); await refresh(); })}>Disconnect</button></li>)}</ul>
      </div>

    </div>
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
