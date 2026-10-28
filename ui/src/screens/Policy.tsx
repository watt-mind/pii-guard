import { useEffect, useState } from "react";
import { isFullStatus, type FullServerStatus } from "../api/status";
import { recovery, request, type Requester } from "../hosted/api";
import { projectPath, type PolicyVersion, type Project, type ProjectList } from "../projects/api";
import { TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, type EntityType } from "../api/types";
import { NerHint } from "../components/NerHint";
import { Button, ButtonLink, Card, KeyValues, Notice, PageHeader } from "../components/ui";
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
      <PageHeader
        title="Policy"
        lead="What this server does with each kind of personal data, read from its configuration. Read-only: the settings live in the server's environment, so a change here could not survive a restart."
      />

      {!server && (
        <Notice live>
          {status.state === "loading"
            ? "Asking the server…"
            : status.state === "missing"
              ? "This pii-guard server doesn't report its configuration (it predates /v1/status). The entity table shows the documented defaults."
              : "The pii-guard API isn't reachable, so its configuration is unknown. The entity table shows the documented defaults (docs/entities.md)."}
        </Notice>
      )}

      {server && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Detection" titleId="policy-detection-title" className="min-w-0">
            <KeyValues
              items={[
                {
                  label: "Default mode",
                  value: (
                    <>
                      <span className="font-medium capitalize">{server.gateway.default_mode}</span>
                      <span className="text-muted"> · a client can pick another mode per request (header {mono("X-PII-Guard-Mode")})</span>
                    </>
                  ),
                },
                { label: "Fast mode", value: server.gateway.modes.fast.detectors.map(detectorName).join(" + ") || "none" },
                {
                  label: "Audit mode",
                  value: server.gateway.modes.audit.available ? (
                    <>Fast + the LLM detector{server.gateway.modes.audit.model ? `, ${server.gateway.modes.audit.model.split("/").pop()}` : ""}</>
                  ) : (
                    <span className="text-muted [overflow-wrap:anywhere]">Unavailable: {server.gateway.modes.audit.reason}</span>
                  ),
                },
                { label: "REST API", value: server.rest.detectors.map(detectorName).join(" + ") || "none" },
                { label: "Default language", value: mono(server.default_language) },
              ]}
            />
            {!server.ner.available && (
              <p role="note" className="mt-3 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-ink">
                <span className="font-medium text-warn">No NER: free-text names are not masked.</span> They need <NerHint />.
              </p>
            )}
          </Card>
          <Card title="Server" titleId="policy-server-title" className="min-w-0">
            <KeyValues
              items={[
                {
                  label: "Images",
                  value: server.images.available ? (
                    <>On · faces {server.images.sam ? "by SAM 3.1 and the on-device detector" : "by the on-device detector"}, text by OCR</>
                  ) : (
                    <span className="text-muted">Refused (fail closed): {imageGaps(server)}</span>
                  ),
                },
                {
                  label: "Traffic log",
                  value: (
                    <>
                      {server.traffic_log === "masked"
                        ? "Placeholders only"
                        : server.traffic_log === "full"
                          ? "Originals too, on this machine only"
                          : "Off: Logs and Overview stay empty"}{" "}
                      <span className="text-muted">(level {mono(server.traffic_log)})</span>
                    </>
                  ),
                },
                { label: "Authentication", value: server.auth.token_required ? "Bearer token required" : "None: keep it on localhost or behind a proxy" },
                { label: "Upstream", value: server.upstream.mock ? "Offline mock model (echo)" : server.upstream.origin ? mono(server.upstream.origin) : "Not configured" },
              ]}
            />
          </Card>
        </div>
      )}

      <Card
        title="Entity policies"
        titleId="policies-title"
        subtitle={
          <>
            {server ? "As this server applies them, in the gateway and the REST API." : "The documented defaults."} Change them in the server's policy overrides, for example{" "}
            {mono("PII_GUARD_POLICY_OVERRIDES=ORGANIZATION=mask,EMAIL=block")}.
          </>
        }
      >
        <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
          <PolicyTable title="Text" types={TEXT_ENTITY_TYPES} policies={server?.policies ?? null} />
          <PolicyTable title="Image regions" types={VISUAL_ENTITY_TYPES} policies={server?.policies ?? null} />
        </div>
        <p className="mt-4 text-xs text-muted">
          <span className="font-medium text-ink">Allow-list:</span> none. pii-guard has no per-value allow-list; a detected value stays in place only when its type's policy is keep.
          Values the application already knows are sensitive can be pre-loaded per session ({mono("POST /v1/sessions")}).
        </p>
      </Card>
    </div>
  );
}

