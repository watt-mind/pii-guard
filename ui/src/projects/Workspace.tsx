import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { ApiError } from "../api/http";
import { Button, Card, Field, Input, Notice, PageHeader, Select } from "../components/ui";
import { recovery, request, type Requester } from "../hosted/api";
import OwnerAccessPanel from "./OwnerAccess";
import {
  pendingPolicyEdit,
  pendingPolicyEndpoint,
  projectPath,
  requestPolicyEdit,
  type Endpoint,
  type EndpointModels,
  type EndpointModelsQuery,
  type PolicyVersion,
  type Project,
  type ProjectList,
} from "./api";
import { localRequest } from "./request";
import { EndpointConnection, EndpointForm, EndpointsSection, type EndpointBody, type Notified } from "./WorkspaceEndpoints";
import { PoliciesSection, PolicyForm, type PolicyBody } from "./WorkspacePolicy";

export { EndpointConnection, EndpointForm, EndpointsSection, PoliciesSection, PolicyForm };

const OwnerAccess = import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? null : OwnerAccessPanel;

const configurationRecovery =
  import.meta.env.VITE_PII_GUARD_HOSTED === "true"
    ? (error: unknown) => recovery(error)
    : (error: unknown, hosted: boolean) => {
        if (hosted) return recovery(error);
        if (error instanceof ApiError) {
          if (error.status === 401 || error.status === 403)
            return "The guard refused owner access. Open Local guard access and enter the owner API token configured on this server, then retry. Check that you are using the guard’s current address.";
          if (error.status === 400 || error.status === 422) return "The guard refused these settings. Check the form and try again.";
          if (error.status === 404) return "This project or endpoint is unavailable. Reload the project list and check that the guard supports project configuration.";
          if (error.status === 503 && error.code === "project_storage_unavailable")
            return "The guard is up, but its project storage is not configured or not reachable. Check the server's project storage settings, then retry.";
        }
        return "The guard could not complete this request. Check its connection and retry.";
      };

/** The confirmation of a project just created, across the console's remount on the new scope. */
let carried: string | null = null;

interface Props {
  call?: Requester;
  hosted?: boolean;
  projectId?: string;
  onProject?: (project: Project) => void;
}

const ENDPOINTS_TITLE = "pw-endpoints-title";
const POLICIES_TITLE = "pw-policies-title";
const byId = (id: string) => () => document.getElementById(id);

/** Move focus after the next render, once the target exists (a heading, a trigger). */
function useFocusLater() {
  const target = useRef<(() => HTMLElement | null | undefined) | null>(null);
  const [tick, setTick] = useState(0);
  useLayoutEffect(() => {
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

function pickDefaultProject(data: ProjectList, projectId?: string): Project | undefined {
  return data.projects.find((p) => p.id === projectId) ?? data.projects.find((p) => p.id === data.default_project_id) ?? data.projects[0];
}

interface ProjectSelectorCardProps {
  projects: Project[];
  selected: string;
  busy: boolean;
  name: string;
  created: string;
  projectSelect: RefObject<HTMLSelectElement | null>;
  onSelectProject: (next: Project) => void;
  onName: (v: string) => void;
  onCreateProject: () => void;
}

function ProjectSelectorCard({ projects, selected, busy, name, created, projectSelect, onSelectProject, onName, onCreateProject }: ProjectSelectorCardProps) {
  return (
    <Card title="Project" subtitle="Endpoints, keys and policies below belong to the current project.">
      <div className="grid gap-4 sm:grid-cols-2">
        {projects.length > 0 ? (
          <Field label="Current project">
            <Select
              ref={projectSelect}
              value={selected}
              disabled={busy}
              onChange={(e) => {
                const next = projects.find((p) => p.id === e.target.value)!;
                onSelectProject(next);
              }}
            >
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
        ) : (
          <p className="text-sm text-muted">No projects yet. Create a project to configure policies and endpoints.</p>
        )}
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) onCreateProject();
          }}
        >
          <Field label="New project name" className="min-w-40 flex-1">
            <Input maxLength={64} value={name} onChange={(e) => onName(e.target.value)} />
          </Field>
          <Button type="submit" busy={busy} disabled={!busy && !name.trim()}>{busy ? "Creating…" : "Create project"}</Button>
        </form>
      </div>
      {created && <Notice tone="success" live className="mt-4">{created}</Notice>}
    </Card>
  );
}

function resolveRequester(suppliedCall: Requester | undefined, hosted: boolean): Requester {
  if (suppliedCall) return suppliedCall;
  return hosted ? request : localRequest;
}

