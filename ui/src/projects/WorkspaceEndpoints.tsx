import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { ApiError } from "../api/http";
import { Badge, Button, Card, Checkbox, ConfirmAction, Field, Input, Notice, Select } from "../components/ui";
import type { Requester } from "../hosted/api";
import { useHostedSession } from "../hosted/session";
import { type Endpoint, type EndpointModels, type EndpointModelsQuery, type PolicyVersion } from "./api";
import { EndpointConnection } from "./WorkspacePolicy";

export { EndpointConnection };

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
const PANEL = "mt-3 min-w-0";
const LIST = "divide-y divide-line";
const ITEM = "py-3 first:pt-0 last:pb-0";
const ROW_LINE = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2";
const REVIEW = "rounded-lg bg-surface-2 p-3 text-sm text-ink sm:p-4";

export type Notified = { area: "endpoints" | "policies"; text: string; endpointId?: string } | null;
export interface EndpointBody {
  name: string;
  provider: string;
  model: string | null;
  policy_version_id: string;
  enabled: boolean;
  base_url?: string;
  api_key?: string;
}

function latestVersions(policies: PolicyVersion[]): Map<string, number> {
  const latest = new Map<string, number>();
  for (const p of policies) latest.set(p.policy_id, Math.max(latest.get(p.policy_id) ?? 0, p.version));
  return latest;
}

function useEscapeGuard(onCancel: () => void, busy: boolean) {
  const [touched, setTouched] = useState(false);
  const [asking, setAsking] = useState(false);
  const keepRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (asking) keepRef.current?.focus();
  }, [asking]);
  const keep = () => {
    setAsking(false);
    const back = returnTo.current;
    requestAnimationFrame(() => back?.focus());
  };
  const onKeyDown = (e: { key: string; defaultPrevented: boolean; preventDefault: () => void }) => {
    if (e.key !== "Escape" || e.defaultPrevented || busy) return;
    e.preventDefault();
    if (asking) return keep();
    if (!touched) return onCancel();
    returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setAsking(true);
  };
  const prompt = asking ? (
    <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm">
      <p className="w-full font-medium text-warn sm:w-auto sm:flex-1">Discard your changes?</p>
      <Button size="sm" variant="danger" onClick={onCancel}>Discard changes</Button>
      <Button size="sm" ref={keepRef} onClick={keep}>Keep editing</Button>
    </div>
  ) : null;
  return { onKeyDown, onChange: () => setTouched(true), prompt };
}

function useFocusOnOpen(id: string) {
  useLayoutEffect(() => {
    const heading = document.getElementById(id);
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView?.({ block: "nearest" });
  }, [id]);
}

interface EndpointRowActionsProps {
  endpoint: Endpoint;
  newer: PolicyVersion | undefined;
  busy: boolean;
  inspectOpen: boolean;
  onApplyLatest: (endpoint: Endpoint) => void;
  onDelete: (endpoint: Endpoint) => void;
  onToggleInspect: (id: string) => void;
  onOpenEdit: (endpoint: Endpoint) => void;
  onRegisterEditRef: (id: string, el: HTMLButtonElement | null) => void;
}

interface EndpointRowProps extends Omit<EndpointRowActionsProps, "inspectOpen"> {
  policies: PolicyVersion[];
  inspect: string;
  isEditing: boolean;
  endpointForm: ReactNode;
  base: string;
  call: Requester;
  hosted: boolean;
}

