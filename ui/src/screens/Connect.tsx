import type { ReactNode } from "react";
import type { ServerStatus } from "../api/status";
import type { SnippetsLoader } from "../api/connect";
import { Notice, PageHeader } from "../components/ui";
import type { Requester } from "../hosted/api";
import type { ServerStatusState } from "../hooks/useServerStatus";
import type { CliHandoffParams } from "../lib/routes";
import { CliAuthCard } from "./CliAuthCard";
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
  /** Account settings, such as a hosted owner's provider connections (shown after the client setup). */
  accounts?: ReactNode;
  /** Hosted: the owner's endpoint picker, which renders the client blocks for the picked endpoint. */
  clientSetup?: (quickstart: (load: SnippetsLoader) => ReactNode) => ReactNode;
  /** A `#connect/<client>` deep link names this client tab first (LAB-1314). */
  initialClient?: string | null;
  /** CLI browser-handoff parameters when opened via `#cli-auth` (LAB-1708). */
  cliHandoff?: CliHandoffParams | null;
  /** Project API requester for CLI authorization (LAB-1708). */
  call?: Requester;
}

export function Connect({ status, traffic, onOpenLog, onOpenSession, loadSnippets, serverSnippets = true, gatewayLine = true, accounts, clientSetup, initialClient = null, cliHandoff = null, call }: ConnectProps) {
  const server = status.state === "ok" ? status.status : null;
  const gateway = server?.gateway.url ?? DEFAULT_GATEWAY_URL;

  return (
    <div className="space-y-6">
      {/* Hosted, the client setup below has its own lead: one, not two saying the same (LAB-1626). */}
      <PageHeader
        title="Connect"
        lead={clientSetup ? undefined : "Point a client at the gateway instead of the model provider. It sends real data, the model gets placeholders, and the answer, tool-call arguments included, comes back restored."}
      />

      {cliHandoff && <CliAuthCard cliHandoff={cliHandoff} call={call} />}

      {clientSetup ? (
        <>
          {clientSetup((load) => (
            <ConnectQuickstart traffic={traffic} ner={server ? server.ner.available : null} onOpenLog={onOpenLog} onOpenSession={onOpenSession} load={load} initialTool={initialClient} />
          ))}
          {/* The Playground's own provider keys: optional, folded so the first run asks for one key only (LAB-1455). */}
          {accounts && (
            <details className="group rounded-xl border border-line bg-surface">
              <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium text-ink sm:px-5 [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="mr-2 inline-block text-muted transition-transform group-open:rotate-90">
                  ›
                </span>
                Optional: provider keys for the Playground
              </summary>
              <div className="border-t border-line p-4 sm:p-5">{accounts}</div>
            </details>
          )}
        </>
      ) : (
        accounts
      )}

      {clientSetup ? null : serverSnippets ? (
        <>
          <ConnectQuickstart traffic={traffic} ner={server ? server.ner.available : null} onOpenLog={onOpenLog} onOpenSession={onOpenSession} load={loadSnippets} initialTool={initialClient} />

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
            The default address: {status.state === "missing" ? "this server doesn't report its own" : "the PII Guard API isn't reachable"}. Start it with {mono("pii-guard up")}{" "}
            and the blocks above use the URL it serves.
          </>
        )}
      </span>
    </div>
  );
}

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;