function useProjectsList(call: Requester, hosted: boolean, projectId: string | undefined, onProject: ((project: Project) => void) | undefined) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState(projectId ?? "");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    call<ProjectList>("/v1/projects")
      .then((data) => {
        if (!Array.isArray(data.projects)) throw new Error("Invalid projects");
        if (!active) return;
        setProjects(data.projects);
        setLoaded(true);
        const project = pickDefaultProject(data, projectId);
        if (project) {
          setSelected(project.id);
          if (project.id !== projectId) onProject?.(project);
        }
        setError("");
      })
      .catch((e: unknown) => {
        if (active) setError(configurationRecovery(e, hosted));
      });
    return () => {
      active = false;
    };
  }, [call, projectId, onProject, retry, hosted]);

  return { projects, setProjects, loaded, selected, setSelected, error, setError, retryProjects: () => setRetry((n) => n + 1) };
}

/** Project configuration only. Secrets live in component memory, never browser storage. */
export function Workspace({ call: suppliedCall, hosted = false, projectId, onProject }: Props) {
  const call = resolveRequester(suppliedCall, hosted);
  const { projects, setProjects, loaded, selected, setSelected, error, setError, retryProjects } = useProjectsList(call, hosted, projectId, onProject);
  const [name, setName] = useState("");
  // A new project becomes the console's scope, which remounts the console: its confirmation and
  // the focus move are carried across that remount.
  const [created, setCreated] = useState(() => carried ?? "");
  const [refocus] = useState(() => carried !== null);
  const [busy, setBusy] = useState(false);
  const focusLater = useFocusLater();
  const projectSelect = useRef<HTMLSelectElement>(null);
  const project = projects.find((p) => p.id === selected);

  // Read once, at mount (above); cleared when this instance goes, so it never reaches a later mount.
  useEffect(() => () => {
    carried = null;
  }, []);
  useLayoutEffect(() => {
    if (refocus && projects.length) projectSelect.current?.focus();
  }, [refocus, projects.length]);

  const createProject = () => {
    const wanted = name.trim();
    setBusy(true);
    setError("");
    setCreated("");
    void call<Project>("/v1/projects", { name })
      .then((next) => {
        const message = `Project '${next.name || wanted}' created.`;
        carried = message;
        setProjects((prev) => [...prev, next]);
        setSelected(next.id);
        setName("");
        setCreated(message);
        // The submit button is disabled again (empty name): focus moves to the new project.
        focusLater(() => projectSelect.current);
        onProject?.(next);
      })
      .catch((e: unknown) => setError(configurationRecovery(e, hosted)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        lead="Keep each application’s endpoints, endpoint keys and policies together. Every endpoint pins one upstream and one policy version, and can pin one model."
      />
      {!hosted && OwnerAccess && <OwnerAccess />}
      {error && (
        <Notice tone="danger" live action={<Button size="sm" onClick={retryProjects}>Retry projects</Button>}>
          {error}
        </Notice>
      )}
      {loaded && (
        <ProjectSelectorCard
          projects={projects}
          selected={selected}
          busy={busy}
          name={name}
          created={created}
          projectSelect={projectSelect}
          onSelectProject={(next) => {
            setSelected(next.id);
            setCreated("");
            onProject?.(next);
          }}
          onName={setName}
          onCreateProject={createProject}
        />
      )}
      {/* A tall placeholder, so the cards that replace it don't push anything on screen (CLS, LAB-1619). */}
      {!loaded && !error && <p role="status" className="min-h-dvh text-sm text-muted">Loading your default project…</p>}
      {project && <ProjectConfiguration key={project.id} project={project} call={call} hosted={hosted} />}
    </div>
  );
}

/** The endpoint as saved, with another policy version or enabled state; the stored credential stays (omitted). */
function endpointBody(endpoint: Endpoint, change: Partial<Pick<EndpointBody, "policy_version_id" | "enabled">>): EndpointBody {
  return {
    name: endpoint.name,
    provider: endpoint.provider,
    model: endpoint.model,
    policy_version_id: endpoint.policy_version_id,
    enabled: endpoint.enabled,
    ...(endpoint.provider === "custom" ? { base_url: endpoint.base_url } : {}),
    ...change,
  };
}

function findWantedPolicyStart(policies: PolicyVersion[], endpoints: Endpoint[], wantedEdit: string, wantedEndpoint: string | null): PolicyVersion | undefined {
  const family = policyFamilies(policies).find((f) => f.latest.policy_id === wantedEdit);
  // Start from the version the endpoint uses, not the latest (LAB-1640): Tune changes what that
  // endpoint masks, so a newer version's other changes must not ride along unseen.
  const pinned = endpoints.find((e) => e.id === wantedEndpoint && e.policy_id === wantedEdit);
  return (pinned && policies.find((p) => p.policy_version_id === pinned.policy_version_id)) ?? family?.latest;
}

function usePendingPolicyTune(loaded: boolean, policies: PolicyVersion[], endpoints: Endpoint[], onStartTune: (policy: PolicyVersion) => void) {
  const [wantedEdit] = useState(pendingPolicyEdit);
  const [wantedEndpoint] = useState(pendingPolicyEndpoint);
  const [openedWanted, setOpenedWanted] = useState(false);
  if (wantedEdit && loaded && !openedWanted) {
    setOpenedWanted(true);
    requestPolicyEdit(null);
    const start = findWantedPolicyStart(policies, endpoints, wantedEdit, wantedEndpoint);
    if (start) onStartTune(start);
  }
  return { wantedEdit, wantedEndpoint };
}

/** "A", "A and B", "3 endpoints". */
function listNames(items: { name: string }[]): string {
  if (items.length > 2) return `${items.length} endpoints`;
  return items.map((e) => `'${e.name}'`).join(" and ");
}

function buildPolicySavedNotice(name: string, saved: Partial<PolicyVersion> | undefined, applyTo: Endpoint[]): Notified {
  const version = saved?.version ? ` v${saved.version}` : "";
  const applied = Boolean(applyTo.length && saved?.policy_version_id);
  return {
    area: "policies",
    text: applied
      ? `Policy '${name}'${version} saved and applied to ${listNames(applyTo)}. The next request uses it.`
      : `Policy '${name}'${version} saved.`,
  };
}

function buildEndpointSavedNotice(name: string, creating: boolean, saved: Partial<Endpoint> | undefined): Notified {
  if (creating) {
    return {
      area: "endpoints",
      text: `Endpoint '${name}' created. Next, create an endpoint key so your application can use it.`,
      endpointId: saved?.id,
    };
  }
  return { area: "endpoints", text: `Endpoint '${name}' saved.` };
}

function useProjectConfigData(base: string, call: Requester, hosted: boolean) {
  const [policies, setPolicies] = useState<PolicyVersion[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  async function reload() {
    const [policyData, endpointData] = await Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]);
    if (!Array.isArray(policyData.policies) || !Array.isArray(endpointData.endpoints)) throw new Error("Invalid configuration");
    setPolicies(policyData.policies);
    setEndpoints(endpointData.endpoints);
    setLoaded(true);
    window.dispatchEvent(new Event("pii-guard-project-configuration"));
  }
  useEffect(() => {
    let active = true;
    void Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)])
      .then(([p, e]) => {
        if (!Array.isArray(p.policies) || !Array.isArray(e.endpoints)) throw new Error("Invalid configuration");
        if (active) {
          setPolicies(p.policies);
          setEndpoints(e.endpoints);
          setLoaded(true);
        }
      })
      .catch((e: unknown) => {
        if (active) setError(configurationRecovery(e, hosted));
      });
    return () => {
      active = false;
    };
  }, [base, call, hosted]);
  return { policies, endpoints, loaded, error, setError, reload };
}