function EndpointRowActions({ endpoint, newer, busy, inspectOpen, onApplyLatest, onDelete, onToggleInspect, onOpenEdit, onRegisterEditRef }: EndpointRowActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 sm:max-w-[60%] sm:shrink-0 sm:justify-end">
      {endpoint.enabled && newer && (
        <ConfirmAction
          size="sm"
          trigger={`Apply v${newer.version}`}
          triggerLabel={`Apply v${newer.version} to ${endpoint.name}`}
          title={`Apply ${newer.name} v${newer.version} to '${endpoint.name}'?`}
          body={`The next request through it uses v${newer.version} instead of v${endpoint.policy_version}. Other endpoints keep their versions.`}
          confirm={`Apply v${newer.version}`}
          busy={busy}
          onConfirm={() => onApplyLatest(endpoint)}
        />
      )}
      {!endpoint.enabled && (
        <ConfirmAction
          size="sm"
          trigger="Delete"
          triggerLabel={`Delete ${endpoint.name}`}
          title={`Delete endpoint '${endpoint.name}'?`}
          body="Its configuration is removed; its endpoint keys are already revoked."
          confirm="Delete endpoint"
          busy={busy}
          onConfirm={() => onDelete(endpoint)}
        />
      )}
      {endpoint.enabled && (
        <Button size="sm" aria-expanded={inspectOpen} aria-label={`Connect & keys for ${endpoint.name}`} onClick={() => onToggleInspect(endpoint.id)}>
          Connect & keys
        </Button>
      )}
      <Button size="sm" busy={busy} aria-label={`Edit ${endpoint.name}`} ref={(el) => onRegisterEditRef(endpoint.id, el)} onClick={() => onOpenEdit(endpoint)}>
        Edit
      </Button>
    </div>
  );
}

function EndpointRow(props: EndpointRowProps) {
  const { endpoint, policies, newer, busy, inspect, isEditing, endpointForm, base, call, hosted } = props;
  const policyName = policies.find((p) => p.policy_version_id === endpoint.policy_version_id)?.name ?? "Policy";
  const inspectOpen = inspect === endpoint.id;
  return (
    <li className={ITEM}>
      <div className={`${ROW_LINE} sm:flex-nowrap`}>
        <div className="min-w-0 sm:flex-1">
          <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-ink break-words">
            {endpoint.name}
            {!endpoint.enabled && <Badge>Disabled</Badge>}
          </h3>
          <p className="mt-0.5 text-sm text-muted break-words">
            {providerLabel(endpoint.provider)} · {endpoint.model ? <span className="font-mono text-xs">{endpoint.model}</span> : "Client chooses the model"}
          </p>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            {policyName} · v{endpoint.policy_version}
            {endpoint.enabled && newer && <Badge>v{newer.version} available</Badge>}
          </p>
        </div>
        <EndpointRowActions
          endpoint={endpoint}
          newer={newer}
          busy={busy}
          inspectOpen={inspectOpen}
          onApplyLatest={props.onApplyLatest}
          onDelete={props.onDelete}
          onToggleInspect={props.onToggleInspect}
          onOpenEdit={props.onOpenEdit}
          onRegisterEditRef={props.onRegisterEditRef}
        />
      </div>
      {isEditing && <div className={PANEL}>{endpointForm}</div>}
      {inspectOpen && (
        <div className={PANEL}>
          <EndpointConnection key={`endpoint-connection-${inspect}`} endpoint={endpoint} base={base} call={call} hosted={hosted} />
        </div>
      )}
    </li>
  );
}

export interface EndpointsSectionProps {
  endpoints: Endpoint[];
  policies: PolicyVersion[];
  loaded: boolean;
  busy: boolean;
  hosted: boolean;
  base: string;
  call: Requester;
  notice: Notified;
  endpointEdit: Endpoint | "new" | null;
  inspect: string;
  createEndpointRef: RefObject<HTMLButtonElement | null>;
  editRefs: RefObject<Map<string, HTMLButtonElement>>;
  endpointForm: ReactNode;
  onOpenNew: () => void;
  onOpenEdit: (endpoint: Endpoint) => void;
  onToggleInspect: (id: string) => void;
  onInspectFromNotice: (id: string) => void;
  onApplyLatest: (endpoint: Endpoint) => void;
  onDelete: (endpoint: Endpoint) => void;
}

function EndpointNoticeBanner({ notice, endpoints, onInspect }: { notice: Notified; endpoints: Endpoint[]; onInspect: (id: string) => void }) {
  if (notice?.area !== "endpoints") return null;
  const targetId = notice.endpointId && endpoints.some((e) => e.id === notice.endpointId) ? notice.endpointId : undefined;
  return (
    <Notice tone="success" live className="mb-4" action={targetId ? <Button size="sm" variant="primary" onClick={() => onInspect(targetId)}>Create an endpoint key</Button> : undefined}>
      {notice.text}
    </Notice>
  );
}

