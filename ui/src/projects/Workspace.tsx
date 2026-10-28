import { useEffect, useState } from "react";
import { TEXT_ENTITY_TYPES, type TextEntityType } from "../api/types";
import { ENTITY_META, type Policy } from "../lib/entities";
import { request, recovery, type Requester } from "../hosted/api";
import { projectPath, type Endpoint, type EndpointKey, type PolicyVersion, type Project, type ProjectList } from "./api";
import "./workspace.css";

interface Props { call?: Requester; hosted?: boolean; projectId?: string; onProject?: (project: Project) => void }
const defaults = Object.fromEntries(TEXT_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy])) as Record<TextEntityType, Policy>;

/** Project configuration only. Secrets live in component memory, never browser storage. */
export function Workspace({ call = request, hosted = false, projectId, onProject }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState(projectId ?? "");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    call<ProjectList>("/v1/projects").then((data) => {
      if (!Array.isArray(data.projects)) throw new Error("Invalid projects");
      if (!active) return;
      setProjects(data.projects);
      const project = data.projects.find((p) => p.id === projectId) ?? data.projects.find((p) => p.id === data.default_project_id) ?? data.projects[0];
      if (project) { setSelected(project.id); onProject?.(project); }
      setError("");
    }).catch((e: unknown) => { if (active) setError(recovery(e)); });
    return () => { active = false; };
  }, [call, projectId, onProject, retry]);
  const project = projects.find((p) => p.id === selected);
  return <div className="project-workspace">
    <div className="pw-heading"><div><h2>Projects & endpoints</h2><p>Keep each application’s credentials, policy assignments and sessions together.</p></div></div>
    {error && <div className="pw-error" role="alert"><p>{error}</p><button onClick={() => setRetry((n) => n + 1)}>Retry projects</button></div>}
    {projects.length > 0 && <div className="pw-projects">
      <label>Current project<select value={selected} disabled={busy} onChange={(e) => { const next = projects.find((p) => p.id === e.target.value)!; setSelected(next.id); onProject?.(next); }}>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label>
      <form onSubmit={(e) => { e.preventDefault(); setBusy(true); setError(""); void call<Project>("/v1/projects", { name }).then((next) => { setProjects((prev) => [...prev, next]); setSelected(next.id); setName(""); onProject?.(next); }).catch((e: unknown) => setError(recovery(e))).finally(() => setBusy(false)); }}>
        <label>New project name<input required maxLength={64} value={name} onChange={(e) => setName(e.target.value)} /></label><button type="submit" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create project"}</button>
      </form>
    </div>}
    {!projects.length && !error && <p role="status">Loading your default project…</p>}
    {project && <ProjectConfiguration key={project.id} project={project} call={call} hosted={hosted} />}
  </div>;
}

