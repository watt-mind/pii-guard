import { lazy, Suspense, useCallback, useEffect, useId, useRef, useState } from "react";
import { TEXT_ENTITY_TYPES, type TextEntityType } from "../api/types";
import { ENTITY_META, type Policy } from "../lib/entities";
import { ApiError } from "../api/http";
import { Announcer, Button, Card, Checkbox, ConfirmAction, Field, Input, Notice, PageHeader, SecretReveal, Select } from "../components/ui";
import { localRequest } from "./request";
import { request, recovery, type Requester } from "../hosted/api";
import { useHostedSession } from "../hosted/session";
import { setSelectedEndpoint } from "./selection";
import { projectPath, type Endpoint, type EndpointKey, type PolicyVersion, type Project, type ProjectList } from "./api";

const OwnerAccess = import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? null : lazy(() => import("./OwnerAccess"));

const configurationRecovery = import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? (error: unknown) => recovery(error) : (error: unknown, hosted: boolean) => {
  if (hosted) return recovery(error);
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) return "The guard refused owner access. Open Local guard access and enter the owner API token configured on this server, then retry. Check that you are using the guard’s current address.";
    if (error.status === 400 || error.status === 422) return "The guard refused these settings. Check the form and try again.";
    if (error.status === 404) return "This project or endpoint is unavailable. Reload the project list and check that the guard supports project configuration.";
    if (error.status === 503 && error.code === "project_storage_unavailable") return "The guard is up, but its project storage is not configured or not reachable. Check the server's project storage settings, then retry.";
  }
  return "The guard could not complete this request. Check its connection and retry.";
};

/** The confirmation of a project just created, across the console's remount on the new scope. */
let carried: string | null = null;

interface Props { call?: Requester; hosted?: boolean; projectId?: string; onProject?: (project: Project) => void }
const defaults = Object.fromEntries(TEXT_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy])) as Record<TextEntityType, Policy>;

/* ---------- Words for codes ---------- */

const PROVIDER_LABEL: Record<string, string> = {
  meta: "Meta",
  openai: "OpenAI",
  fireworks: "Fireworks",
  openrouter: "OpenRouter",
  custom: "Custom HTTPS endpoint",
  sponsored: "Sponsored Meta (subject to allowance)",
};
const providerLabel = (provider: string) => PROVIDER_LABEL[provider] ?? provider;
const LANGUAGE_LABEL: Record<string, string> = { hu: "Hungarian", en: "English", de: "German" };
const describePolicy = (policy: { language: string; mode: string }) => `${LANGUAGE_LABEL[policy.language] ?? policy.language} · ${policy.mode} mode`;
const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

const ENDPOINTS_TITLE = "pw-endpoints-title";
const POLICIES_TITLE = "pw-policies-title";
const byId = (id: string) => () => document.getElementById(id);

/** Move focus after the next render, once the target exists (a heading, a trigger). */
function useFocusLater() {
  const target = useRef<(() => HTMLElement | null | undefined) | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const find = target.current;
    target.current = null;
    find?.()?.focus();
  }, [tick]);
  return useCallback((find: () => HTMLElement | null | undefined) => {
    target.current = find;
    setTick((n) => n + 1);
  }, []);
}

const LIST = "divide-y divide-line";
const ROW = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0";
const REVIEW = "rounded-lg bg-surface-2 p-3 text-sm text-ink sm:p-4";