function findNewerPolicyVersion(endpoint: Endpoint, policies: PolicyVersion[], latest: Map<string, number>): PolicyVersion | undefined {
  const v = latest.get(endpoint.policy_id) ?? 0;
  return v > endpoint.policy_version ? policies.find((p) => p.policy_id === endpoint.policy_id && p.version === v) : undefined;
}

export function EndpointsSection(props: EndpointsSectionProps) {
  const { endpoints, policies, loaded, busy, hosted, base, call, notice, endpointEdit, inspect, createEndpointRef, editRefs, endpointForm } = props;
  const noPolicyHint = useId();
  const latest = latestVersions(policies);
  const noPoliciesYet = loaded && !policies.length;
  const orderedEndpoints = [...endpoints.filter((e) => e.enabled), ...endpoints.filter((e) => !e.enabled)];
  const registerEditRef = (id: string, el: HTMLButtonElement | null) => {
    if (el) editRefs.current.set(id, el);
    else editRefs.current.delete(id);
  };

  return (
    <>
      <Card
        title="Gateway endpoints"
        titleId={ENDPOINTS_TITLE}
        subtitle="One upstream and pinned policy version per endpoint, with a pinned model or the client’s own."
        actions={
          <Button ref={createEndpointRef} busy={busy} disabled={!loaded || !policies.length || endpointEdit === "new"} aria-describedby={noPoliciesYet ? noPolicyHint : undefined} onClick={props.onOpenNew}>
            Create endpoint
          </Button>
        }
      >
        {noPoliciesYet && <p id={noPolicyHint} className="mb-3 text-xs text-muted">Create a policy first: every endpoint pins one policy version.</p>}
        <EndpointNoticeBanner notice={notice} endpoints={endpoints} onInspect={props.onInspectFromNotice} />
        {loaded && !endpoints.length && <p className="text-sm text-muted">No endpoints yet. Create one, then create an endpoint key to connect your application.</p>}
        {endpoints.length > 0 && (
          <ul className={LIST}>
            {orderedEndpoints.map((endpoint) => (
              <EndpointRow
                key={endpoint.id}
                endpoint={endpoint}
                policies={policies}
                newer={findNewerPolicyVersion(endpoint, policies, latest)}
                busy={busy}
                inspect={inspect}
                isEditing={endpointEdit !== "new" && endpointEdit?.id === endpoint.id}
                endpointForm={endpointForm}
                base={base}
                call={call}
                hosted={hosted}
                onApplyLatest={props.onApplyLatest}
                onDelete={props.onDelete}
                onToggleInspect={props.onToggleInspect}
                onOpenEdit={props.onOpenEdit}
                onRegisterEditRef={registerEditRef}
              />
            ))}
          </ul>
        )}
      </Card>
      {endpointEdit === "new" && endpointForm}
    </>
  );
}

const OTHER_MODEL = "other model";

function useSponsoredAllowedModels(isSponsored: boolean, catalog: (query: EndpointModelsQuery) => Promise<EndpointModels>, onDefaultModel: (updater: (current: string) => string) => void): string[] | "failed" | null {
  const [allowed, setAllowed] = useState<string[] | "failed" | null>(null);
  useEffect(() => {
    if (!isSponsored) return;
    let active = true;
    catalog({ provider: "sponsored" })
      .then((data) => {
        if (!active) return;
        const list = Array.isArray(data.models) ? data.models : [];
        setAllowed(list);
        onDefaultModel((current) => (current && list.includes(current) ? current : (list[0] ?? "")));
      })
      .catch(() => {
        if (active) setAllowed("failed");
      });
    return () => {
      active = false;
    };
  }, [isSponsored, catalog, onDefaultModel]);
  return allowed;
}

function SponsoredModelField({ allowed, model, onModel }: { allowed: string[] | "failed" | null; model: string; onModel: (m: string) => void }) {
  const hint = allowed === "failed" ? "The allowed models could not be loaded. Enter one the operator allows." : "Requests without your own key use one of the allowed models.";
  return (
    <Field label="Model" required hint={hint}>
      {Array.isArray(allowed) && allowed.length ? (
        <Select value={model} onChange={(e) => onModel(e.target.value)}>
          {allowed.map((m) => <option key={m} value={m}>{m}</option>)}
        </Select>
      ) : (
        <Input maxLength={256} value={model} onChange={(e) => onModel(e.target.value)} placeholder={allowed === null ? "Loading allowed models…" : "muse-spark-1.3"} />
      )}
    </Field>
  );
}