function ProjectConfiguration({ project, call, hosted }: { project: Project; call: Requester; hosted: boolean }) {
  const [policies, setPolicies] = useState<PolicyVersion[]>([]);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [endpointEdit, setEndpointEdit] = useState<Endpoint | "new" | null>(null);
  const [policyEdit, setPolicyEdit] = useState<PolicyVersion | "new" | null>(null);
  const [inspect, setInspect] = useState("");
  const base = projectPath(project.id);
  async function reload() {
    const [policyData, endpointData] = await Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]);
    if (!Array.isArray(policyData.policies) || !Array.isArray(endpointData.endpoints)) throw new Error("Invalid configuration");
    setPolicies(policyData.policies); setEndpoints(endpointData.endpoints); setLoaded(true);
    window.dispatchEvent(new Event("pii-guard-project-configuration"));
  }
  useEffect(() => { let active = true; void Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]).then(([p, e]) => { if (!Array.isArray(p.policies) || !Array.isArray(e.endpoints)) throw new Error("Invalid configuration"); if (active) { setPolicies(p.policies); setEndpoints(e.endpoints); setLoaded(true); } }).catch((e: unknown) => { if (active) setError(recovery(e)); }); return () => { active = false; }; }, [base, call]);
  async function action(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (e) { setError(recovery(e)); } finally { setBusy(false); } }
  return <div className="pw-stack">
    <p className="pw-note">Configuration is saved by the guard. Restoration mappings and activity remain temporary. {hosted && "This hosted preview supports text only."}</p>
    {error && <div role="alert" className="pw-error">{error}<button onClick={() => void action(reload)}>Reload configuration</button></div>}
    {!loaded && !error && <p role="status">Loading endpoints and policies…</p>}
    <section className="pw-panel" aria-labelledby="endpoint-heading"><div className="pw-heading"><div><h3 id="endpoint-heading">Gateway endpoints</h3><p>One upstream, model and pinned policy version per endpoint.</p></div><button disabled={!loaded || busy || !policies.length} onClick={() => { setEndpointEdit("new"); setPolicyEdit(null); }}>Create endpoint</button></div>
      {loaded && !endpoints.length && <p>No endpoints yet. Create one, then issue a scoped key to connect your application.</p>}
      <ul className="pw-list">{endpoints.map((endpoint) => <li key={endpoint.id}><div><h4>{endpoint.name} {!endpoint.enabled && <span>· disabled</span>}</h4><p>{endpoint.provider} · {endpoint.model}</p><p>{policies.find((p) => p.policy_version_id === endpoint.policy_version_id)?.name ?? "Policy"} · v{endpoint.policy_version}</p></div><div className="pw-actions"><button onClick={() => { setInspect(inspect === endpoint.id ? "" : endpoint.id); setEndpointEdit(null); }}>Connect & keys</button><button disabled={busy} onClick={() => { setEndpointEdit(endpoint); setPolicyEdit(null); }}>Edit endpoint</button></div></li>)}</ul>
    </section>
    {endpointEdit && <EndpointForm key={`endpoint-form-${typeof endpointEdit === "string" ? "new" : endpointEdit.id}`} endpoint={endpointEdit === "new" ? undefined : endpointEdit} policies={policies} busy={busy} hosted={hosted} onCancel={() => setEndpointEdit(null)} onSave={(body) => action(async () => { await call(endpointEdit === "new" ? `${base}/endpoints` : `${base}/endpoints/${encodeURIComponent(endpointEdit.id)}`, body, endpointEdit === "new" ? "POST" : "PUT"); await reload(); setEndpointEdit(null); })} onDisable={endpointEdit === "new" ? undefined : () => action(async () => { await call(`${base}/endpoints/${encodeURIComponent(endpointEdit.id)}`, undefined, "DELETE"); await reload(); setEndpointEdit(null); setInspect(""); })} />}
    {endpoints.find((e) => e.id === inspect) && <EndpointConnection key={`endpoint-connection-${inspect}`} endpoint={endpoints.find((e) => e.id === inspect)!} base={base} call={call} />}
    <section className="pw-panel" aria-labelledby="policy-heading"><div className="pw-heading"><div><h3 id="policy-heading">Reusable policies</h3><p>Each saved version is immutable. Endpoints keep their assigned version until you explicitly reassign them.</p></div><button disabled={!loaded || busy} onClick={() => { setPolicyEdit("new"); setEndpointEdit(null); }}>Create policy</button></div>
      <ul className="pw-list">{policies.map((policy) => <li key={policy.policy_version_id}><div><h4>{policy.name} · v{policy.version}</h4><p>{policy.language} · {policy.mode} · {endpoints.filter((e) => e.enabled && e.policy_version_id === policy.policy_version_id).length} endpoints</p></div><button aria-label={`New version of ${policy.name} v${policy.version}`} disabled={busy} onClick={() => { setPolicyEdit(policy); setEndpointEdit(null); }}>New version</button></li>)}</ul>
    </section>
    {policyEdit && <PolicyForm template={policies.find((p) => p.policy_id === project.default_policy_id) ?? policies[0]} key={`policy-form-${policyEdit === "new" ? "new" : policyEdit.policy_version_id}`} policy={policyEdit === "new" ? undefined : policyEdit} endpoints={endpoints} hosted={hosted} busy={busy} onCancel={() => setPolicyEdit(null)} onSave={(body) => action(async () => { await call(policyEdit === "new" ? `${base}/policies` : `${base}/policies/${encodeURIComponent(policyEdit.policy_id)}`, body, policyEdit === "new" ? "POST" : "PUT"); await reload(); setPolicyEdit(null); })} />}
  </div>;
}