function findNextApplicablePolicyVersion(endpoint: Endpoint, policies: PolicyVersion[], latest: Map<string, number>): PolicyVersion | undefined {
  const v = latest.get(endpoint.policy_id) ?? 0;
  return v > endpoint.policy_version ? policies.find((p) => p.policy_id === endpoint.policy_id && p.version === v) : undefined;
}

async function applySavedPolicyToEndpoints(call: Requester, base: string, applyTo: Endpoint[], versionId: string | undefined) {
  if (!applyTo.length || !versionId) return;
  for (const target of applyTo) {
    await call(`${base}/endpoints/${encodeURIComponent(target.id)}`, endpointBody(target, { policy_version_id: versionId }), "PUT");
  }
}

function ActivePolicyForm({
  policyEdit,
  policies,
  defaultPolicyId,
  endpoints,
  wantedEdit,
  wantedEndpoint,
  latest,
  hosted,
  busy,
  onCancel,
  onSave,
}: {
  policyEdit: PolicyVersion | "new" | null;
  policies: PolicyVersion[];
  defaultPolicyId?: string | null;
  endpoints: Endpoint[];
  wantedEdit: string | null;
  wantedEndpoint: string | null;
  latest: Map<string, number>;
  hosted: boolean;
  busy: boolean;
  onCancel: () => void;
  onSave: (targetEdit: PolicyVersion | "new", body: PolicyBody, applyTo: Endpoint[]) => Promise<void>;
}) {
  if (!policyEdit) return null;
  const target = policyEdit === "new" ? undefined : policyEdit;
  return (
    <PolicyForm
      template={policies.find((p) => p.policy_id === defaultPolicyId) ?? policies[0]}
      key={`policy-form-${target ? target.policy_version_id : "new"}`}
      policy={target}
      endpoints={endpoints}
      preferred={target && target.policy_id === wantedEdit ? wantedEndpoint : null}
      latest={target ? latest.get(target.policy_id) : undefined}
      hosted={hosted}
      busy={busy}
      onCancel={onCancel}
      onSave={(body, applyTo) => onSave(policyEdit, body, applyTo)}
    />
  );
}