function modelFieldHint(provider: string, modelsState: "idle" | "loading" | "failed" | "rejected", models: string[] | null, listing: boolean): string {
  const label = providerLabel(provider);
  if (modelsState === "rejected") return `${label} refused the API key. Check the API key, then load again, or type a model ID.`;
  if (modelsState === "failed") return `${label} did not list its models. Type a model ID, or leave it empty.`;
  if (models && !models.length) return `${label} listed no models. Type a model ID, or leave it empty.`;
  if (listing) return "Pick ‘Client chooses’ to let Codex or Muse Code send their own model.";
  return "Leave empty to let your client choose, e.g. Codex or Muse Code.";
}

function ModelControl({ listing, models, model, onModel, onTyping }: { listing: boolean; models: string[] | null; model: string; onModel: (m: string) => void; onTyping: (v: boolean) => void }) {
  if (!listing || !models) return <Input maxLength={256} value={model} onChange={(e) => onModel(e.target.value)} placeholder="Client chooses" />;
  const options = [...(model && !models.includes(model) ? [model] : []), ...models];
  return (
    <Select value={model} onChange={(e) => (e.target.value === OTHER_MODEL ? onTyping(true) : onModel(e.target.value))}>
      <option value="">Client chooses (no pinned model)</option>
      {options.map((m) => <option key={m} value={m}>{m}</option>)}
      <option value={OTHER_MODEL}>Other model ID…</option>
    </Select>
  );
}

function loadModelsButtonText(provider: string, modelsState: "idle" | "loading" | "failed" | "rejected", hasModels: boolean): string {
  if (modelsState === "loading") return "Loading models…";
  if (hasModels) return "Reload models";
  return provider === "custom" ? "Load models from this endpoint" : `Load models from ${providerLabel(provider)}`;
}

interface ProviderModelFieldProps {
  provider: string;
  model: string;
  onModel: (m: string) => void;
  models: string[] | null;
  modelsState: "idle" | "loading" | "failed" | "rejected";
  typing: boolean;
  onTyping: (v: boolean) => void;
  canLoadModels: boolean;
  baseUrl: string;
  onLoadModels: () => void;
}

function ProviderModelField({ provider, model, onModel, models, modelsState, typing, onTyping, canLoadModels, baseUrl, onLoadModels }: ProviderModelFieldProps) {
  const hasModels = Boolean(models && models.length);
  const listing = hasModels && !typing;
  const loadBlocked = provider === "custom" && !baseUrl ? "Enter the base URL and provider API key to load models." : "Enter the provider API key to load models.";
  return (
    <Field label="Model (optional)" hint={modelFieldHint(provider, modelsState, models, listing)}>
      <ModelControl listing={listing} models={models} model={model} onModel={onModel} onTyping={onTyping} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          className="max-sm:h-11"
          busy={modelsState === "loading"}
          disabled={!canLoadModels}
          onClick={() => {
            onTyping(false);
            onLoadModels();
          }}
        >
          {loadModelsButtonText(provider, modelsState, Boolean(models))}
        </Button>
        {hasModels && typing && (
          <Button size="sm" variant="ghost" className="max-sm:h-11" onClick={() => onTyping(false)}>Choose from the list</Button>
        )}
        {!canLoadModels && <p className="text-xs text-muted">{loadBlocked}</p>}
      </div>
    </Field>
  );
}

function credentialFieldHint(credentialConfigured: boolean | undefined, hasConnectedProvider: boolean, provider: string): string {
  if (credentialConfigured) return "A credential is configured. Its value cannot be retrieved.";
  if (hasConnectedProvider) {
    return `An endpoint keeps its own key: your ${providerLabel(provider)} connection on Connect is for the Playground only, so enter the key here too. Never saved in browser storage.`;
  }
  return "The credential is sent to the guard and never saved in browser storage.";
}

