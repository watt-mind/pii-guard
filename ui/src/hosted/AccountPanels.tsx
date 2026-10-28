import { useEffect, useId, useState } from "react";
import { Announcer, Button, ConfirmAction, Field, Input, KeyValues, Metric, Notice, Select } from "../components/ui";
import { SetupChecklist } from "./SetupChecklist";
import { recovery, type Account, type Connection, type Requester } from "./api";
import { getPlaygroundConnection, setPlaygroundConnection, time, useHostedSession, usePlaygroundConnection } from "./session";

const PROVIDER_LABEL: Record<string, string> = { meta: "Meta", openai: "OpenAI", fireworks: "Fireworks", openrouter: "OpenRouter", custom: "Custom HTTPS endpoint" };
const providerLabel = (provider: string) => PROVIDER_LABEL[provider] ?? provider;
const connectionLabel = (c: Pick<Connection, "provider" | "origin">) => `${providerLabel(c.provider)} · ${c.origin}`;

const LIMIT_LABEL: Record<string, string> = {
  requests_per_day: "Requests per day",
  requests_per_minute: "Requests per minute",
  tokens_per_day: "Tokens per day",
  max_input_chars: "Longest input (characters)",
  max_body_bytes: "Largest request (bytes)",
  max_connections: "Provider connections",
  concurrent_requests: "Requests at the same time",
  max_output_tokens: "Longest answer (tokens)",
  images_per_day: "Images per day",
  max_image_bytes: "Largest image (bytes)",
};
function limitLabel(key: string) {
  if (LIMIT_LABEL[key]) return LIMIT_LABEL[key];
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The server's limits for this account, behind a disclosure with a visible chevron. `hideZero` drops limits that are off (0), as on the public page. */
export function Limits({ account, hideZero = false }: { account: Account; hideZero?: boolean }) {
  const entries = Object.entries(account.limits).filter(([, value]) => value !== null && typeof value !== "boolean" && !(hideZero && value === 0));
  if (entries.length === 0) return null;
  return (
    <details className="group">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-sm text-sm text-ink pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden">
        <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-muted transition-transform group-open:rotate-90" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m6 4 4 4-4 4" />
        </svg>
        Current server limits
      </summary>
      <KeyValues
        className="mt-3"
        items={entries.map(([key, value]) => ({ key, label: limitLabel(key), value: <span className="tabular-nums">{typeof value === "number" ? value.toLocaleString() : String(value)}</span> }))}
      />
    </details>
  );
}

/** Connect a provider key and list the account's connections, with a confirmed Disconnect. */
export function Settings({ call, account, refresh, onDisconnect, onConnect }: { call: Requester; account: Account; refresh: () => Promise<void>; onDisconnect: (id: string) => void; onConnect?: (id: string) => void }) {
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState("");
  const [connected, setConnected] = useState("");
  const [announce, setAnnounce] = useState("");
  const [busy, setBusy] = useState(false);
  const listTitle = useId();
  const [focusList, setFocusList] = useState(0);
  // After a disconnect the row is gone: focus moves to the list's heading.
  useEffect(() => {
    if (focusList) document.getElementById(listTitle)?.focus();
  }, [focusList, listTitle]);
  async function action(run: () => Promise<void>) { setBusy(true); setError(""); try { await run(); } catch (e) { setError(recovery(e)); } finally { setBusy(false); } }
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-normal text-ink">Bring your own model key</h3>
          <p className="mt-0.5 text-sm text-muted">Connections are held in memory by the hosted guard. Disconnect to remove a key. Requests use your provider’s terms and billing.</p>
        </div>
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            setConnected("");
            void action(async () => {
              const secret = apiKey;
              setApiKey("");
              const created = await call<Partial<Connection> | undefined>("/v1/account/connections", { provider, api_key: secret, ...(provider === "custom" ? { base_url: baseUrl } : {}) });
              await refresh();
              if (created?.id) onConnect?.(created.id);
              const label = created?.origin ? connectionLabel({ provider, origin: created.origin }) : providerLabel(provider);
              setConnected(created?.id && onConnect ? `Connected ${label}. Playground chat now sends through it.` : `Connected ${label}.`);
              // The submit button is disabled again (empty key): move focus to the list it changed.
              setFocusList((n) => n + 1);
            });
          }}
        >
          <Field label="Provider" required>
            <Select disabled={busy} value={provider} onChange={(e) => setProvider(e.target.value)}>
              {["meta", "openai", "fireworks", "openrouter", "custom"].map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
            </Select>
          </Field>
          {provider === "custom" && (
            <Field label="Base URL" required hint="Public HTTPS only. Private and local network addresses are refused by the guard.">
              <Input type="url" placeholder="https://api.example.com/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} pattern="https://.*" />
            </Field>
          )}
          <Field label="Provider API key" required hint="Kept by the guard for the connection’s lifetime, never saved in browser storage.">
            <Input type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </Field>
          <div className="sm:col-span-2">
            <Button variant="primary" type="submit" busy={busy} disabled={!busy && !apiKey}>{busy ? "Working…" : "Connect provider"}</Button>
          </div>
        </form>
        {connected && <Notice tone="success" live>{connected}</Notice>}
        {error && <Notice tone="danger" live>{error}</Notice>}
      </div>
      <div className="space-y-3">
        <h3 id={listTitle} tabIndex={-1} className="text-lg font-normal text-ink focus:outline-none">Your connections</h3>
        <Announcer message={announce} />
        {account.connections.length === 0 ? (
          <p className="text-sm text-muted">No provider connections yet. Playground chat uses the sponsored model.</p>
        ) : (
          <ul className="divide-y divide-line" aria-labelledby={listTitle}>
            {account.connections.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <p className="text-sm text-ink break-words">{connectionLabel(c)}</p>
                  <p className="text-xs text-muted">Expires {time(c.expires_at)}</p>
                </div>
                <ConfirmAction
                  size="sm"
                  trigger="Disconnect"
                  triggerLabel={`Disconnect ${connectionLabel(c)}`}
                  title={`Disconnect ${connectionLabel(c)}?`}
                  body="Playground chat through it stops."
                  confirm="Disconnect"
                  busy={busy}
                  onConfirm={() => action(async () => {
                    await call(`/v1/account/connections/${encodeURIComponent(c.id)}`, undefined, "DELETE");
                    onDisconnect(c.id);
                    setConnected("");
                    await refresh();
                    setAnnounce(`Disconnected ${connectionLabel(c)}.`);
                    setFocusList((n) => n + 1);
                  })}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** The console's account block (Overview): tier, today's usage, the reset time and the limits. */
export function AccountSummary({ active = true, calls = 0 }: { active?: boolean; calls?: number }) {
  const session = useHostedSession();
  if (!session) return null;
  const { account, error, refresh } = session;
  const perDay = account.limits.requests_per_day;
  return (
    <section aria-labelledby="account-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="account-title" className="text-lg font-normal text-ink">Your account</h2>
        <span className="text-xs text-muted">Signed in with Google · {account.tier} tier</span>
      </div>
      <dl className="mt-4 grid gap-4 sm:grid-cols-3">
        <Metric label="Requests today" value={account.usage.requests_today} suffix={typeof perDay === "number" ? `of ${perDay}` : undefined} />
        <Metric label="Allowance resets" value={<span className="text-sm font-normal">{time(account.usage.resets_at)}</span>} />
        <Metric label="Provider connections" value={account.connections.length} />
      </dl>
      <div className="mt-4"><Limits account={account} /></div>
      {error && (
        <Notice tone="danger" live className="mt-3" action={<Button size="sm" onClick={() => void refresh()}>Reconnect to API</Button>}>
          {error}
        </Notice>
      )}
      <SetupChecklist call={session.call} account={account} active={active} calls={calls} />
      <p className="mt-3 text-xs text-muted">Sessions and provider connections are temporary. A guard restart loses ephemeral state. Every section shows only your own projects, activity and sessions.</p>
    </section>
  );
}

/** The console's provider connections (Connect), and which one the Playground's Chat uses. */
export function ProviderConnections() {
  const session = useHostedSession();
  const selected = usePlaygroundConnection();
  if (!session) return null;
  const { account, call, refresh } = session;
  const active = account.connections.some((c) => c.id === selected) ? selected : "";
  return (
    <section aria-labelledby="connections-title" className="space-y-4">
      <div>
        <h2 id="connections-title" className="text-lg font-normal text-ink">Model provider keys for the Playground</h2>
        <p className="mt-0.5 text-sm text-muted">Connect your own model key for Playground chat. Your application doesn&apos;t use these: it uses an endpoint key from <a className="underline underline-offset-4" href="#projects">Projects</a>, as above.</p>
      </div>
      <div className="space-y-6 rounded-xl border border-line bg-surface p-4 sm:p-5">
        <Field label="Playground chat sends through" className="sm:max-w-md">
          <Select value={active} onChange={(e) => setPlaygroundConnection(e.target.value)}>
            <option value="">Sponsored Meta (subject to allowance)</option>
            {account.connections.map((c) => <option key={c.id} value={c.id}>{connectionLabel(c)}</option>)}
          </Select>
        </Field>
        <Settings call={call} account={account} refresh={refresh} onConnect={setPlaygroundConnection} onDisconnect={(id) => { if (getPlaygroundConnection() === id) setPlaygroundConnection(""); }} />
      </div>
    </section>
  );
}