/** Project configuration only. Secrets live in component memory, never browser storage. */
export function Workspace({ call: suppliedCall, hosted = false, projectId, onProject }: Props) {
  const call = suppliedCall ?? (hosted ? request : localRequest);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState(projectId ?? "");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  // A new project becomes the console's scope, which remounts the console: its confirmation and
  // the focus move are carried across that remount.
  const [created, setCreated] = useState(() => carried ?? "");
  const [refocus] = useState(() => carried !== null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const focusLater = useFocusLater();
  const projectSelect = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    let active = true;
    call<ProjectList>("/v1/projects").then((data) => {
      if (!Array.isArray(data.projects)) throw new Error("Invalid projects");
      if (!active) return;
      setProjects(data.projects);
      const project = data.projects.find((p) => p.id === projectId) ?? data.projects.find((p) => p.id === data.default_project_id) ?? data.projects[0];
      if (project) { setSelected(project.id); if (project.id !== projectId) onProject?.(project); }
      setError("");
    }).catch((e: unknown) => { if (active) setError(configurationRecovery(e, hosted)); });
    return () => { active = false; };
  }, [call, projectId, onProject, retry, hosted]);
  const project = projects.find((p) => p.id === selected);
  // Read once, at mount (above); cleared when this instance goes, so it never reaches a later mount.
  useEffect(() => () => {
    carried = null;
  }, []);
  useEffect(() => {
    if (refocus && projects.length) projectSelect.current?.focus();
  }, [refocus, projects.length]);
  return (
    <div className="space-y-6">
      <PageHeader title="Projects" lead="Keep each application’s endpoints, endpoint keys and policies together. Every endpoint pins one upstream, one model and one policy version." />
      {!hosted && OwnerAccess && <Suspense fallback={null}><OwnerAccess /></Suspense>}
      {error && (
        <Notice tone="danger" live action={<Button size="sm" onClick={() => setRetry((n) => n + 1)}>Retry projects</Button>}>
          {error}
        </Notice>
      )}
      {projects.length > 0 && (
        <Card title="Project" subtitle="Endpoints, keys and policies below belong to the current project.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Current project">
              <Select ref={projectSelect} value={selected} disabled={busy} onChange={(e) => { const next = projects.find((p) => p.id === e.target.value)!; setSelected(next.id); setCreated(""); onProject?.(next); }}>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const wanted = name.trim();
                if (!wanted) return;
                setBusy(true); setError(""); setCreated("");
                void call<Project>("/v1/projects", { name }).then((next) => {
                  const message = `Project '${next.name || wanted}' created.`;
                  carried = message;
                  setProjects((prev) => [...prev, next]); setSelected(next.id); setName(""); setCreated(message);
                  // The submit button is disabled again (empty name): focus moves to the new project.
                  focusLater(() => projectSelect.current);
                  onProject?.(next);
                }).catch((e: unknown) => setError(configurationRecovery(e, hosted))).finally(() => setBusy(false));
              }}
            >
              <Field label="New project name" required className="min-w-40 flex-1">
                <Input maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Button type="submit" busy={busy} disabled={!busy && !name.trim()}>{busy ? "Creating…" : "Create project"}</Button>
            </form>
          </div>
          {created && <Notice tone="success" live className="mt-4">{created}</Notice>}
        </Card>
      )}
      {!projects.length && !error && <p role="status" className="text-sm text-muted">Loading your default project…</p>}
      {project && <ProjectConfiguration key={project.id} project={project} call={call} hosted={hosted} />}
    </div>
  );
}

type Notified = { area: "endpoints" | "policies"; text: string; endpointId?: string } | null;
interface EndpointBody { name: string; provider: string; model: string; policy_version_id: string; enabled: boolean; base_url?: string; api_key?: string }
interface PolicyBody { name: string; entity_policies: Record<TextEntityType, Policy>; language: string; mode: string }

