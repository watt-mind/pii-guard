import { lazy, Suspense, useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, type TextEntityType, type VisualEntityType } from "../api/types";
import { ENTITY_META, type Policy } from "../lib/entities";
import { ApiError } from "../api/http";
import { Announcer, Badge, Button, Card, Checkbox, ConfirmAction, Field, Input, Notice, PageHeader, SecretReveal, Select } from "../components/ui";
import { localRequest } from "./request";
import { request, recovery, type Requester } from "../hosted/api";
import { useHostedSession } from "../hosted/session";
import { dateTime, relativeTime } from "../lib/time";
import { setSelectedEndpoint } from "./selection";
import { exampleModel, projectPath, pendingPolicyEdit, requestPolicyEdit, type Endpoint, type EndpointKey, type EndpointModels, type EndpointModelsQuery, type PolicyVersion, type Project, type ProjectList, type VisualDetection, VISUAL_DETECTION_LABEL } from "./api";

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
const visualDefaults = Object.fromEntries(VISUAL_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy === "keep" ? "keep" : "mask"])) as Record<VisualEntityType, "mask" | "keep">;

/* ---------- Words for codes ---------- */

const PROVIDER_LABEL: Record<string, string> = {
  meta: "Meta",
  openai: "OpenAI",
  fireworks: "Fireworks",
  openrouter: "OpenRouter",
  custom: "Custom HTTPS endpoint",
  sponsored: "Meta Muse Spark (no key needed)",
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

/** The newest version number of each policy family (`policy_id`). */
function latestVersions(policies: PolicyVersion[]): Map<string, number> {
  const latest = new Map<string, number>();
  for (const p of policies) latest.set(p.policy_id, Math.max(latest.get(p.policy_id) ?? 0, p.version));
  return latest;
}

/** One row per policy family (LAB-1626): its latest version first, older versions behind it. */
function policyFamilies(policies: PolicyVersion[]): { latest: PolicyVersion; older: PolicyVersion[] }[] {
  const families = new Map<string, PolicyVersion[]>();
  for (const p of policies) families.set(p.policy_id, [...(families.get(p.policy_id) ?? []), p]);
  return [...families.values()].map((versions) => {
    const sorted = [...versions].sort((a, b) => b.version - a.version);
    return { latest: sorted[0]!, older: sorted.slice(1) };
  });
}

/** Escape closes an inline form like Cancel (a confirmation inside it handles its own Escape first). */
const escapeTo = (onCancel: () => void, busy: boolean) => (e: { key: string; defaultPrevented: boolean; preventDefault: () => void }) => {
  if (e.key !== "Escape" || e.defaultPrevented || busy) return;
  e.preventDefault();
  onCancel();
};

/** A panel opened from a row (edit, new version, keys) renders inside that row, below it (LAB-1619). */
const INLINE = "w-full basis-full pt-1";

const LIST = "divide-y divide-line";
const ROW = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0";
const REVIEW = "rounded-lg bg-surface-2 p-3 text-sm text-ink sm:p-4";

/** Project configuration only. Secrets live in component memory, never browser storage. */
export function Workspace({ call: suppliedCall, hosted = false, projectId, onProject }: Props) {
  const call = suppliedCall ?? (hosted ? request : localRequest);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loaded, setLoaded] = useState(false);
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
      setLoaded(true);
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
      <PageHeader title="Projects" lead="Keep each application’s endpoints, endpoint keys and policies together. Every endpoint pins one upstream and one policy version, and can pin one model." />
      {!hosted && OwnerAccess && <Suspense fallback={null}><OwnerAccess /></Suspense>}
      {error && (
        <Notice tone="danger" live action={<Button size="sm" onClick={() => setRetry((n) => n + 1)}>Retry projects</Button>}>
          {error}
        </Notice>
      )}
      {loaded && (
        <Card title="Project" subtitle="Endpoints, keys and policies below belong to the current project.">
          <div className="grid gap-4 sm:grid-cols-2">
            {projects.length > 0 && <Field label="Current project">
              <Select ref={projectSelect} value={selected} disabled={busy} onChange={(e) => { const next = projects.find((p) => p.id === e.target.value)!; setSelected(next.id); setCreated(""); onProject?.(next); }}>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            </Field>}
            {!projects.length && <p className="text-sm text-muted">No projects yet. Create a project to configure policies and endpoints.</p>}
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
              <Field label="New project name" className="min-w-40 flex-1">
                <Input maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Button type="submit" busy={busy} disabled={!busy && !name.trim()}>{busy ? "Creating…" : "Create project"}</Button>
            </form>
          </div>
          {created && <Notice tone="success" live className="mt-4">{created}</Notice>}
        </Card>
      )}
      {/* A tall placeholder, so the cards that replace it don't push anything on screen (CLS, LAB-1619). */}
      {!loaded && !error && <p role="status" className="min-h-dvh text-sm text-muted">Loading your default project…</p>}
      {project && <ProjectConfiguration key={project.id} project={project} call={call} hosted={hosted} />}
    </div>
  );
}

