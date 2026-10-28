import { useState, type ReactNode } from "react";
import type { ServerStatus } from "../api/status";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { readPref, writePref } from "../lib/storage";

/** The gateway's default address (`pii-guard up`, `pii-guard serve`), when the server can't be asked. */
const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787/v1";

type ClientId = "pi" | "muse-code" | "claude-code" | "openai" | "curl";

const CLIENTS: { id: ClientId; label: string; note: string }[] = [
  { id: "pi", label: "pi", note: "coding agent" },
  { id: "muse-code", label: "Muse Code", note: "Meta's coding agent" },
  { id: "claude-code", label: "Claude Code", note: "not supported yet" },
  { id: "openai", label: "OpenAI SDK", note: "any OpenAI-compatible client" },
  { id: "curl", label: "curl", note: "one request by hand" },
];

const isClient = (v: string | null): v is ClientId => CLIENTS.some((c) => c.id === v);

export interface ConnectProps {
  status: ServerStatusState;
}

export function Connect({ status }: ConnectProps) {
  const [client, setClientState] = useState<ClientId>(() => {
    const saved = readPref("connect-client");
    return isClient(saved) ? saved : "pi";
  });
  const setClient = (c: ClientId) => {
    setClientState(c);
    writePref("connect-client", c);
  };
  const server = status.state === "ok" ? status.status : null;
  const gateway = server?.gateway.url ?? DEFAULT_GATEWAY_URL;

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-medium text-balance text-ink">Connect</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          Point a client at the gateway instead of the model provider. It sends real data, the model gets placeholders, and the answer, tool-call arguments included, comes back
          restored.
        </p>
      </div>

      <GatewayLine status={status} server={server} gateway={gateway} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <fieldset className="min-w-0">
          <legend className="mb-2 text-xs font-medium text-muted">Your client</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:flex lg:flex-col">
            {CLIENTS.map((c) => (
              <label
                key={c.id}
                className={[
                  "relative flex min-w-0 cursor-pointer flex-col rounded-lg border px-3 py-2 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--focus)]",
                  client === c.id ? "border-ink bg-surface" : "border-line hover:border-line-strong",
                ].join(" ")}
              >
                <input type="radio" name="connect-client" value={c.id} checked={client === c.id} onChange={() => setClient(c.id)} className="sr-only" />
                <span className="font-medium text-ink">{c.label}</span>
                <span className="text-xs text-muted">{c.note}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <section aria-label={`Set up ${CLIENTS.find((c) => c.id === client)!.label}`} className="min-w-0 space-y-5 rounded-xl border border-line bg-surface p-4 sm:p-5">
          <ClientSteps client={client} gateway={gateway} server={server} />
        </section>
      </div>
    </div>
  );
}

function GatewayLine({ status, server, gateway }: { status: ServerStatusState; server: ServerStatus | null; gateway: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
      <span className="text-muted">Gateway base URL</span>
      <code className="min-w-0 font-mono text-sm break-all text-ink" data-testid="gateway-url">
        {gateway}
      </code>
      <CopyButton text={gateway} label="Copy the gateway URL" />
      <span className="w-full text-xs text-muted">
        {server ? (
          <>
            As this server reports it, version {server.version}. OpenAI-compatible: {mono("POST /chat/completions")}, {mono("POST /responses")}, {mono("GET /models")}.
            {server.upstream.mock ? " The upstream is the offline mock model: answers echo what it received." : ""}
          </>
        ) : status.state === "loading" ? (
          "Asking the server…"
        ) : (
          <>
            The default address: {status.state === "missing" ? "this server doesn't report its own" : "the pii-guard API isn't reachable"}. Start it with {mono("pii-guard up")}{" "}
            and the commands below use the URL it serves.
          </>
        )}
      </span>
    </div>
  );
}

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;

function ClientSteps({ client, gateway, server }: { client: ClientId; gateway: string; server: ServerStatus | null }) {
  const token = server?.auth.token_required ?? false;
  const runNote = (
    <p className="text-xs text-muted">
      Started pii-guard with {mono("uvx --from …")}? Put the same prefix in front of {mono("pii-guard")}: the {mono("pii-guard up")} banner prints it.
    </p>
  );
  const tokenNote = token ? (
    <p role="note" className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink">
      This server needs a token ({mono("PII_GUARD_API_TOKEN")}). Export it in the shell first: {mono("connect")} writes it as the client's key.
    </p>
  ) : null;

  if (client === "pi") {
    return (
      <>
        <Step n={1} title="Write pi's provider config">
          <Command text={`pii-guard connect pi --gateway ${gateway}`} />
          <p className="text-xs text-muted">
            Merges a {mono("pii-guard")} provider into pi's {mono("models.json")} (backup first, idempotent; {mono("--dry-run")} shows the diff). The base URL it writes carries a
            stable session ({mono("/s/<session>/v1")}), so the same value gets the same placeholder in every conversation.
          </p>
          {tokenNote}
          {runNote}
        </Step>
        <Step n={2} title="Check the whole path">
          <Command text={`pii-guard connect pi --gateway ${gateway} --check`} />
          <p className="text-xs text-muted">Sends one fictional canary the way pi would and prints what was sent, what the model saw and what came back. It shows up in Logs.</p>
        </Step>
        <Step n={3} title="Use pi as usual">
          <p className="text-sm text-ink">
            Pick a model from the {mono("pii-guard")} provider in pi. <DocLink href="https://github.com/watt-mind/pii-guard/blob/develop/docs/integrations/pi.md">docs/integrations/pi.md</DocLink>
          </p>
        </Step>
      </>
    );
  }
  if (client === "muse-code") {
    return (
      <>
        <Step n={1} title="Point Muse Code at the gateway">
          <Command text={`pii-guard connect muse-code --gateway ${gateway}`} />
          <p className="text-xs text-muted">
            Sets {mono("endpoint_transport.base_url")} in Muse's {mono("settings.json")} and keeps every other setting (backup first, {mono("--dry-run")} to preview). Muse then sends{" "}
            {mono("/v1/responses")} through pii-guard.
          </p>
          {tokenNote}
          {runNote}
        </Step>
        <Step n={2} title="Check the whole path">
          <Command text={`pii-guard connect muse-code --gateway ${gateway} --check`} />
          <p className="text-xs text-muted">Sends a fictional canary the way Muse does, with {mono("$META_API_KEY")}, and prints what the model saw and what came back.</p>
        </Step>
        <Step n={3} title="Read more">
          <p className="text-sm text-ink">
            <DocLink href="https://github.com/watt-mind/pii-guard/blob/develop/docs/integrations/muse-code.md">docs/integrations/muse-code.md</DocLink>
          </p>
        </Step>
      </>
    );
  }
  if (client === "claude-code") {
    return (
      <div role="note" className="space-y-3 text-sm">
        <p className="font-medium text-ink">Claude Code can't go through pii-guard yet.</p>
        <p className="text-ink">
          Claude Code speaks the Anthropic Messages API ({mono("POST /v1/messages")}). The gateway serves the OpenAI APIs ({mono("/chat/completions")} and{" "}
          {mono("/responses")}), so pointing {mono("ANTHROPIC_BASE_URL")} at it would fail every request rather than mask it.
        </p>
        <p className="text-muted">
          For a coding agent behind pii-guard today, use pi or Muse Code (both tested end to end). Any client that lets you set an OpenAI base URL works too: see OpenAI SDK.
        </p>
      </div>
    );
  }
  if (client === "openai") {
    const env = `export OPENAI_BASE_URL=${gateway}\nexport OPENAI_API_KEY=${token ? "$PII_GUARD_API_TOKEN" : "unused-the-gateway-holds-the-key"}`;
    return (
      <>
        <Step n={1} title="Set the base URL">
          <Command text={env} />
          <p className="text-xs text-muted">
            The OpenAI SDKs, LangChain, LiteLLM and Open WebUI read these. {token ? "The gateway checks the token" : "The gateway sends its own upstream key, so the client's key is not used"}.
          </p>
        </Step>
        <Step n={2} title="Pick the mode and language per request (optional)">
          <Command text={`X-PII-Guard-Mode: fast\nX-PII-Guard-Language: en`} />
          <p className="text-xs text-muted">
            As extra headers ({mono("extra_headers=…")} in Python). Fast is the default: rules and the on-device NER, nothing leaves the machine. Send{" "}
            {mono("X-PII-Guard-Session")} from the first answer to keep placeholders stable across turns.
          </p>
        </Step>
      </>
    );
  }
  const auth = token ? ` \\\n  -H "Authorization: Bearer $PII_GUARD_API_TOKEN"` : "";
  const model = server?.upstream.mock ? "pii-guard-mock" : "MODEL_ID";
  const body = JSON.stringify({ model, messages: [{ role: "user", content: "Write to Jane Placeholder at jane.placeholder@example.net" }] });
  return (
    <>
      {model === "MODEL_ID" && (
        <Step n={1} title="Find a model id">
          <Command text={`curl -s ${gateway}/models${token ? ` -H "Authorization: Bearer $PII_GUARD_API_TOKEN"` : ""}`} />
          <p className="text-xs text-muted">Listed from the upstream; put one in place of {mono("MODEL_ID")} below.</p>
        </Step>
      )}
      <Step n={model === "MODEL_ID" ? 2 : 1} title="Send one fictional request">
        <Command text={`curl -si ${gateway}/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "X-PII-Guard-Mode: fast" -H "X-PII-Guard-Language: en"${auth} \\\n  -d '${body}'`} />
        <p className="text-xs text-muted">
          {mono("-i")} shows the headers: {mono("X-PII-Guard-Masked")} counts the values masked, {mono("X-PII-Guard-Session")} and {mono("X-PII-Guard-Session-Source")} say
          which vault session was used. The call shows up in Logs.
        </p>
      </Step>
    </>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 gap-y-2">
      <span aria-hidden="true" className="grid size-7 place-items-center rounded-full border border-line font-mono text-xs text-muted">
        {n}
      </span>
      <div className="min-w-0 space-y-2">
        <h2 className="pt-1 text-sm font-medium text-ink">
          <span className="sr-only">Step {n}: </span>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

function Command({ text }: { text: string }) {
  return (
    <div className="flex min-w-0 items-start gap-2 rounded-lg border border-line bg-surface-2 p-2 pl-3">
      <pre className="min-w-0 flex-1 overflow-x-auto py-1 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-ink sm:whitespace-pre">{text}</pre>
      <CopyButton text={text} label="Copy" />
    </div>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copy = () => {
    const done = (r: "ok" | "failed") => {
      setCopied(r);
      setTimeout(() => setCopied(null), 1600);
    };
    if (!navigator.clipboard) return done("failed");
    navigator.clipboard.writeText(text).then(
      () => done("ok"),
      () => done("failed"),
    );
  };
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      className="inline-flex h-7 shrink-0 items-center rounded-md border border-line bg-surface px-2 text-xs font-medium text-ink transition-colors hover:border-line-strong"
    >
      <span aria-live="polite">{copied === "ok" ? "Copied" : copied === "failed" ? "Select and copy" : "Copy"}</span>
    </button>
  );
}

function DocLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="font-mono text-xs text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink">
      {children}
    </a>
  );
}