function ActiveEndpointForm({
  endpointEdit,
  policies,
  busy,
  hosted,
  catalog,
  onCancel,
  onSave,
  onDisable,
}: {
  endpointEdit: Endpoint | "new" | null;
  policies: PolicyVersion[];
  busy: boolean;
  hosted: boolean;
  catalog: (query: EndpointModelsQuery) => Promise<EndpointModels>;
  onCancel: () => void;
  onSave: (targetEdit: Endpoint | "new", body: EndpointBody) => Promise<void>;
  onDisable: (target: Endpoint) => Promise<void>;
}) {
  if (!endpointEdit) return null;
  const target = endpointEdit === "new" ? undefined : endpointEdit;
  return (
    <EndpointForm
      key={`endpoint-form-${target ? target.id : "new"}`}
      endpoint={target}
      policies={policies}
      busy={busy}
      hosted={hosted}
      catalog={catalog}
      onCancel={onCancel}
      onSave={(body) => onSave(endpointEdit, body)}
      onDisable={target ? () => onDisable(target) : undefined}
    />
  );
}

function ProjectConfiguration({ project, call, hosted }: { project: Project; call: Requester; hosted: boolean }) {
  const base = projectPath(project.id);
  const { policies, endpoints, loaded, error, setError, reload } = useProjectConfigData(base, call, hosted);
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
  const catalog = useCallback((query: EndpointModelsQuery) => call<EndpointModels>(`${base}/endpoints/models`, query, "POST"), [call, base]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice(null);
    try {
      await work();
    } catch (e) {
      setError(configurationRecovery(e, hosted));
    } finally {
      setBusy(false);
    }
  }

  const openEndpointForm = (next: Endpoint | "new") => {
    setEndpointEdit(next);
    setPolicyEdit(null);
    setInspect("");
    setNotice(null);
  };
  const openPolicyForm = (next: PolicyVersion | "new") => {
    setPolicyEdit(next);
    setEndpointEdit(null);
    setNotice(null);
  };
  const closeEndpointForm = () => {
    const was = endpointEdit;
    setEndpointEdit(null);
    focusLater(() => (!was || was === "new" ? createEndpointRef.current : editRefs.current.get(was.id)));
  };
  const closePolicyForm = () => {
    const was = policyEdit;
    setPolicyEdit(null);
    focusLater(() => (!was || was === "new" ? createPolicyRef.current : versionRefs.current.get(was.policy_version_id)));
  };
  const latest = latestVersions(policies);
  const applyLatest = (endpoint: Endpoint) =>
    action(async () => {
      const next = findNextApplicablePolicyVersion(endpoint, policies, latest);
      if (!next) return;
      await call(`${base}/endpoints/${encodeURIComponent(endpoint.id)}`, endpointBody(endpoint, { policy_version_id: next.policy_version_id }), "PUT");
      await reload();
      setNotice({ area: "endpoints", text: `Endpoint '${endpoint.name}' now uses ${next.name} v${next.version}. The next request uses it.` });
      focusLater(byId(ENDPOINTS_TITLE));
    });
  const deleteEndpoint = (endpoint: Endpoint) =>
    action(async () => {
      await call(`${base}/endpoints/${encodeURIComponent(endpoint.id)}`, undefined, "DELETE");
      await reload();
      setNotice({ area: "endpoints", text: `Endpoint '${endpoint.name}' deleted.` });
      focusLater(byId(ENDPOINTS_TITLE));
    });

  // Opened from Connect's "Tune what is masked": a new version of that policy, its form focused.
  const { wantedEdit, wantedEndpoint } = usePendingPolicyTune(loaded, policies, endpoints, (start) => {
    setPolicyEdit(start);
    setEndpointEdit(null);
  });

  const savePolicy = (targetEdit: PolicyVersion | "new", body: PolicyBody, applyTo: Endpoint[]) =>
    action(async () => {
      const isNew = targetEdit === "new";
      const path = isNew ? `${base}/policies` : `${base}/policies/${encodeURIComponent(targetEdit.policy_id)}`;
      const saved = await call<Partial<PolicyVersion> | undefined>(path, body, isNew ? "POST" : "PUT");
      await applySavedPolicyToEndpoints(call, base, applyTo, saved?.policy_version_id);
      await reload();
      setPolicyEdit(null);
      setNotice(buildPolicySavedNotice(body.name, saved, applyTo));
      focusLater(byId(POLICIES_TITLE));
    });

  const saveEndpoint = (targetEdit: Endpoint | "new", body: EndpointBody) =>
    action(async () => {
      const creating = targetEdit === "new";
      const path = creating ? `${base}/endpoints` : `${base}/endpoints/${encodeURIComponent(targetEdit.id)}`;
      const saved = await call<Partial<Endpoint> | undefined>(path, body, creating ? "POST" : "PUT");
      await reload();
      setEndpointEdit(null);
      setNotice(buildEndpointSavedNotice(body.name, creating, saved));
      focusLater(byId(ENDPOINTS_TITLE));
    });

  const disableEndpoint = (target: Endpoint) =>
    action(async () => {
      await call(`${base}/endpoints/${encodeURIComponent(target.id)}`, endpointBody(target, { enabled: false }), "PUT");
      await reload();
      setEndpointEdit(null);
      setInspect("");
      setNotice({ area: "endpoints", text: `Endpoint '${target.name}' disabled. Its endpoint keys are revoked.` });
      focusLater(byId(ENDPOINTS_TITLE));
    });

  const policyForm = (
    <ActivePolicyForm
      policyEdit={policyEdit}
      policies={policies}
      defaultPolicyId={project.default_policy_id}
      endpoints={endpoints}
      wantedEdit={wantedEdit}
      wantedEndpoint={wantedEndpoint}
      latest={latest}
      hosted={hosted}
      busy={busy}
      onCancel={closePolicyForm}
      onSave={savePolicy}
    />
  );

  const endpointForm = (
    <ActiveEndpointForm
      endpointEdit={endpointEdit}
      policies={policies}
      busy={busy}
      hosted={hosted}
      catalog={catalog}
      onCancel={closeEndpointForm}
      onSave={saveEndpoint}
      onDisable={disableEndpoint}
    />
  );

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">
        Configuration is saved {hosted ? "on the PII Guard server" : "by the guard"}. Restoration mappings and activity remain temporary.
        {loaded && !policies.length ? " Create a policy first: every endpoint pins one policy version." : ""}
      </p>
      {error && (
        <Notice tone="danger" live action={<Button size="sm" busy={busy} onClick={() => void action(reload)}>Reload configuration</Button>}>
          {error}
        </Notice>
      )}
      {!loaded && !error ? (
        <p role="status" className="min-h-dvh text-sm text-muted">Loading endpoints and policies…</p>
      ) : (
        <>
          <PoliciesSection
            policies={policies}
            endpoints={endpoints}
            loaded={loaded}
            busy={busy}
            notice={notice}
            policyEdit={policyEdit}
            policyForm={policyForm}
            createPolicyRef={createPolicyRef}
            versionRefs={versionRefs}
            onOpenPolicyForm={openPolicyForm}
          />
          <EndpointsSection
            endpoints={endpoints}
            policies={policies}
            loaded={loaded}
            busy={busy}
            hosted={hosted}
            base={base}
            call={call}
            notice={notice}
            endpointEdit={endpointEdit}
            inspect={inspect}
            createEndpointRef={createEndpointRef}
            editRefs={editRefs}
            endpointForm={endpointForm}
            onOpenNew={() => openEndpointForm("new")}
            onOpenEdit={openEndpointForm}
            onToggleInspect={(id) => {
              setInspect(inspect === id ? "" : id);
              setEndpointEdit(null);
            }}
            onInspectFromNotice={(id) => {
              setInspect(id);
              setNotice(null);
            }}
            onApplyLatest={(endpoint) => void applyLatest(endpoint)}
            onDelete={(endpoint) => void deleteEndpoint(endpoint)}
          />
        </>
      )}
    </div>
  );
}