function hasStoredEndpointKey(endpoint: Endpoint | undefined, provider: string, baseUrl: string): boolean {
  if (!endpoint?.credential_configured || endpoint.provider !== provider) return false;
  return provider !== "custom" || endpoint.base_url === baseUrl;
}

function canFetchProviderModels(isSponsored: boolean, secret: string, storedKey: boolean, provider: string, baseUrl: string): boolean {
  if (isSponsored) return false;
  if (!secret && !storedKey) return false;
  return provider !== "custom" || Boolean(baseUrl);
}

function buildModelsQuery(provider: string, baseUrl: string, secret: string, endpoint?: Endpoint): EndpointModelsQuery {
  return {
    provider,
    ...(provider === "custom" ? { base_url: baseUrl } : {}),
    ...(secret ? { api_key: secret } : endpoint ? { endpoint_id: endpoint.id } : {}),
  };
}

function endpointBlockedReason(isSponsored: boolean, model: string, policyId: string, changed: boolean, reviewed: boolean): string {
  if (isSponsored && !model) return "Choose a model to save.";
  if (!policyId) return "Choose a policy version to save.";
  if (changed && !reviewed) return "Confirm the policy change below to save.";
  return "";
}

function buildEndpointSaveBody(name: string, provider: string, model: string, policyId: string, endpoint: Endpoint | undefined, reenable: boolean, baseUrl: string, apiKey: string): EndpointBody {
  return {
    name,
    provider,
    model: model.trim() || null,
    policy_version_id: policyId,
    enabled: endpoint ? endpoint.enabled || reenable : true,
    ...(provider === "custom" ? { base_url: baseUrl } : {}),
    ...(apiKey ? { api_key: apiKey } : {}),
  };
}

interface EndpointReviewPanelsProps {
  endpoint?: Endpoint;
  busy: boolean;
  reenable: boolean;
  onReenable: (v: boolean) => void;
  changed: boolean;
  reviewed: boolean;
  onReviewed: (v: boolean) => void;
  selectedPolicy?: PolicyVersion;
}

function EndpointReviewPanels({ endpoint, busy, reenable, onReenable, changed, reviewed, onReviewed, selectedPolicy }: EndpointReviewPanelsProps) {
  return (
    <>
      {selectedPolicy && (
        <p className="text-sm text-muted">
          {describePolicy(selectedPolicy)}. {plural(Object.values(selectedPolicy.entity_policies).filter((p) => p === "keep").length, "entity type")} kept in place. Fail-closed processing is always enforced.
        </p>
      )}
      {endpoint && !endpoint.enabled && (
        <div className={REVIEW}>
          <p>This endpoint is disabled. Its revoked endpoint keys stay revoked.</p>
          <Checkbox className="mt-3" checked={reenable} disabled={busy} onChange={(e) => onReenable(e.target.checked)} label="Re-enable this endpoint; create a new endpoint key afterward" />
        </div>
      )}
      {changed && endpoint && (
        <div className={REVIEW}>
          <p>
            Applying this version changes future requests through <strong className="font-medium">{endpoint.name}</strong>. Other endpoints keep their versions. Already admitted requests finish with their original policy.
          </p>
          <Checkbox className="mt-3" checked={reviewed} disabled={busy} onChange={(e) => onReviewed(e.target.checked)} label={`Apply ${selectedPolicy?.name} v${selectedPolicy?.version} to this endpoint`} />
        </div>
      )}
    </>
  );
}

interface EndpointFormActionsProps {
  endpoint?: Endpoint;
  busy: boolean;
  blockedReason: string;
  onCancel: () => void;
  onDisable?: () => Promise<void>;
}

function EndpointFormActions({ endpoint, busy, blockedReason, onCancel, onDisable }: EndpointFormActionsProps) {
  const submitLabel = busy ? "Saving…" : endpoint ? "Save endpoint" : "Create endpoint";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="primary" type="submit" busy={busy} disabled={!busy && Boolean(blockedReason)}>{submitLabel}</Button>
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
  );
}