export interface OwnerPolicyProps {
  /** The owner's project API (the hosted session's requester); defaults to the cookie requester. */
  call?: Requester;
  /** The project the console is scoped to; else the owner's default project. */
  projectId?: string;
}

type OwnerState =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ok"; project: Project; policy: PolicyVersion | null };

/** The default policy's latest version: what new endpoints in the project start from. */
function defaultPolicyOf(project: Project, policies: PolicyVersion[]): PolicyVersion | null {
  const family = policies.filter((p) => p.policy_id === project.default_policy_id);
  return family.reduce<PolicyVersion | null>((best, p) => (best === null || p.version > best.version ? p : best), null);
}

/**
 * Policy where the server has no policy of its own to show (a hosted owner): the owner's
 * project default policy, read-only, from the owner-scoped project API. Editing stays under
 * Projects, where policies are versioned and pinned per endpoint.
 */
export function OwnerPolicy({ call = request, projectId }: OwnerPolicyProps) {
  const [state, setState] = useState<OwnerState>({ state: "loading" });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    (async () => {
      const list = await call<ProjectList>("/v1/projects");
      if (!Array.isArray(list.projects)) throw new Error("Invalid projects");
      const project = list.projects.find((p) => p.id === projectId) ?? list.projects.find((p) => p.id === list.default_project_id) ?? list.projects[0];
      if (!project) throw new Error("No project");
      const data = await call<{ policies: PolicyVersion[] }>(`${projectPath(project.id)}/policies`);
      if (!Array.isArray(data.policies)) throw new Error("Invalid policies");
      return { project, policy: defaultPolicyOf(project, data.policies) };
    })().then(
      (ok) => active && setState({ state: "ok", ...ok }),
      (e: unknown) => active && setState({ state: "error", message: recovery(e) }),
    );
    return () => {
      active = false;
    };
  }, [call, projectId, retry]);

  const policy = state.state === "ok" ? state.policy : null;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Policy"
        lead="What happens to each kind of personal data in your project. Policies belong to projects and are versioned: each endpoint applies the version it is pinned to. Read-only here; create policies and new versions under Projects."
      />

      {state.state === "loading" && <Notice live>Loading your project's policy…</Notice>}
      {state.state === "error" && (
        <Notice
          tone="danger"
          live
          action={
            <Button
              size="sm"
              onClick={() => {
                setState({ state: "loading" });
                setRetry((n) => n + 1);
              }}
            >
              Retry
            </Button>
          }
        >
          {state.message}
        </Notice>
      )}
      {state.state === "ok" && !policy && <Notice live>The project {state.project.name} has no default policy yet. Create one under Projects.</Notice>}

      {state.state === "ok" && policy && (
        <>
          <Card title="Default policy" titleId="owner-policy-title" className="min-w-0">
            <KeyValues
              items={[
                { label: "Project", value: state.project.name },
                {
                  label: "Policy",
                  value: (
                    <>
                      {policy.name} <span className="text-muted">· v{policy.version}</span>
                    </>
                  ),
                },
                { label: "Detection mode", value: <span className="capitalize">{policy.mode}</span> },
                { label: "Language", value: mono(policy.language) },
              ]}
            />
          </Card>
          <Card title="Entity policies" titleId="policies-title" subtitle={`As ${policy.name} v${policy.version} applies them. An endpoint pinned to another policy or version applies that one.`}>
            <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
              <PolicyTable title="Text" types={TEXT_ENTITY_TYPES} policies={policy.entity_policies} />
            </div>
          </Card>
        </>
      )}

      <div>
        <ButtonLink variant="primary" href="#projects">
          Edit policies in Projects
        </ButtonLink>
      </div>
    </div>
  );
}

function imageGaps(server: FullServerStatus): string {
  const needs: Record<string, string> = { ocr: "no OCR (the ocr extra)", tesseract: "no Tesseract", segmenter: "no face detector (the local-vision extra, or SAM 3.1 with a Meta API key)" };
  return server.images.gaps.map((g) => needs[g] ?? g).join(", ");
}

/** Each type's policy; `policies` null shows the documented defaults, otherwise changes are marked. */
function PolicyTable({ title, types, policies }: { title: string; types: readonly EntityType[]; policies: Partial<Record<EntityType, EntityPolicy>> | null }) {
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
          const policy = (policies?.[t] ?? ENTITY_META[t]?.policy ?? "mask") as EntityPolicy;
          const changed = policies && ENTITY_META[t] && ENTITY_META[t].policy !== policy;
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
