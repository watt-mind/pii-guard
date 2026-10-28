import type { ServerStatus } from "../api/status";
import type { SnippetsLoader } from "../api/connect";
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
  loadSnippets?: SnippetsLoader;
}

export function Connect({ status, traffic, onOpenLog, loadSnippets }: ConnectProps) {
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

      <ConnectQuickstart traffic={traffic} ner={server ? server.ner.available : null} onOpenLog={onOpenLog} load={loadSnippets} />

      <GatewayLine status={status} server={server} gateway={gateway} />
    </div>
  );
}

function GatewayLine({ status, server, gateway }: { status: ServerStatusState; server: ServerStatus | null; gateway: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
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
