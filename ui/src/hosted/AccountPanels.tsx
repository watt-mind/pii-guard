import { useState } from "react";
import { recovery, type Account, type Requester } from "./api";
import { getPlaygroundConnection, setPlaygroundConnection, time, useHostedSession, usePlaygroundConnection } from "./session";
import "./hosted.css";

export function Limits({ account }: { account: Account }) {
  const entries = Object.entries(account.limits).filter(([, value]) => value !== null && typeof value !== "boolean");
  return <details><summary>Current server limits</summary><ul className="list">{entries.map(([key, value]) => <li key={key}><span>{key.replaceAll("_", " ")}</span><span>{String(value)}</span></li>)}</ul></details>;
}

export function Settings({ call, account, refresh, onDisconnect }: { call: Requester; account: Account; refresh: () => Promise<void>; onDisconnect: (id: string) => void }) {
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

/** The console's account block (Overview): tier, today's usage, the reset time and the limits. */
export function AccountSummary() {
  const session = useHostedSession();
  if (!session) return null;
  const { account, error, refresh } = session;
  const perDay = account.limits.requests_per_day;
  return <section aria-labelledby="account-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 id="account-title" className="text-lg font-normal text-ink">Your account</h2><span className="text-xs text-muted">Signed in with Google · {account.tier} tier</span></div>
    <dl className="mt-4 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
      <div className="bg-surface p-3"><dt className="text-xs text-muted">Requests today</dt><dd className="mt-1 text-xl text-ink tabular-nums">{account.usage.requests_today}{typeof perDay === "number" && <span className="text-sm text-muted"> of {perDay}</span>}</dd></div>
      <div className="bg-surface p-3"><dt className="text-xs text-muted">Allowance resets</dt><dd className="mt-1 text-sm text-ink">{time(account.usage.resets_at)}</dd></div>
      <div className="bg-surface p-3"><dt className="text-xs text-muted">Provider connections</dt><dd className="mt-1 text-xl text-ink tabular-nums">{account.connections.length}</dd></div>
    </dl>
    <div className="hosted hosted-embed mt-3"><Limits account={account} /></div>
    {error && <div className="mt-3 flex flex-wrap items-center gap-3"><p role="alert" className="text-sm text-danger">{error}</p><button type="button" onClick={() => void refresh()} className="inline-flex min-h-11 items-center rounded-lg border border-line px-3 text-sm text-ink lg:min-h-9">Reconnect to API</button></div>}
    <div className="mt-4 flex flex-wrap gap-2">{[["#projects", "Create a project"], ["#connect", "Add a provider connection"], ["#playground/text", "Try the playground"]].map(([href, label]) => <a key={href} href={href} className="inline-flex min-h-11 items-center rounded-lg border border-line px-3.5 text-sm font-medium text-ink transition-colors hover:border-line-strong lg:min-h-9">{label}</a>)}</div>
    <p className="mt-3 text-xs text-muted">Sessions and provider connections are temporary. A guard restart loses ephemeral state. Every section shows only your own projects, activity and sessions.</p>
  </section>;
}

/** The console's provider connections (Connect), and which one the Playground's Chat uses. */
export function ProviderConnections() {
  const session = useHostedSession();
  const selected = usePlaygroundConnection();
  if (!session) return null;
  const { account, call, refresh } = session;
  const active = account.connections.some((c) => c.id === selected) ? selected : "";
  return <section aria-labelledby="connections-title" className="space-y-4">
    <div><h2 id="connections-title" className="text-lg font-normal text-ink">Provider connections</h2><p className="mt-1 text-sm text-muted">Connect your own model key for the Playground. Endpoint keys for your application are created per endpoint in <a className="underline underline-offset-4" href="#projects">Projects</a>, and shown once.</p></div>
    <div className="hosted hosted-embed stack max-w-3xl">
      <label>Playground chat sends through<select value={active} onChange={(e) => setPlaygroundConnection(e.target.value)}><option value="">Sponsored Meta (subject to allowance)</option>{account.connections.map((c) => <option key={c.id} value={c.id}>{c.provider} · {c.origin}</option>)}</select></label>
      <Settings call={call} account={account} refresh={refresh} onDisconnect={(id) => { if (getPlaygroundConnection() === id) setPlaygroundConnection(""); }} />
    </div>
  </section>;
}