function ProjectConfiguration({ project, call, hosted }: { project: Project; call: Requester; hosted: boolean }) {
  const [policies, setPolicies] = useState<PolicyVersion[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<Notified>(null);
  const [busy, setBusy] = useState(false);
  const [endpointEdit, setEndpointEdit] = useState<Endpoint | "new" | null>(null);
  const [policyEdit, setPolicyEdit] = useState<PolicyVersion | "new" | null>(null);
  const [inspect, setInspect] = useState("");
  const focusLater = useFocusLater();
  const createEndpointRef = useRef<HTMLButtonElement>(null);
  const createPolicyRef = useRef<HTMLButtonElement>(null);
  const editRefs = useRef(new Map<string, HTMLButtonElement>());
  const versionRefs = useRef(new Map<string, HTMLButtonElement>());
  const noPolicyHint = useId();
  const base = projectPath(project.id);
  async function reload() {
    const [policyData, endpointData] = await Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]);
    if (!Array.isArray(policyData.policies) || !Array.isArray(endpointData.endpoints)) throw new Error("Invalid configuration");
    setPolicies(policyData.policies); setEndpoints(endpointData.endpoints); setLoaded(true);
    window.dispatchEvent(new Event("pii-guard-project-configuration"));
  }
  useEffect(() => { let active = true; void Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]).then(([p, e]) => { if (!Array.isArray(p.policies) || !Array.isArray(e.endpoints)) throw new Error("Invalid configuration"); if (active) { setPolicies(p.policies); setEndpoints(e.endpoints); setLoaded(true); } }).catch((e: unknown) => { if (active) setError(configurationRecovery(e, hosted)); }); return () => { active = false; }; }, [base, call, hosted]);
  async function action(work: () => Promise<void>) { setBusy(true); setError(""); setNotice(null); try { await work(); } catch (e) { setError(configurationRecovery(e, hosted)); } finally { setBusy(false); } }

  const openEndpointForm = (next: Endpoint | "new") => { setEndpointEdit(next); setPolicyEdit(null); setInspect(""); setNotice(null); };
  const openPolicyForm = (next: PolicyVersion | "new") => { setPolicyEdit(next); setEndpointEdit(null); setNotice(null); };
  const closeEndpointForm = () => {
    const was = endpointEdit;
    setEndpointEdit(null);
    focusLater(() => (was === "new" || !was ? createEndpointRef.current : editRefs.current.get(was.id)));
  };
  const closePolicyForm = () => {
    const was = policyEdit;
    setPolicyEdit(null);
    focusLater(() => (was === "new" || !was ? createPolicyRef.current : versionRefs.current.get(was.policy_version_id)));
  };
  const inspected = endpoints.find((e) => e.id === inspect);

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">Configuration is saved by the guard. Restoration mappings and activity remain temporary. Create a policy first: every endpoint pins one policy version.</p>
      {error && (
        <Notice tone="danger" live action={<Button size="sm" busy={busy} onClick={() => void action(reload)}>Reload configuration</Button>}>
          {error}
        </Notice>
      )}
      {!loaded && !error && <p role="status" className="text-sm text-muted">Loading endpoints and policies…</p>}

      <Card
        title="Reusable policies"
        titleId={POLICIES_TITLE}
        subtitle="Each saved version is immutable. Endpoints keep their assigned version until you explicitly reassign them."
        actions={<Button ref={createPolicyRef} busy={busy} disabled={!loaded || policyEdit === "new"} onClick={() => openPolicyForm("new")}>Create policy</Button>}
      >
        {notice?.area === "policies" && <Notice tone="success" live className="mb-4">{notice.text}</Notice>}
        {loaded && !policies.length && <p className="text-sm text-muted">No policies yet. Create one to choose what each endpoint masks, keeps or blocks.</p>}
        {policies.length > 0 && (
          <ul className={LIST}>
            {policies.map((policy) => (
              <li key={policy.policy_version_id} className={ROW}>
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-ink break-words">{policy.name} · v{policy.version}</h3>
                  <p className="mt-0.5 text-sm text-muted">{describePolicy(policy)} · {plural(endpoints.filter((e) => e.enabled && e.policy_version_id === policy.policy_version_id).length, "endpoint")}</p>
                </div>
                <Button
                  size="sm"
                  busy={busy}
                  aria-label={`New version of ${policy.name} v${policy.version}`}
                  ref={(el) => { if (el) versionRefs.current.set(policy.policy_version_id, el); else versionRefs.current.delete(policy.policy_version_id); }}
                  onClick={() => openPolicyForm(policy)}
                >
                  New version
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {policyEdit && (
        <PolicyForm
          template={policies.find((p) => p.policy_id === project.default_policy_id) ?? policies[0]}
          key={`policy-form-${policyEdit === "new" ? "new" : policyEdit.policy_version_id}`}
          policy={policyEdit === "new" ? undefined : policyEdit}
          endpoints={endpoints}
          hosted={hosted}
          busy={busy}
          onCancel={closePolicyForm}
          onSave={(body) => action(async () => {
            await call(policyEdit === "new" ? `${base}/policies` : `${base}/policies/${encodeURIComponent(policyEdit.policy_id)}`, body, policyEdit === "new" ? "POST" : "PUT");
            await reload();
            setPolicyEdit(null);
            setNotice({ area: "policies", text: `Policy '${body.name}' saved.` });
            focusLater(byId(POLICIES_TITLE));
          })}
        />
      )}

      <Card
        title="Gateway endpoints"
        titleId={ENDPOINTS_TITLE}
        subtitle="One upstream, model and pinned policy version per endpoint."
        actions={
          <Button ref={createEndpointRef} busy={busy} disabled={!loaded || !policies.length || endpointEdit === "new"} aria-describedby={loaded && !policies.length ? noPolicyHint : undefined} onClick={() => openEndpointForm("new")}>
            Create endpoint
          </Button>
        }
      >
        {loaded && !policies.length && <p id={noPolicyHint} className="mb-3 text-xs text-muted">Create a policy first: every endpoint pins one policy version.</p>}
        {notice?.area === "endpoints" && (
          <Notice
            tone="success"
            live
            className="mb-4"
            action={notice.endpointId && endpoints.some((e) => e.id === notice.endpointId) ? <Button size="sm" variant="primary" onClick={() => { setInspect(notice.endpointId!); setNotice(null); }}>Create an endpoint key</Button> : undefined}
          >
            {notice.text}
          </Notice>
        )}
        {loaded && !endpoints.length && <p className="text-sm text-muted">No endpoints yet. Create one, then create an endpoint key to connect your application.</p>}
        {endpoints.length > 0 && (
          <ul className={LIST}>
            {endpoints.map((endpoint) => (
              <li key={endpoint.id} className={ROW}>
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-ink break-words">
                    {endpoint.name}
                    {!endpoint.enabled && <span className="ml-1.5 font-normal text-muted">· Disabled</span>}
                  </h3>
                  <p className="mt-0.5 text-sm text-muted break-words">{providerLabel(endpoint.provider)} · <span className="font-mono text-xs">{endpoint.model}</span></p>
                  <p className="text-sm text-muted">{policies.find((p) => p.policy_version_id === endpoint.policy_version_id)?.name ?? "Policy"} · v{endpoint.policy_version}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" aria-expanded={inspect === endpoint.id} aria-label={`Connect & keys for ${endpoint.name}`} onClick={() => { setInspect(inspect === endpoint.id ? "" : endpoint.id); setEndpointEdit(null); }}>
                    Connect & keys
                  </Button>
                  <Button
                    size="sm"
                    busy={busy}
                    aria-label={`Edit ${endpoint.name}`}
                    ref={(el) => { if (el) editRefs.current.set(endpoint.id, el); else editRefs.current.delete(endpoint.id); }}
                    onClick={() => openEndpointForm(endpoint)}
                  >
                    Edit
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {endpointEdit && (
        <EndpointForm
          key={`endpoint-form-${typeof endpointEdit === "string" ? "new" : endpointEdit.id}`}
          endpoint={endpointEdit === "new" ? undefined : endpointEdit}
          policies={policies}
          busy={busy}
          hosted={hosted}
          onCancel={closeEndpointForm}
          onSave={(body) => action(async () => {
            const creating = endpointEdit === "new";
            const saved = await call<Partial<Endpoint> | undefined>(creating ? `${base}/endpoints` : `${base}/endpoints/${encodeURIComponent(endpointEdit.id)}`, body, creating ? "POST" : "PUT");
            await reload();
            setEndpointEdit(null);
            setNotice(
              creating
                ? { area: "endpoints", text: `Endpoint '${body.name}' created. Next, create an endpoint key so your application can use it.`, endpointId: saved?.id }
                : { area: "endpoints", text: `Endpoint '${body.name}' saved.` },
            );
            focusLater(byId(ENDPOINTS_TITLE));
          })}
          onDisable={endpointEdit === "new" ? undefined : () => action(async () => {
            await call(`${base}/endpoints/${encodeURIComponent(endpointEdit.id)}`, { name: endpointEdit.name, provider: endpointEdit.provider, model: endpointEdit.model, policy_version_id: endpointEdit.policy_version_id, enabled: false, ...(endpointEdit.provider === "custom" ? { base_url: endpointEdit.base_url } : {}) }, "PUT");
            await reload();
            setEndpointEdit(null); setInspect("");
            setNotice({ area: "endpoints", text: `Endpoint '${endpointEdit.name}' disabled. Its endpoint keys are revoked.` });
            focusLater(byId(ENDPOINTS_TITLE));
          })}
        />
      )}
      {inspected && <EndpointConnection key={`endpoint-connection-${inspect}`} endpoint={inspected} base={base} call={call} hosted={hosted} />}
    </div>
  );
}

/** Focus a form's heading when it opens, so keyboard users land where the form appeared. */
function useFocusOnOpen(id: string) {
  useEffect(() => {
    const heading = document.getElementById(id);
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView?.({ block: "nearest" });
  }, [id]);
}

function EndpointForm({ endpoint, policies, busy, hosted, onSave, onCancel, onDisable }: { endpoint?: Endpoint; policies: PolicyVersion[]; busy: boolean; hosted: boolean; onSave: (body: EndpointBody) => Promise<void>; onCancel: () => void; onDisable?: () => Promise<void> }) {
  const [name, setName] = useState(endpoint?.name ?? "");
  const session = useHostedSession();
  const sponsored = hosted && session?.account.limits.sponsored_enabled !== false;
  // Hosted: Sponsored Meta needs no key, so it comes first and is the default for a new endpoint.
  const [provider, setProvider] = useState(endpoint?.provider ?? (sponsored ? "sponsored" : "openai"));
  const connected = session?.account.connections.filter((c) => c.provider === provider) ?? [];
  const [model, setModel] = useState(endpoint?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(endpoint?.base_url ?? "");
  const [secret, setSecret] = useState("");
  // One policy version: nothing to choose, so it is preselected.
  const [policyId, setPolicyId] = useState(endpoint?.policy_version_id ?? (policies.length === 1 ? policies[0]!.policy_version_id : ""));
  const [reviewed, setReviewed] = useState(false);
  const [reenable, setReenable] = useState(false);
  const titleId = useId();
  useFocusOnOpen(titleId);
  const changed = Boolean(endpoint && endpoint.policy_version_id !== policyId);
  const selected = policies.find((p) => p.policy_version_id === policyId);
  const requiresCredential = provider !== "sponsored" && (!endpoint?.credential_configured || endpoint.provider !== provider);
  const keyLabel = requiresCredential ? "Provider API key" : "Replace provider API key (optional)";
  const blockedReason = !policyId ? "Choose a policy version to save." : changed && !reviewed ? "Confirm the policy change below to save." : "";
  return (
    <Card
      title={endpoint ? `Edit ${endpoint.name}` : "Create endpoint"}
      titleId={titleId}
      subtitle={endpoint ? "Changes apply to future requests through this endpoint." : "Clients reach the model through this endpoint with an endpoint key."}
    >
      <form
        aria-labelledby={titleId}
        className="space-y-4"
        onSubmit={(e) => { e.preventDefault(); const apiKey = secret; setSecret(""); void onSave({ name, provider, model, policy_version_id: policyId, enabled: endpoint ? endpoint.enabled || reenable : true, ...(provider === "custom" ? { base_url: baseUrl } : {}), ...(apiKey ? { api_key: apiKey } : {}) }); }}
      >
        <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <Field label="Endpoint name" required hint="Shown in logs and in the project switcher.">
            <Input maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Provider" required>
            <Select value={provider} onChange={(e) => { setProvider(e.target.value); setSecret(""); }}>
              {[...(hosted ? ["sponsored"] : []), "meta", "openai", "fireworks", "openrouter", "custom"].map((value) => <option key={value} value={value}>{providerLabel(value)}</option>)}
            </Select>
          </Field>
          {provider === "custom" && (
            <Field label="Upstream base URL" required hint="Use a public HTTPS endpoint for hosted deployments.">
              <Input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
            </Field>
          )}
          <Field label="Model ID" required hint="The provider’s exact model ID.">
            <Input maxLength={200} value={model} onChange={(e) => setModel(e.target.value)} placeholder="example-model-v1" />
          </Field>
          {provider !== "sponsored" && (
            <Field label={keyLabel} required={requiresCredential} hint={
                endpoint?.credential_configured
                  ? "A credential is configured. Its value cannot be retrieved."
                  : connected.length
                    ? `An endpoint keeps its own key: your ${providerLabel(provider)} connection on Connect is for the Playground only, so enter the key here too. Never saved in browser storage.`
                    : "The credential is sent to the guard and never saved in browser storage."
              }>
              <Input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </Field>
          )}
          <Field label="Policy version" required hint={policies.length === 1 && !endpoint ? "The project’s only policy version is selected." : "The endpoint keeps this version until you reassign it."}>
            <Select value={policyId} onChange={(e) => { setPolicyId(e.target.value); setReviewed(false); }}>
              <option value="" disabled>Choose a policy version</option>
              {policies.map((policy) => <option key={policy.policy_version_id} value={policy.policy_version_id}>{policy.name} · v{policy.version}</option>)}
            </Select>
          </Field>
        </fieldset>
        {selected && <p className="text-sm text-muted">{describePolicy(selected)}. {plural(Object.values(selected.entity_policies).filter((p) => p === "keep").length, "entity type")} kept in place. Fail-closed processing is always enforced.</p>}
        {endpoint && !endpoint.enabled && (
          <div className={REVIEW}>
            <p>This endpoint is disabled. Its revoked endpoint keys stay revoked.</p>
            <Checkbox className="mt-3" checked={reenable} disabled={busy} onChange={(e) => setReenable(e.target.checked)} label="Re-enable this endpoint; create a new endpoint key afterward" />
          </div>
        )}
        {changed && (
          <div className={REVIEW}>
            <p>Applying this version changes future requests through <strong className="font-medium">{endpoint!.name}</strong>. Other endpoints keep their versions. Already admitted requests finish with their original policy.</p>
            <Checkbox className="mt-3" checked={reviewed} disabled={busy} onChange={(e) => setReviewed(e.target.checked)} label={`Apply ${selected?.name} v${selected?.version} to this endpoint`} />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" type="submit" busy={busy} disabled={!busy && Boolean(blockedReason)}>{busy ? "Saving…" : endpoint ? "Save endpoint" : "Create endpoint"}</Button>
          <Button variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button>
          {onDisable && endpoint?.enabled && (
            <ConfirmAction
              trigger="Disable endpoint…"
              triggerVariant="danger"
              title={`Disable endpoint '${endpoint.name}'?`}
              body="All its endpoint keys are revoked and future requests through it are refused."
              confirm="Disable and revoke keys"
              busy={busy}
              onConfirm={onDisable}
            />
          )}
          {blockedReason && !busy && <p className="w-full text-xs text-muted">{blockedReason}</p>}
        </div>
      </form>
    </Card>
  );
}

function PolicyForm({ policy, template, endpoints, hosted, busy, onSave, onCancel }: { policy?: PolicyVersion; template?: PolicyVersion; endpoints: Endpoint[]; hosted: boolean; busy: boolean; onSave: (body: PolicyBody) => Promise<void>; onCancel: () => void }) {
  const [name, setName] = useState(policy?.name ?? "");
  const [entities, setEntities] = useState({ ...(policy?.entity_policies ?? template?.entity_policies ?? defaults) });
  const [language, setLanguage] = useState(policy?.language ?? template?.language ?? "hu");
  const [mode, setMode] = useState(hosted ? "fast" : policy?.mode ?? template?.mode ?? "fast");
  const titleId = useId();
  useFocusOnOpen(titleId);
  const affected = endpoints.filter((e) => e.enabled && e.policy_id === policy?.policy_id);
  return (
    <Card title={policy ? `New version of ${policy.name}` : "Create policy"} titleId={titleId} subtitle="Mask replaces detected values with reversible placeholders. Keep sends them unchanged. Block refuses the entire request when that type is detected.">
      <form aria-labelledby={titleId} className="space-y-4" onSubmit={(e) => { e.preventDefault(); void onSave({ name, entity_policies: entities, language, mode }); }}>
        <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Policy name" required>
            <Input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Language">
            <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="hu">Hungarian</option>
              <option value="en">English</option>
              <option value="de">German</option>
            </Select>
          </Field>
          {!hosted && (
            <Field label="Detection mode" hint="Audit mode needs a server with the audit detectors.">
              <Select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="fast">Fast</option>
                <option value="audit">Audit</option>
              </Select>
            </Field>
          )}
        </fieldset>
        <fieldset disabled={busy} className="min-w-0">
          <legend className="mb-3 text-sm font-medium text-ink">What happens to each type</legend>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {TEXT_ENTITY_TYPES.map((type) => (
              <Field key={type} label={ENTITY_META[type].label}>
                <Select value={entities[type]} onChange={(e) => setEntities((prev) => ({ ...prev, [type]: e.target.value as Policy }))}>
                  <option value="mask">Mask</option>
                  <option value="keep">Keep</option>
                  <option value="block">Block request</option>
                </Select>
              </Field>
            ))}
          </div>
        </fieldset>
        <div className={REVIEW}>
          <p>{policy ? "Saving creates a new version. No endpoint changes automatically." : "The new policy is available to endpoints in this project."}</p>
          {policy && (
            <>
              <p className="mt-1">Endpoints using this policy family: {affected.length ? affected.map((e) => `${e.name} (v${e.policy_version})`).join(", ") : "none"}.</p>
              <p className="mt-1">To apply the saved version, edit an endpoint and review its policy assignment.</p>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" type="submit" busy={busy}>{busy ? "Saving…" : policy ? "Save new version" : "Save policy"}</Button>
          <Button variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function EndpointConnection({ endpoint, base, call, hosted }: { endpoint: Endpoint; base: string; call: Requester; hosted: boolean }) {
  const panel = useRef<HTMLElement>(null);
  // This component mounts only after an explicit Connect & keys expansion.
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "start", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, []);
  const [keys, setKeys] = useState<EndpointKey[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [secret, setSecret] = useState<{ id: string; name: string; key: string } | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [announce, setAnnounce] = useState("");
  const keysTitle = useId();
  const disabledHint = useId();
  const keyHint = useId();
  const focusLater = useFocusLater();
  const keyPath = `${base}/endpoints/${encodeURIComponent(endpoint.id)}/keys`;
  useEffect(() => { let active = true; call<{ keys: EndpointKey[] }>(keyPath).then((data) => { if (!Array.isArray(data.keys)) throw new Error("Invalid keys"); if (active) { setKeys(data.keys); setLoaded(true); } }).catch((e: unknown) => { if (active) setError(configurationRecovery(e, hosted)); }); return () => { active = false; }; }, [call, keyPath, hosted]);
  async function action(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (e) { setError(configurationRecovery(e, hosted)); } finally { setBusy(false); } }
  const url = `${globalThis.location.origin}${endpoint.base_path}`;
  const snippet = `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(url)},\n    api_key=os.environ["PII_GUARD_ENDPOINT_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(endpoint.model)},\n    messages=[{"role": "user", "content": "Hello, Robin Example."}],\n)`;
  function copy(value: string, label: string) { void navigator.clipboard.writeText(value).then(() => setCopied(`${label} copied`)).catch(() => setCopied("Copy failed. Select the text and copy it manually.")); }
  const revoke = (key: EndpointKey) => action(async () => {
    await call(`${keyPath}/${encodeURIComponent(key.id)}`, undefined, "DELETE");
    const at = new Date().toISOString();
    setKeys((prev) => prev.map((k) => (k.id === key.id ? { ...k, revoked_at: at } : k)));
    if (secret?.id === key.id) setSecret(null);
    setAnnounce(`Key '${key.name}' revoked.`);
    focusLater(byId(keysTitle));
  });
  return (
    <Card ref={panel} tabIndex={-1} aria-label={`Connect ${endpoint.name}`} title={`Connect ${endpoint.name}`} subtitle="Endpoint keys authorize only this endpoint. Provider credentials are managed by the guard." className="focus:outline-none">
      <div className="space-y-4">
        <Field label="OpenAI-compatible base URL">
          <Input readOnly value={url} className="font-mono" />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => copy(url, "URL")}>Copy URL</Button>
          <Button size="sm" onClick={() => copy(snippet, "Snippet")}>Copy Python snippet</Button>
          {hosted && (
            <a
              href="#connect"
              className="text-sm text-ink underline underline-offset-4"
              onClick={(e) => {
                // Open Connect first, then pick this endpoint (the console remounts on the new scope).
                e.preventDefault();
                globalThis.location.hash = "#connect";
                setSelectedEndpoint(endpoint.id);
              }}
            >
              Client setup for this endpoint
            </a>
          )}
          <p role="status" className="text-xs text-muted">{copied}</p>
        </div>
        <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-ui whitespace-pre text-ink sm:p-4">{snippet}</pre>
      </div>

      <div className="mt-6 space-y-4 border-t border-line pt-5">
        <h3 id={keysTitle} tabIndex={-1} className="text-lg font-normal text-ink focus:outline-none">Endpoint keys</h3>
        {error && <Notice tone="danger" live>{error}</Notice>}
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim() || !endpoint.enabled) return;
            setSecret(null);
            void action(async () => {
              const created = await call<EndpointKey & { key: string }>(keyPath, { name });
              setSecret({ id: created.id, name: created.name, key: created.key });
              setKeys((prev) => [...prev, { id: created.id, name: created.name, created_at: created.created_at }]);
              setName("");
            });
          }}
        >
          <Field label="Endpoint key name" required className="min-w-40 flex-1">
            <Input maxLength={64} value={name} disabled={!endpoint.enabled} onChange={(e) => setName(e.target.value)} aria-describedby={endpoint.enabled ? keyHint : disabledHint} />
          </Field>
          <Button variant="primary" type="submit" busy={busy} disabled={!busy && (!name.trim() || !endpoint.enabled)} aria-describedby={endpoint.enabled ? undefined : disabledHint}>
            {busy ? "Working…" : "Create endpoint key"}
          </Button>
          {endpoint.enabled ? (
            <p id={keyHint} className="w-full text-xs text-muted">Name it after the app that uses it.</p>
          ) : (
            <p id={disabledHint} className="w-full text-xs text-muted">This endpoint is disabled. Re-enable it to create endpoint keys.</p>
          )}
        </form>
        {secret && <SecretReveal label={`endpoint key '${secret.name}'`} secret={secret.key} envName="PII_GUARD_ENDPOINT_KEY" onDismiss={() => setSecret(null)} />}
        <Announcer message={announce} />
        {loaded && !keys.length && <p className="text-sm text-muted">No endpoint keys yet. Create one to connect an application to this endpoint.</p>}
        {keys.length > 0 && (
          <ul className={LIST} aria-labelledby={keysTitle}>
            {keys.map((key) => (
              <li key={key.id} className={ROW}>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink break-words">{key.name}</p>
                  <p className="mt-0.5 text-sm text-muted">
                    <span className={key.revoked_at ? "text-danger" : "text-guard"}>{key.revoked_at ? "Revoked" : "Active"}</span> · created {new Date(key.created_at).toLocaleString()}
                  </p>
                </div>
                {!key.revoked_at && (
                  <ConfirmAction
                    size="sm"
                    trigger="Revoke"
                    triggerLabel={`Revoke key ${key.name}`}
                    title={`Revoke key '${key.name}'?`}
                    body="Apps using it stop working."
                    confirm="Revoke key"
                    busy={busy}
                    onConfirm={() => revoke(key)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