export interface EndpointFormProps {
  endpoint?: Endpoint;
  policies: PolicyVersion[];
  busy: boolean;
  hosted: boolean;
  catalog: (query: EndpointModelsQuery) => Promise<EndpointModels>;
  onSave: (body: EndpointBody) => Promise<void>;
  onCancel: () => void;
  onDisable?: () => Promise<void>;
}

function initialProviderOf(endpoint: Endpoint | undefined, hosted: boolean, sponsoredLimit: unknown): string {
  if (endpoint) return endpoint.provider;
  return hosted && sponsoredLimit !== false ? "sponsored" : "openai";
}

function initialPolicyIdOf(endpoint: Endpoint | undefined, policies: PolicyVersion[]): string {
  if (endpoint) return endpoint.policy_version_id;
  return policies.length === 1 ? policies[0]!.policy_version_id : "";
}

function requiresProviderCredential(isSponsored: boolean, endpoint: Endpoint | undefined, provider: string): boolean {
  if (isSponsored) return false;
  return !endpoint?.credential_configured || endpoint.provider !== provider;
}

function useModelCatalogState(catalog: (query: EndpointModelsQuery) => Promise<EndpointModels>) {
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsState, setModelsState] = useState<"idle" | "loading" | "failed" | "rejected">("idle");
  const [typing, setTyping] = useState(false);
  const resetCatalog = () => {
    setModels(null);
    setModelsState("idle");
    setTyping(false);
  };
  const loadModels = async (query: EndpointModelsQuery) => {
    setModelsState("loading");
    try {
      setModels((await catalog(query)).models);
      setModelsState("idle");
    } catch (e) {
      setModels(null);
      setModelsState(e instanceof ApiError && e.code === "upstream_credential_rejected" ? "rejected" : "failed");
    }
  };
  return { models, modelsState, typing, setTyping, resetCatalog, loadModels };
}

function PolicyVersionSelectField({ endpoint, policies, policyId, onSelectPolicy }: { endpoint?: Endpoint; policies: PolicyVersion[]; policyId: string; onSelectPolicy: (id: string) => void }) {
  const latestOf = latestVersions(policies);
  const hint = policies.length === 1 && !endpoint ? "The project’s only policy version is selected." : "The endpoint keeps this version until you reassign it.";
  return (
    <Field label="Policy version" required hint={hint}>
      <Select value={policyId} onChange={(e) => onSelectPolicy(e.target.value)}>
        <option value="" disabled>Choose a policy version</option>
        {policies.map((policy) => (
          <option key={policy.policy_version_id} value={policy.policy_version_id}>
            {policy.name} · v{policy.version}{latestOf.get(policy.policy_id) === policy.version ? " (latest)" : ""}
          </option>
        ))}
      </Select>
    </Field>
  );
}

function resolveInitialEndpointDefaults(endpoint: Endpoint | undefined, hosted: boolean, session: ReturnType<typeof useHostedSession>, policies: PolicyVersion[]) {
  const sponsoredEnabled = session ? session.account.limits.sponsored_enabled : undefined;
  return {
    name: endpoint ? endpoint.name : "",
    provider: initialProviderOf(endpoint, hosted, sponsoredEnabled),
    model: endpoint?.model ? endpoint.model : "",
    baseUrl: endpoint?.base_url ? endpoint.base_url : "",
    policyId: initialPolicyIdOf(endpoint, policies),
  };
}

function hasSessionConnectionForProvider(session: ReturnType<typeof useHostedSession>, provider: string): boolean {
  if (!session) return false;
  return session.account.connections.some((c) => c.provider === provider);
}

function endpointCardMeta(endpoint: Endpoint | undefined) {
  if (endpoint) return { title: `Edit ${endpoint.name}`, subtitle: "Changes apply to future requests through this endpoint." };
  return { title: "Create endpoint", subtitle: "Clients reach the model through this endpoint with an endpoint key." };
}

