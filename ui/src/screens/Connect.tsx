import type { ReactNode } from "react";
import type { ServerStatus } from "../api/status";
import type { SnippetsLoader } from "../api/connect";
import { Notice, PageHeader } from "../components/ui";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { ConnectQuickstart, CopyButton, type QuickstartTraffic } from "./ConnectQuickstart";

/** The gateway's default address (`pii-guard up`, `pii-guard serve`), when the server can't be asked. */
const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787/v1";

export interface ConnectProps {
  status: ServerStatusState;
  /** The live traffic the console follows: step 3 watches it for the tool's first request. */
  traffic?: QuickstartTraffic;
  /** Open one call on the Logs screen. */
  onOpenLog?: (id: string) => void;
  /** Open the tool's vault session on the Vault screen (by its traffic-log ref). */
  onOpenSession?: (ref: string) => void;
  loadSnippets?: SnippetsLoader;
  /** Show the server's client snippets and gateway URL; off where the server can't report them yet. */
  serverSnippets?: boolean;
  /** The server's gateway URL line; off where each endpoint has its own URL (hosted). */
  gatewayLine?: boolean;
  /** Account settings shown first, such as a hosted owner's provider connections. */
  accounts?: ReactNode;
}

export function Connect({ status, traffic, onOpenLog, onOpenSession, loadSnippets, serverSnippets = true, gatewayLine = true, accounts }: ConnectProps) {
  const server = status.state === "ok" ? status.status : null;
  const gateway = server?.gateway.url ?? DEFAULT_GATEWAY_URL;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Connect"
        lead="Point a client at the gateway instead of the model provider. It sends real data, the model gets placeholders, and the answer, tool-call arguments included, comes back restored."
      />

      {accounts}

      {serverSnippets ? (
        <>
          <ConnectQuickstart traffic={traffic} ner={server ? server.ner.available : null} onOpenLog={onOpenLog} onOpenSession={onOpenSession} load={loadSnippets} />

          {gatewayLine && <GatewayLine status={status} server={server} gateway={gateway} />}
        </>
      ) : (
        <Notice>
          Each endpoint has its own base URL, client snippets and keys. Pick one under <span className="text-ink">Inspect activity &amp; vault</span> in the project menu at the top for its
          snippets here, or open{" "}
          <a className="text-ink underline underline-offset-4" href="#projects">
            Projects
          </a>{" "}
          and choose Connect &amp; keys on an endpoint.
        </Notice>
      )}
    </div>
  );
}

function GatewayLine({ status, server, gateway }: { status: ServerStatusState; server: ServerStatus | null; gateway: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface p-4 text-sm sm:p-5">
      <span className="text-muted">Any other client: gateway base URL</span>
      {status.state === "loading" ? (
        <span className="text-sm text-muted">…</span>
      ) : (
        <>
          <code className="min-w-0 font-mono text-sm break-all text-ink" data-testid="gateway-url">
            {gateway}
          </code>
          <CopyButton text={gateway} label="Copy the gateway URL" />
        </>
      )}
      <span className="w-full text-xs text-muted">
        {server ? (
          <>
            As this server reports it, version {server.version}. OpenAI-compatible: {mono("POST /chat/completions")}, {mono("POST /responses")}, {mono("GET /models")}. Add{" "}
            {mono("/s/<session>")} before {mono("/v1")} to keep placeholders stable across conversations.
          </>
        ) : status.state === "loading" ? (
          "Asking the server…"
        ) : (
          <>
            The default address: {status.state === "missing" ? "this server doesn't report its own" : "the pii-guard API isn't reachable"}. Start it with {mono("pii-guard up")}{" "}
            and the blocks above use the URL it serves.
          </>
        )}
      </span>
    </div>
  );
}

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;
