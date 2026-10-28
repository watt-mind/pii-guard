import type { ReactNode } from "react";
import { isFullStatus, type FullServerStatus } from "../api/status";
import { TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, type EntityType } from "../api/types";
import { NerHint } from "../components/NerHint";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { ENTITY_META, metaFor, type Policy as EntityPolicy } from "../lib/entities";
import { detectorName } from "../lib/traffic";

export interface PolicyProps {
  status: ServerStatusState;
}

const POLICY_TEXT: Record<EntityPolicy, string> = {
  mask: "Masked",
  keep: "Kept in place",
  block: "Blocks the request",
};

const POLICY_CLASS: Record<EntityPolicy, string> = {
  mask: "bg-masked-soft text-masked ring-masked/35",
  keep: "bg-surface-2 text-muted ring-kept/50",
  block: "bg-blocked-soft text-blocked ring-blocked/40",
};

const mono = (s: string) => <code className="font-mono text-xs">{s}</code>;

export function Policy({ status }: PolicyProps) {
  const server = status.state === "ok" && isFullStatus(status.status) ? status.status : null;
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-medium text-balance text-ink">Policy</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          What this server does with each kind of personal data, read from its configuration. Read-only: the settings live in the server's environment, so a change here could not
          survive a restart.
        </p>
      </div>

      {!server && (
        <p role="status" className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-muted">
          {status.state === "loading"
            ? "Asking the server…"
            : status.state === "missing"
              ? "This pii-guard server doesn't report its configuration (it predates /v1/status). The entity table shows the documented defaults."
              : "The pii-guard API isn't reachable, so its configuration is unknown. The entity table shows the documented defaults (docs/entities.md)."}
        </p>
      )}

      {server && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Detection">
            <Rows>
              <Row label="Default mode">
                <span className="font-medium capitalize">{server.gateway.default_mode}</span>
                <span className="text-muted"> · per request with {mono("X-PII-Guard-Mode")}</span>
              </Row>
              <Row label="Fast mode">{server.gateway.modes.fast.detectors.map(detectorName).join(" + ") || "none"}</Row>
              <Row label="Audit mode">
                {server.gateway.modes.audit.available ? (
                  <>Fast + the LLM detector{server.gateway.modes.audit.model ? `, ${server.gateway.modes.audit.model.split("/").pop()}` : ""}</>
                ) : (
                  <span className="text-muted [overflow-wrap:anywhere]">Unavailable: {server.gateway.modes.audit.reason}</span>
                )}
              </Row>
              <Row label="REST API">{server.rest.detectors.map(detectorName).join(" + ") || "none"}</Row>
              <Row label="Default language">{mono(server.default_language)}</Row>
            </Rows>
            {!server.ner.available && (
              <p role="note" className="mt-3 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-ink">
                <span className="font-medium text-warn">No NER: free-text names are not masked.</span> They need <NerHint />.
              </p>
            )}
          </Card>
          <Card title="Server">
            <Rows>
              <Row label="Images">
                {server.images.available ? (
                  <>On · faces {server.images.sam ? "by SAM 3.1 and the on-device detector" : "by the on-device detector"}, text by OCR</>
                ) : (
                  <span className="text-muted">Refused (fail closed): {imageGaps(server)}</span>
                )}
              </Row>
              <Row label="Traffic log">
                {mono(server.traffic_log)}
                <span className="text-muted">
                  {server.traffic_log === "masked" ? " · placeholders only" : server.traffic_log === "full" ? " · originals too, loopback only" : " · Logs and Overview stay empty"}
                </span>
              </Row>
              <Row label="Authentication">{server.auth.token_required ? "Bearer token required" : "None: keep it on localhost or behind a proxy"}</Row>
              <Row label="Upstream">{server.upstream.mock ? "Offline mock model (echo)" : server.upstream.origin ? mono(server.upstream.origin) : "Not configured"}</Row>
            </Rows>
          </Card>
        </div>
      )}

      <section aria-labelledby="policies-title" className="rounded-xl border border-line bg-surface p-4 sm:p-5">
        <h2 id="policies-title" className="text-lg font-normal text-ink">
          Entity policies
        </h2>
        <p className="mt-0.5 text-sm text-muted">
          {server ? "As this server applies them, in the gateway and the REST API." : "The documented defaults."} Changed with {mono("PII_GUARD_POLICY_OVERRIDES")}, for example{" "}
          {mono("ORGANIZATION=mask,EMAIL=block")}.
        </p>
        <div className="mt-4 grid gap-x-8 gap-y-6 md:grid-cols-2">
          <PolicyTable title="Text" types={TEXT_ENTITY_TYPES} server={server} />
          <PolicyTable title="Image regions" types={VISUAL_ENTITY_TYPES} server={server} />
        </div>
        <p className="mt-4 text-xs text-muted">
          <span className="font-medium text-ink">Allow-list:</span> none. pii-guard has no per-value allow-list; a detected value stays in place only when its type's policy is keep.
          Values the application already knows are sensitive can be pre-loaded per session ({mono("POST /v1/sessions")}).
        </p>
      </section>
    </div>
  );
}

function imageGaps(server: FullServerStatus): string {
  const needs: Record<string, string> = { ocr: "no OCR (the ocr extra)", tesseract: "no Tesseract", segmenter: "no face detector (the local-vision extra, or SAM 3.1 with META_API_KEY)" };
  return server.images.gaps.map((g) => needs[g] ?? g).join(", ");
}

function PolicyTable({ title, types, server }: { title: string; types: readonly EntityType[]; server: FullServerStatus | null }) {
  return (
    <table className="w-full self-start text-sm">
      <caption className="mb-1 text-left text-xs font-medium text-muted">{title}</caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">Type</th>
          <th scope="col">Policy</th>
        </tr>
      </thead>
      <tbody>
        {types.map((t) => {
          const policy = (server?.policies[t] ?? ENTITY_META[t]?.policy ?? "mask") as EntityPolicy;
          const changed = server && ENTITY_META[t] && ENTITY_META[t].policy !== policy;
          return (
            <tr key={t} className="border-b border-line last:border-0">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal">
                <span className="text-ink">{metaFor(t).label}</span> <span className="font-mono text-2xs text-faint">{t}</span>
              </th>
              <td className="py-1.5 text-right">
                <span className={["inline-block rounded-md px-1.5 py-px text-xs font-medium ring-1 ring-inset", POLICY_CLASS[policy]].join(" ")}>{POLICY_TEXT[policy]}</span>
                {changed && <span className="ml-1.5 text-2xs text-muted">changed</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="min-w-0 rounded-xl border border-line bg-surface p-4 sm:p-5">
      <h2 className="mb-3 text-lg font-normal text-ink">{title}</h2>
      {children}
    </section>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">{children}</dl>;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </>
  );
}