export function EndpointForm({ endpoint, policies, busy, hosted, catalog, onSave, onCancel, onDisable }: EndpointFormProps) {
  const session = useHostedSession();
  const initial = resolveInitialEndpointDefaults(endpoint, hosted, session, policies);
  const [name, setName] = useState(initial.name);
  const [provider, setProvider] = useState(initial.provider);
  const hasConnected = hasSessionConnectionForProvider(session, provider);
  const [model, setModel] = useState(initial.model);
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl);
  const [secret, setSecret] = useState("");
  const { models, modelsState, typing, setTyping, resetCatalog, loadModels } = useModelCatalogState(catalog);
  const isSponsored = provider === "sponsored";
  const storedKey = hasStoredEndpointKey(endpoint, provider, baseUrl);
  const canLoadModels = canFetchProviderModels(isSponsored, secret, storedKey, provider, baseUrl);
  const allowed = useSponsoredAllowedModels(isSponsored, catalog, setModel);

  const chooseProvider = (next: string) => {
    setProvider(next);
    setSecret("");
    resetCatalog();
    if (next === "sponsored" || isSponsored) setModel("");
  };
  const [policyId, setPolicyId] = useState(initial.policyId);
  const [reviewed, setReviewed] = useState(false);
  const [reenable, setReenable] = useState(false);
  const titleId = useId();
  useFocusOnOpen(titleId);
  const changed = Boolean(endpoint && endpoint.policy_version_id !== policyId);
  const selected = policies.find((p) => p.policy_version_id === policyId);
  const requiresCredential = requiresProviderCredential(isSponsored, endpoint, provider);
  const keyLabel = requiresCredential ? "Provider API key" : "Replace provider API key (optional)";
  const guard = useEscapeGuard(onCancel, busy);
  const blockedReason = endpointBlockedReason(isSponsored, model, policyId, changed, reviewed);
  const providerChoices = hosted ? ["sponsored", "meta", "openai", "fireworks", "openrouter", "custom"] : ["meta", "openai", "fireworks", "openrouter", "custom"];
  const cardMeta = endpointCardMeta(endpoint);

  return (
    <div onKeyDown={guard.onKeyDown}>
      <Card title={cardMeta.title} titleId={titleId} subtitle={cardMeta.subtitle}>
        <form
          aria-labelledby={titleId}
          className="space-y-4"
          onChange={guard.onChange}
          onSubmit={(e) => {
            e.preventDefault();
            const apiKey = secret;
            setSecret("");
            void onSave(buildEndpointSaveBody(name, provider, model, policyId, endpoint, reenable, baseUrl, apiKey));
          }}
        >
          <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-2">
            <Field label="Endpoint name" required hint="Shown in logs and in the project switcher.">
              <Input maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Provider" required>
              <Select value={provider} onChange={(e) => chooseProvider(e.target.value)}>
                {providerChoices.map((value) => <option key={value} value={value}>{providerLabel(value)}</option>)}
              </Select>
            </Field>
            {provider === "custom" && (
              <Field label="Upstream base URL" required hint="Use a public HTTPS endpoint for hosted deployments.">
                <Input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
              </Field>
            )}
            {isSponsored ? (
              <SponsoredModelField allowed={allowed} model={model} onModel={setModel} />
            ) : (
              <ProviderModelField provider={provider} model={model} onModel={setModel} models={models} modelsState={modelsState} typing={typing} onTyping={setTyping} canLoadModels={canLoadModels} baseUrl={baseUrl} onLoadModels={() => void loadModels(buildModelsQuery(provider, baseUrl, secret, endpoint))} />
            )}
            {!isSponsored && (
              <Field label={keyLabel} required={requiresCredential} hint={credentialFieldHint(endpoint?.credential_configured, hasConnected, provider)}>
                <Input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
              </Field>
            )}
            <PolicyVersionSelectField
              endpoint={endpoint}
              policies={policies}
              policyId={policyId}
              onSelectPolicy={(id) => {
                setPolicyId(id);
                setReviewed(false);
              }}
            />
          </fieldset>
          <EndpointReviewPanels endpoint={endpoint} busy={busy} reenable={reenable} onReenable={setReenable} changed={changed} reviewed={reviewed} onReviewed={setReviewed} selectedPolicy={selected} />
          {guard.prompt}
          <EndpointFormActions endpoint={endpoint} busy={busy} blockedReason={blockedReason} onCancel={onCancel} onDisable={onDisable} />
        </form>
      </Card>
    </div>
  );
}
