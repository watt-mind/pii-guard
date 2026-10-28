import { useEffect, useRef, useState } from "react";
import { createHttpChat, pickDefaultModel, SYSTEM_PROMPT } from "../api/chat";
import { request, recovery, type Account, type DemoResult, type GuardKey, type Requester } from "./api";
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
        if (![next.original, next.masked, next.answer, next.restored, next.model].every((s) => typeof s === "string" && s.length > 0) || !Array.isArray(next.entities)) throw new Error("Incomplete demo");
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
          <h1>Useful answers.<br /><span>Less personal data exposed.</span></h1>
          <p>A privacy firewall between your application and an AI model. Detect personal data, replace it with keyed placeholders, then restore the values in the answer. Built for Hungarian first.</p>
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
        <section className="account-panel stack" id="account" aria-labelledby="account-heading">
          <h2 id="account-heading">Try it now. Connect when you’re ready.</h2>
          {!account?.authenticated && <p>No login needed for curated live examples. Sign in with Google to edit text, bring your own provider key and manage guard API keys.</p>}
          {accountError ? <div className="stack"><p className="error" role="alert">{accountError}</p><div><button onClick={() => void refresh()}>Reconnect to API</button></div></div> : !account ? <p role="status">Checking live availability…</p> : <>
            <p className="muted">{account.usage.requests_today} requests used today. Allowance resets: {time(account.usage.resets_at)}.</p>
            <Limits account={account} />
            {account.authenticated ? <><p>You’re signed in. Your text, provider connections and guard keys belong to this account.</p><Settings call={call} account={account} refresh={refresh} onDisconnect={(id) => { if (connection === id) setConnection(""); }} /><a href="/.auth/logout">Sign out</a></> : <div className="stack"><div><a className="button primary" href="/.auth/login/google">Continue with Google</a></div></div>}
            <small>Sessions and provider connections are temporary. A guard restart loses ephemeral state; start a fresh request if restoration expires. Provider keys are kept by the guard for the connection lifetime, never saved in browser storage.</small>
          </>}
        </section>
        <section className="privacy" id="privacy" aria-label="Privacy and evidence">
          <div className="stack"><h2>Know the trust boundary.</h2><p>The Azure-hosted guard receives originals and holds the mapping needed to restore them. The upstream model receives the masked request. If detection misses a value, that value can reach the model.</p><p>Self-host the guard to place that boundary on your own infrastructure. Any hosted detector you enable also becomes part of that boundary. Logs are designed to contain types and counts, not original values.</p><a href={`${SOURCE}/blob/develop/docs/privacy-model.md`}>Read the privacy model ↗</a></div>
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
  const [name, setName] = useState("");
  const [keys, setKeys] = useState<GuardKey[]>([]);
  const [created, setCreated] = useState("");
  const [copy, setCopy] = useState("Copy key");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { call<GuardKey[] | { keys: GuardKey[] }>("/v1/account/api-keys").then((payload) => setKeys(Array.isArray(payload) ? payload : payload.keys)).catch((e: unknown) => setError(recovery(e))); }, [call]);
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
      <div className="stack"><h3>Your guard API keys</h3><p className="muted">Use a guard key to authenticate an integration. Copy a new key now; it is shown only once.</p>
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void action(async () => { setCreated(""); const key = await call<GuardKey & { key: string }>("/v1/account/api-keys", { name }); setCreated(key.key); setCopy("Copy key"); setKeys((prev) => [...prev, { id: key.id, name: key.name, prefix: key.prefix, created_at: key.created_at }]); setName(""); }); }}><label>Key name<input required value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></label><button disabled={busy || !name.trim()} type="submit">Create guard key</button></form>
        {created && <div className="stack"><p className="secret">{created}</p><div className="actions"><button onClick={() => { void navigator.clipboard.writeText(created).then(() => setCopy("Copied")).catch(() => setCopy("Select and copy key")); }}>{copy}</button><button onClick={() => setCreated("")}>Dismiss key</button></div></div>}
        <ul className="list">{keys.map((key) => <li key={key.id}><div>{key.name}<br /><small>{key.prefix}… · {time(key.created_at)}</small></div><button disabled={busy} onClick={() => void action(async () => { await call(`/v1/account/api-keys/${encodeURIComponent(key.id)}`, undefined, "DELETE"); setKeys((prev) => prev.filter((k) => k.id !== key.id)); setCreated(""); })}>Revoke</button></li>)}</ul>
      </div>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