type Notified = { area: "endpoints" | "policies"; text: string; endpointId?: string } | null;
interface EndpointBody { name: string; provider: string; model: string | null; policy_version_id: string; enabled: boolean; base_url?: string; api_key?: string }
interface PolicyBody { name: string; entity_policies: Record<TextEntityType, Policy> & Record<VisualEntityType, "mask" | "keep">; language: string; mode: string; visual_detection: VisualDetection }

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
  const catalog = useCallback((query: EndpointModelsQuery) => call<EndpointModels>(`${base}/endpoints/models`, query, "POST"), [call, base]);
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
  const latest = latestVersions(policies);
  // Opened from Connect's "Tune what is masked": a new version of that policy, its form focused.
  const [wantedEdit] = useState(pendingPolicyEdit);
  const [openedWanted, setOpenedWanted] = useState(false);
  if (wantedEdit && loaded && !openedWanted) {
    setOpenedWanted(true);
    requestPolicyEdit(null);
    const family = policyFamilies(policies).find((f) => f.latest.policy_id === wantedEdit);
    if (family) { setPolicyEdit(family.latest); setEndpointEdit(null); }
  }
  const policyForm = policyEdit && (
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
  );
  const endpointForm = endpointEdit && (
    <EndpointForm
      key={`endpoint-form-${typeof endpointEdit === "string" ? "new" : endpointEdit.id}`}
      endpoint={endpointEdit === "new" ? undefined : endpointEdit}
      policies={policies}
      busy={busy}
      hosted={hosted}
      catalog={catalog}
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
  );

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">Configuration is saved {hosted ? "on the PII Guard server" : "by the guard"}. Restoration mappings and activity remain temporary.{loaded && !policies.length ? " Create a policy first: every endpoint pins one policy version." : ""}</p>
      {error && (
        <Notice tone="danger" live action={<Button size="sm" busy={busy} onClick={() => void action(reload)}>Reload configuration</Button>}>
          {error}
        </Notice>
      )}
      {/* The cards wait for the data: rendered empty, they'd jump up from below a tall placeholder (CLS, LAB-1619). */}
      {!loaded && !error ? <p role="status" className="min-h-dvh text-sm text-muted">Loading endpoints and policies…</p> : <>

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
            {policyFamilies(policies).map(({ latest: policy, older }) => {
              const pinned = (version: PolicyVersion) => endpoints.filter((e) => e.enabled && e.policy_version_id === version.policy_version_id).length;
              const family = endpoints.filter((e) => e.enabled && e.policy_id === policy.policy_id).length;
              return (
              <li key={policy.policy_id} className={ROW}>
                <div className="min-w-0">
                  <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-ink break-words">
                    {policy.name} · v{policy.version}
                    {older.length > 0 && <Badge tone="live">Latest</Badge>}
                  </h3>
                  <p className="mt-0.5 text-sm text-muted">
                    {describePolicy(policy)} · {plural(family, "endpoint")}
                    {older.length > 0 && <> · {plural(older.length + 1, "version")}</>}
                  </p>
                </div>
                <Button
                  size="sm"
                  busy={busy}
                  aria-label={`New version of ${policy.name}`}
                  ref={(el) => { if (el) versionRefs.current.set(policy.policy_version_id, el); else versionRefs.current.delete(policy.policy_version_id); }}
                  onClick={() => openPolicyForm(policy)}
                >
                  New version
                </Button>
                {policyEdit !== "new" && policyEdit?.policy_id === policy.policy_id && <div className={INLINE}>{policyForm}</div>}
                {older.length > 0 && (
                  <details className="w-full basis-full text-sm">
                    <summary className="cursor-pointer text-muted hover:text-ink">Older versions ({older.length})</summary>
                    <ul className="mt-2 space-y-1 border-l border-line pl-3">
                      {older.map((v) => (
                        <li key={v.policy_version_id} className="text-muted">
                          <span className="text-ink">v{v.version}</span> · {describePolicy(v)} · {plural(pinned(v), "endpoint")}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
              );
            })}
          </ul>
        )}
      </Card>

      {policyEdit === "new" && policyForm}

      <Card
        title="Gateway endpoints"
        titleId={ENDPOINTS_TITLE}
        subtitle="One upstream and pinned policy version per endpoint, with a pinned model or the client’s own."
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
            {[...endpoints.filter((e) => e.enabled), ...endpoints.filter((e) => !e.enabled)].map((endpoint) => (
              <li key={endpoint.id} className={ROW}>
                <div className="min-w-0">
                  <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-ink break-words">
                    {endpoint.name}
                    {!endpoint.enabled && <Badge>Disabled</Badge>}
                  </h3>
                  <p className="mt-0.5 text-sm text-muted break-words">{providerLabel(endpoint.provider)} · {endpoint.model ? <span className="font-mono text-xs">{endpoint.model}</span> : "Client chooses the model"}</p>
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
                    {policies.find((p) => p.policy_version_id === endpoint.policy_version_id)?.name ?? "Policy"} · v{endpoint.policy_version}
                    {(latest.get(endpoint.policy_id) ?? 0) > endpoint.policy_version && <Badge>v{latest.get(endpoint.policy_id)} available</Badge>}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {endpoint.enabled && (
                    <Button size="sm" aria-expanded={inspect === endpoint.id} aria-label={`Connect & keys for ${endpoint.name}`} onClick={() => { setInspect(inspect === endpoint.id ? "" : endpoint.id); setEndpointEdit(null); }}>
                      Connect & keys
                    </Button>
                  )}
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
                {endpointEdit !== "new" && endpointEdit?.id === endpoint.id && <div className={INLINE}>{endpointForm}</div>}
                {inspected?.id === endpoint.id && (
                  <div className={INLINE}>
                    <EndpointConnection key={`endpoint-connection-${inspect}`} endpoint={inspected} base={base} call={call} hosted={hosted} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {endpointEdit === "new" && endpointForm}
      </>}
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

/** The model select's "type another id" choice; never a provider model id (it has a space). */
const OTHER_MODEL = "other model";

function EndpointForm({ endpoint, policies, busy, hosted, catalog, onSave, onCancel, onDisable }: { endpoint?: Endpoint; policies: PolicyVersion[]; busy: boolean; hosted: boolean; catalog: (query: EndpointModelsQuery) => Promise<EndpointModels>; onSave: (body: EndpointBody) => Promise<void>; onCancel: () => void; onDisable?: () => Promise<void> }) {
  const [name, setName] = useState(endpoint?.name ?? "");
  const session = useHostedSession();
  const sponsored = hosted && session?.account.limits.sponsored_enabled !== false;
  // Hosted: Sponsored Meta needs no key, so it comes first and is the default for a new endpoint.
  const [provider, setProvider] = useState(endpoint?.provider ?? (sponsored ? "sponsored" : "openai"));
  const connected = session?.account.connections.filter((c) => c.provider === provider) ?? [];
  const [model, setModel] = useState(endpoint?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(endpoint?.base_url ?? "");
  const [secret, setSecret] = useState("");
  // Model choices: the provider's catalog (asked on request) or the sponsored allow-list.
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsState, setModelsState] = useState<"idle" | "loading" | "failed" | "rejected">("idle");
  const [typing, setTyping] = useState(false);
  const isSponsored = provider === "sponsored";
  const storedKey = Boolean(endpoint?.credential_configured && endpoint.provider === provider && (provider !== "custom" || endpoint.base_url === baseUrl));
  const canLoadModels = !isSponsored && (Boolean(secret) || storedKey) && (provider !== "custom" || Boolean(baseUrl));
  const loadBlocked = provider === "custom" && !baseUrl ? "Enter the base URL and provider API key to load models." : "Enter the provider API key to load models.";
  const loadLabel = provider === "custom" ? "Load models from this endpoint" : `Load models from ${providerLabel(provider)}`;
  const listing = Boolean(models && models.length && !typing);
  async function loadModels() {
    setModelsState("loading");
    try {
      const query: EndpointModelsQuery = { provider, ...(provider === "custom" ? { base_url: baseUrl } : {}), ...(secret ? { api_key: secret } : endpoint ? { endpoint_id: endpoint.id } : {}) };
      setModels((await catalog(query)).models);
      setModelsState("idle");
    } catch (e) {
      setModels(null);
      setModelsState(e instanceof ApiError && e.code === "upstream_credential_rejected" ? "rejected" : "failed");
    }
  }
  // Sponsored needs no key: its allow-list loads as soon as it is the provider.
  const [allowed, setAllowed] = useState<string[] | "failed" | null>(null);
  useEffect(() => {
    if (!isSponsored) return;
    let active = true;
    catalog({ provider: "sponsored" }).then((data) => {
      if (!active) return;
      const list = Array.isArray(data.models) ? data.models : [];
      setAllowed(list);
      setModel((current) => (current && list.includes(current) ? current : list[0] ?? ""));
    }).catch(() => { if (active) setAllowed("failed"); });
    return () => { active = false; };
  }, [isSponsored, catalog]);
  const chooseProvider = (next: string) => { setProvider(next); setSecret(""); setModels(null); setModelsState("idle"); setTyping(false); if (next === "sponsored" || provider === "sponsored") setModel(""); };
  // One policy version: nothing to choose, so it is preselected.
  const [policyId, setPolicyId] = useState(endpoint?.policy_version_id ?? (policies.length === 1 ? policies[0]!.policy_version_id : ""));
  const [reviewed, setReviewed] = useState(false);
  const [reenable, setReenable] = useState(false);
  const titleId = useId();
  useFocusOnOpen(titleId);
  const changed = Boolean(endpoint && endpoint.policy_version_id !== policyId);
  const latestOf = latestVersions(policies);
  const selected = policies.find((p) => p.policy_version_id === policyId);
  const requiresCredential = provider !== "sponsored" && (!endpoint?.credential_configured || endpoint.provider !== provider);
  const keyLabel = requiresCredential ? "Provider API key" : "Replace provider API key (optional)";
  const blockedReason = isSponsored && !model ? "Choose a model to save." : !policyId ? "Choose a policy version to save." : changed && !reviewed ? "Confirm the policy change below to save." : "";
  return (
    // Escape anywhere in the form, its focused heading included, is Cancel (LAB-1626).
    <div onKeyDown={escapeTo(onCancel, busy)}>
    <Card
      title={endpoint ? `Edit ${endpoint.name}` : "Create endpoint"}
      titleId={titleId}
      subtitle={endpoint ? "Changes apply to future requests through this endpoint." : "Clients reach the model through this endpoint with an endpoint key."}
    >
      <form
        aria-labelledby={titleId}
        className="space-y-4"
        onSubmit={(e) => { e.preventDefault(); const apiKey = secret; setSecret(""); void onSave({ name, provider, model: model.trim() || null, policy_version_id: policyId, enabled: endpoint ? endpoint.enabled || reenable : true, ...(provider === "custom" ? { base_url: baseUrl } : {}), ...(apiKey ? { api_key: apiKey } : {}) }); }}
      >
        <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <Field label="Endpoint name" required hint="Shown in logs and in the project switcher.">
            <Input maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Provider" required>
            <Select value={provider} onChange={(e) => chooseProvider(e.target.value)}>
              {[...(hosted ? ["sponsored"] : []), "meta", "openai", "fireworks", "openrouter", "custom"].map((value) => <option key={value} value={value}>{providerLabel(value)}</option>)}
            </Select>
          </Field>
          {provider === "custom" && (
            <Field label="Upstream base URL" required hint="Use a public HTTPS endpoint for hosted deployments.">
              <Input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
            </Field>
          )}
          {isSponsored ? (
            <Field label="Model" required hint={allowed === "failed" ? "The allowed models could not be loaded. Enter one the operator allows." : "Requests without your own key use one of the allowed models."}>
              {Array.isArray(allowed) && allowed.length ? (
                <Select value={model} onChange={(e) => setModel(e.target.value)}>
                  {allowed.map((m) => <option key={m} value={m}>{m}</option>)}
                </Select>
              ) : (
                <Input maxLength={256} value={model} onChange={(e) => setModel(e.target.value)} placeholder={allowed === null ? "Loading allowed models…" : "muse-spark-1.3"} />
              )}
            </Field>
          ) : (
            <Field label="Model (optional)" hint={
                modelsState === "rejected" ? `${providerLabel(provider)} refused the API key. Check the API key, then load again, or type a model ID.`
                  : modelsState === "failed" ? `${providerLabel(provider)} did not list its models. Type a model ID, or leave it empty.`
                    : models && !models.length ? `${providerLabel(provider)} listed no models. Type a model ID, or leave it empty.`
                      : listing ? "Pick ‘Client chooses’ to let Codex or Muse Code send their own model."
                        : "Leave empty to let your client choose, e.g. Codex or Muse Code."
              }>
              {listing && models ? (
                <Select value={model} onChange={(e) => { if (e.target.value === OTHER_MODEL) setTyping(true); else setModel(e.target.value); }}>
                  <option value="">Client chooses (no pinned model)</option>
                  {[...(model && !models.includes(model) ? [model] : []), ...models].map((m) => <option key={m} value={m}>{m}</option>)}
                  <option value={OTHER_MODEL}>Other model ID…</option>
                </Select>
              ) : (
                <Input maxLength={256} value={model} onChange={(e) => setModel(e.target.value)} placeholder="Client chooses" />
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button size="sm" className="max-sm:h-11" busy={modelsState === "loading"} disabled={!canLoadModels} onClick={() => { setTyping(false); void loadModels(); }}>{modelsState === "loading" ? "Loading models…" : models ? "Reload models" : loadLabel}</Button>
                {models && models.length > 0 && typing && <Button size="sm" variant="ghost" className="max-sm:h-11" onClick={() => setTyping(false)}>Choose from the list</Button>}
                {!canLoadModels && <p className="text-xs text-muted">{loadBlocked}</p>}
              </div>
            </Field>
          )}
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
              {policies.map((policy) => <option key={policy.policy_version_id} value={policy.policy_version_id}>{policy.name} · v{policy.version}{latestOf.get(policy.policy_id) === policy.version ? " (latest)" : ""}</option>)}
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
    </div>
  );
}

function PolicyForm({ policy, template, endpoints, hosted, busy, onSave, onCancel }: { policy?: PolicyVersion; template?: PolicyVersion; endpoints: Endpoint[]; hosted: boolean; busy: boolean; onSave: (body: PolicyBody) => Promise<void>; onCancel: () => void }) {
  const [name, setName] = useState(policy?.name ?? "");
  const [entities, setEntities] = useState({ ...(policy?.entity_policies ?? template?.entity_policies ?? defaults) });
  const [language, setLanguage] = useState(policy?.language ?? template?.language ?? "hu");
  const [mode, setMode] = useState(hosted ? "fast" : policy?.mode ?? template?.mode ?? "fast");
  const start = policy ?? template;
  // A version saved before visual types existed shows the defaults (the server's, LAB-1444).
  const [visual, setVisual] = useState(() => Object.fromEntries(VISUAL_ENTITY_TYPES.map((type) => {
    const saved = start?.entity_policies[type];
    return [type, saved === "keep" || saved === "mask" ? saved : visualDefaults[type]];
  })) as Record<VisualEntityType, "mask" | "keep">);
  // Hosted images are on-device only until SAM has its own spend reservation.
  const [detection, setDetection] = useState<VisualDetection>(hosted ? "local" : start?.visual_detection ?? "local");
  const titleId = useId();
  useFocusOnOpen(titleId);
  const affected = endpoints.filter((e) => e.enabled && e.policy_id === policy?.policy_id);
  return (
    <div onKeyDown={escapeTo(onCancel, busy)}>
    <Card title={policy ? `New version of ${policy.name}` : "Create policy"} titleId={titleId} subtitle="Mask replaces detected values with reversible placeholders. Keep sends them unchanged. Block refuses the entire request when that type is detected.">
      <form aria-labelledby={titleId} className="space-y-4" onSubmit={(e) => { e.preventDefault(); void onSave({ name, entity_policies: { ...entities, ...visual }, language, mode, visual_detection: detection }); }}>
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
        <fieldset disabled={busy} className="min-w-0">
          <legend className="mb-3 text-sm font-medium text-ink">Images</legend>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field
              label="Detection"
              hint={hosted
                ? "The hosted service detects on its own CPU only; SAM 3.1 needs a self-hosted install."
                : detection === "sam"
                  ? "The original image is sent to Meta's API for signatures and stamps. Needs a SAM key on the server; a server set to on-device detection stays on-device."
                  : "Faces, ID photos and signatures are found on the guard's CPU. Stamps cannot be detected on-device, so they can only be kept."}
            >
              <Select value={detection} onChange={(e) => setDetection(e.target.value as VisualDetection)}>
                <option value="local">{VISUAL_DETECTION_LABEL.local}</option>
                <option value="sam" disabled={hosted}>{VISUAL_DETECTION_LABEL.sam}</option>
              </Select>
            </Field>
            {VISUAL_ENTITY_TYPES.map((type) => (
              <Field key={type} label={ENTITY_META[type].label}>
                <Select value={visual[type]} onChange={(e) => setVisual((prev) => ({ ...prev, [type]: e.target.value as "mask" | "keep" }))}>
                  <option value="mask">Mask</option>
                  <option value="keep">Keep</option>
                </Select>
              </Field>
            ))}
          </div>
          {detection === "local" && visual.STAMP === "mask" && (
            <p role="alert" className="mt-2 text-sm text-warn">{hosted ? "Detection on the PII Guard server" : "On-device detection"} cannot find stamps, so every image would be refused. Keep stamps, or choose SAM 3.1.</p>
          )}
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
    </div>
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
  const active = keys.filter((k) => !k.revoked_at).sort(newestFirst);
  const revoked = keys.filter((k) => k.revoked_at).sort(newestFirst);
  const url = `${globalThis.location.origin}${endpoint.base_path}`;
  const snippet = `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(url)},\n    api_key=os.environ["PII_GUARD_ENDPOINT_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(endpoint.model ?? "<model-id>")},\n    messages=[{"role": "user", "content": "Hello, Robin Example."}],\n)`;
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
        {!endpoint.model && <p className="text-xs text-muted">This endpoint has no pinned model: replace <span className="font-mono">&lt;model-id&gt;</span> with the model your client uses{exampleModel(endpoint.provider) ? <>, for example <span className="font-mono">{exampleModel(endpoint.provider)}</span></> : " (a model ID this endpoint serves)"}.</p>}
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
        {active.length > 0 && (
          <ul className={LIST} aria-labelledby={keysTitle}>
            {active.map((key) => (
              <KeyRow key={key.id} item={key}>
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
              </KeyRow>
            ))}
          </ul>
        )}
        {loaded && keys.length > 0 && !active.length && <p className="text-sm text-muted">No active endpoint keys. Create one to connect an application to this endpoint.</p>}
        {revoked.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted hover:text-ink">Show {plural(revoked.length, "revoked key")}</summary>
            <ul className={`${LIST} mt-3`} aria-label="Revoked endpoint keys">
              {revoked.map((key) => <KeyRow key={key.id} item={key} />)}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}

/** Newest first; created_at is ISO 8601, so it sorts as text. */
const newestFirst = (a: EndpointKey, b: EndpointKey) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0);

function KeyRow({ item, children }: { item: EndpointKey; children?: ReactNode }) {
  return (
    <li className={ROW}>
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-ink break-words">
          {item.name}
          <Badge tone={item.revoked_at ? "failed" : "live"}>{item.revoked_at ? "Revoked" : "Active"}</Badge>
        </p>
        <p className="mt-0.5 text-sm text-muted">
          Created <time dateTime={item.created_at} title={dateTime(item.created_at)}>{relativeTime(item.created_at)}</time>
          {item.revoked_at && <>, revoked <time dateTime={item.revoked_at} title={dateTime(item.revoked_at)}>{relativeTime(item.revoked_at)}</time></>}
        </p>
      </div>
      {children}
    </li>
  );
}