function EndpointForm({ endpoint, policies, busy, hosted, onSave, onCancel, onDisable }: { endpoint?: Endpoint; policies: PolicyVersion[]; busy: boolean; hosted: boolean; onSave: (body: unknown) => Promise<void>; onCancel: () => void; onDisable?: () => Promise<void> }) {
  const [name, setName] = useState(endpoint?.name ?? "");
  const [provider, setProvider] = useState(endpoint?.provider ?? "openai");
  const [model, setModel] = useState(endpoint?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(endpoint?.base_url ?? "");
  const [secret, setSecret] = useState("");
  const [policyId, setPolicyId] = useState(endpoint?.policy_version_id ?? "");
  const [reviewed, setReviewed] = useState(false);
  const [disableReview, setDisableReview] = useState(false);
  const [reenable, setReenable] = useState(false);
  const changed = Boolean(endpoint && endpoint.policy_version_id !== policyId);
  const selected = policies.find((p) => p.policy_version_id === policyId);
  const requiresCredential = provider !== "sponsored" && (!endpoint?.credential_configured || endpoint.provider !== provider);
  return <form className="pw-panel pw-stack" aria-label={endpoint ? "Edit endpoint" : "Create endpoint"} onSubmit={(e) => { e.preventDefault(); const apiKey = secret; setSecret(""); void onSave({ name, provider, model, policy_version_id: policyId, enabled: endpoint ? endpoint.enabled || reenable : true, ...(provider === "custom" ? { base_url: baseUrl } : {}), ...(apiKey ? { api_key: apiKey } : {}) }); }}>
    <h3>{endpoint ? `Edit ${endpoint.name}` : "Create gateway endpoint"}</h3>
    <fieldset disabled={busy} className="pw-fields"><label>Endpoint name<input required maxLength={64} value={name} onChange={(e) => setName(e.target.value)} /></label><label>Provider<select value={provider} onChange={(e) => { setProvider(e.target.value); setSecret(""); }}>{["meta", "openai", "fireworks", "openrouter", "custom", ...(hosted ? ["sponsored"] : [])].map((value) => <option key={value} value={value}>{value === "sponsored" ? "Sponsored Meta (subject to allowance)" : value}</option>)}</select></label>
      {provider === "custom" && <label>Upstream base URL<input required type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" /><small>Use a public HTTPS endpoint for hosted deployments.</small></label>}
      <label>Model ID<input required maxLength={200} value={model} onChange={(e) => setModel(e.target.value)} placeholder="Provider’s exact model ID" /></label>
      {provider !== "sponsored" && <label>{requiresCredential ? "Provider API key" : "Replace provider API key (optional)"}<input aria-label={requiresCredential ? "Provider API key" : "Replace provider API key (optional)"} type="password" required={requiresCredential} autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} /><small>{endpoint?.credential_configured ? "A credential is configured. Its value cannot be retrieved." : "The credential is sent to the guard and never saved in browser storage."}</small></label>}
      <label>Policy version<select required value={policyId} onChange={(e) => { setPolicyId(e.target.value); setReviewed(false); }}><option value="" disabled>Choose a policy version</option>{policies.map((policy) => <option key={policy.policy_version_id} value={policy.policy_version_id}>{policy.name} · v{policy.version}</option>)}</select></label>
    </fieldset>
    {selected && <p className="pw-note">{selected.language} · {selected.mode}. {Object.values(selected.entity_policies).filter((p) => p === "keep").length} entity types kept in place. Fail-closed processing is always enforced.</p>}
    {endpoint && !endpoint.enabled && <div className="pw-review"><p>This endpoint is disabled. Its revoked keys will stay revoked.</p><label className="pw-check"><input type="checkbox" checked={reenable} onChange={(e) => setReenable(e.target.checked)} />Re-enable this endpoint; issue a new integration key afterward</label></div>}
    {changed && <div className="pw-review"><p>Applying this version changes future requests through <strong>{endpoint!.name}</strong>. Other endpoints keep their versions. Already admitted requests finish with their original policy.</p><label className="pw-check"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />Apply {selected?.name} v{selected?.version} to this endpoint</label></div>}
    <div className="pw-actions"><button className="pw-primary" type="submit" disabled={busy || !policyId || (changed && !reviewed)}>{busy ? "Saving…" : endpoint ? "Save endpoint" : "Create endpoint"}</button><button type="button" disabled={busy} onClick={onCancel}>Cancel</button>{onDisable && endpoint?.enabled && <button type="button" disabled={busy} onClick={() => setDisableReview(true)}>Disable endpoint…</button>}</div>
    {disableReview && <div className="pw-review"><p>Disable {endpoint?.name} and revoke all its integration keys? Future requests will be refused.</p><div className="pw-actions"><button type="button" disabled={busy} onClick={() => void onDisable?.()}>Disable and revoke keys</button><button type="button" disabled={busy} onClick={() => setDisableReview(false)}>Keep endpoint</button></div></div>}
  </form>;
}

function PolicyForm({ policy, template, endpoints, hosted, busy, onSave, onCancel }: { policy?: PolicyVersion; template?: PolicyVersion; endpoints: Endpoint[]; hosted: boolean; busy: boolean; onSave: (body: unknown) => Promise<void>; onCancel: () => void }) {
  const [name, setName] = useState(policy?.name ?? "");
  const [entities, setEntities] = useState({ ...(policy?.entity_policies ?? template?.entity_policies ?? defaults) });
  const [language, setLanguage] = useState(policy?.language ?? template?.language ?? "hu");
  const [mode, setMode] = useState(hosted ? "fast" : policy?.mode ?? template?.mode ?? "fast");
  const affected = endpoints.filter((e) => e.enabled && e.policy_id === policy?.policy_id);
  return <form className="pw-panel pw-stack" aria-label="Policy editor" onSubmit={(e) => { e.preventDefault(); void onSave({ name, entity_policies: entities, language, mode }); }}>
    <h3>{policy ? `New version of ${policy.name}` : "Create policy"}</h3>
    <p>Mask replaces detected values with reversible placeholders. Keep sends them unchanged. Block refuses the entire request when that type is detected.</p>
    <fieldset disabled={busy} className="pw-fields"><label>Policy name<input required value={name} maxLength={64} onChange={(e) => setName(e.target.value)} /></label><label>Language<select value={language} onChange={(e) => setLanguage(e.target.value)}><option value="hu">Hungarian</option><option value="en">English</option><option value="de">German</option></select></label>{!hosted && <label>Detection mode<select value={mode} onChange={(e) => setMode(e.target.value)}><option value="fast">Fast</option><option value="audit">Audit (requires server support)</option></select></label>}
    {TEXT_ENTITY_TYPES.map((type) => <label key={type}>{ENTITY_META[type].label}<select value={entities[type]} onChange={(e) => setEntities((prev) => ({ ...prev, [type]: e.target.value as Policy }))}><option value="mask">Mask</option><option value="keep">Keep</option><option value="block">Block request</option></select></label>)}</fieldset>
    <div className="pw-review"><p>{policy ? "Saving creates a new version. No endpoint changes automatically." : "The new policy is available to endpoints in this project."}</p>{policy && <><p>Endpoints using this policy family: {affected.length ? affected.map((e) => `${e.name} (v${e.policy_version})`).join(", ") : "none"}.</p><p>To apply the saved version, edit an endpoint and review its policy assignment.</p></>}</div>
    <div className="pw-actions"><button className="pw-primary" type="submit" disabled={busy}>{busy ? "Saving…" : policy ? "Save new version" : "Save policy"}</button><button type="button" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </form>;
}

function EndpointConnection({ endpoint, base, call }: { endpoint: Endpoint; base: string; call: Requester }) {
  const [keys, setKeys] = useState<EndpointKey[]>([]);
  const [secret, setSecret] = useState<{ id: string; key: string } | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const keyPath = `${base}/endpoints/${encodeURIComponent(endpoint.id)}/keys`;
  useEffect(() => { let active = true; call<{ keys: EndpointKey[] }>(keyPath).then((data) => { if (!Array.isArray(data.keys)) throw new Error("Invalid keys"); if (active) setKeys(data.keys); }).catch((e: unknown) => { if (active) setError(recovery(e)); }); return () => { active = false; }; }, [call, keyPath]);
  async function action(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (e) { setError(recovery(e)); } finally { setBusy(false); } }
  const url = `${globalThis.location.origin}${endpoint.base_path}`;
  const snippet = `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(url)},\n    api_key=os.environ["PII_GUARD_ENDPOINT_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(endpoint.model)},\n    messages=[{"role": "user", "content": "Hello, Robin Example."}],\n)`;
  function copy(value: string, label: string) { void navigator.clipboard.writeText(value).then(() => setCopied(`${label} copied`)).catch(() => setCopied("Copy failed. Select the text and copy it manually.")); }
  return <section className="pw-panel pw-stack" aria-label={`Connect ${endpoint.name}`}><h3>Connect {endpoint.name}</h3><p>Keys authorize only this endpoint. Provider credentials are managed by the guard.</p><label>OpenAI-compatible base URL<input readOnly value={url} /></label><div className="pw-actions"><button onClick={() => copy(url, "URL")}>Copy URL</button><button onClick={() => copy(snippet, "Snippet")}>Copy Python snippet</button></div><pre>{snippet}</pre><p role="status">{copied}</p>
    {error && <p role="alert" className="pw-error">{error}</p>}
    <form className="pw-inline" onSubmit={(e) => { e.preventDefault(); setSecret(null); void action(async () => { const created = await call<EndpointKey & { key: string }>(keyPath, { name }); setSecret({ id: created.id, key: created.key }); setKeys((prev) => [...prev, { id: created.id, name: created.name, created_at: created.created_at }]); setName(""); }); }}><label>Integration key name<input required maxLength={64} value={name} onChange={(e) => setName(e.target.value)} /></label><button type="submit" disabled={busy || !name.trim() || !endpoint.enabled}>{busy ? "Working…" : "Create endpoint key"}</button></form>
    {secret && <div className="pw-review pw-stack"><p>Copy this key now. It is shown only once.</p><code className="pw-secret">{secret.key}</code><div className="pw-actions"><button onClick={() => copy(secret.key, "Key")}>Copy key</button><button onClick={() => { setSecret(null); setCopied(""); }}>Dismiss key</button></div></div>}
    <ul className="pw-list">{keys.map((key) => <li key={key.id}><div><h4>{key.name}</h4><p>{key.revoked_at ? "Revoked" : "Active"} · {new Date(key.created_at).toLocaleString()}</p></div>{!key.revoked_at && <button disabled={busy} onClick={() => void action(async () => { await call(`${keyPath}/${encodeURIComponent(key.id)}`, undefined, "DELETE"); setKeys((prev) => prev.filter((k) => k.id !== key.id)); if (secret?.id === key.id) setSecret(null); })}>Revoke {key.name}</button>}</li>)}</ul>
  </section>;
}
