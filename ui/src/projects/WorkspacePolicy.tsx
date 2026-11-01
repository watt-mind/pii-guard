import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { ApiError } from "../api/http";
import { TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, type TextEntityType, type VisualEntityType } from "../api/types";
import { Announcer, Badge, Button, Card, ConfirmAction, Field, Input, Notice, SecretReveal, Select } from "../components/ui";
import { recovery, type Requester } from "../hosted/api";
import { ENTITY_META, type Policy } from "../lib/entities";
import { dateTime, relativeTime } from "../lib/time";
import { VISUAL_DETECTION_LABEL, exampleModel, type Endpoint, type EndpointKey, type PolicyVersion, type VisualDetection } from "./api";
import { setSelectedEndpoint } from "./selection";
import type { Notified } from "./WorkspaceEndpoints";

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

const defaults = Object.fromEntries(TEXT_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy])) as Record<TextEntityType, Policy>;
const visualDefaults = Object.fromEntries(VISUAL_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy === "keep" ? "keep" : "mask"])) as Record<
  VisualEntityType,
  "mask" | "keep"
>;

const LANGUAGE_LABEL: Record<string, string> = { hu: "Hungarian", en: "English", de: "German" };
const describePolicy = (policy: { language: string; mode: string }) => `${LANGUAGE_LABEL[policy.language] ?? policy.language} · ${policy.mode} mode`;
const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
const byId = (id: string) => () => document.getElementById(id);

const POLICIES_TITLE = "pw-policies-title";
const INLINE = "w-full basis-full pt-1";
const LIST = "divide-y divide-line";
const ITEM = "py-3 first:pt-0 last:pb-0";
const ROW_LINE = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2";
const ROW = `${ROW_LINE} ${ITEM}`;
const REVIEW = "rounded-lg bg-surface-2 p-3 text-sm text-ink sm:p-4";

export interface PolicyBody {
  name: string;
  entity_policies: Record<TextEntityType, Policy> & Record<VisualEntityType, "mask" | "keep">;
  language: string;
  mode: string;
  visual_detection: VisualDetection;
}

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

/** One row per policy family (LAB-1626): its latest version first, older versions behind it. */
function policyFamilies(policies: PolicyVersion[]): { latest: PolicyVersion; older: PolicyVersion[] }[] {
  const families = new Map<string, PolicyVersion[]>();
  for (const p of policies) families.set(p.policy_id, [...(families.get(p.policy_id) ?? []), p]);
  return [...families.values()].map((versions) => {
    const sorted = [...versions].sort((a, b) => b.version - a.version);
    return { latest: sorted[0]!, older: sorted.slice(1) };
  });
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

function listNames(items: { name: string }[]): string {
  if (items.length > 2) return `${items.length} endpoints`;
  return items.map((e) => `'${e.name}'`).join(" and ");
}

export interface PoliciesSectionProps {
  policies: PolicyVersion[];
  endpoints: Endpoint[];
  loaded: boolean;
  busy: boolean;
  notice: Notified;
  policyEdit: PolicyVersion | "new" | null;
  policyForm: ReactNode;
  createPolicyRef: RefObject<HTMLButtonElement | null>;
  versionRefs: RefObject<Map<string, HTMLButtonElement>>;
  onOpenPolicyForm: (next: PolicyVersion | "new") => void;
}

export function PoliciesSection({
  policies,
  endpoints,
  loaded,
  busy,
  notice,
  policyEdit,
  policyForm,
  createPolicyRef,
  versionRefs,
  onOpenPolicyForm,
}: PoliciesSectionProps) {
  const pinnedCount = (version: PolicyVersion) => endpoints.filter((e) => e.enabled && e.policy_version_id === version.policy_version_id).length;
  const familyCount = (policyId: string) => endpoints.filter((e) => e.enabled && e.policy_id === policyId).length;
  return (
    <>
      <Card
        title="Reusable policies"
        titleId={POLICIES_TITLE}
        subtitle="Each saved version is immutable. Endpoints keep their assigned version until you explicitly reassign them."
        actions={
          <Button ref={createPolicyRef} busy={busy} disabled={!loaded || policyEdit === "new"} onClick={() => onOpenPolicyForm("new")}>
            Create policy
          </Button>
        }
      >
        {notice?.area === "policies" && <Notice tone="success" live className="mb-4">{notice.text}</Notice>}
        {loaded && !policies.length && <p className="text-sm text-muted">No policies yet. Create one to choose what each endpoint masks, keeps or blocks.</p>}
        {policies.length > 0 && (
          <ul className={LIST}>
            {policyFamilies(policies).map(({ latest: policy, older }) => (
              <li key={policy.policy_id} className={ROW}>
                <div className="min-w-0">
                  <h3 className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-ink break-words">
                    {policy.name} · v{policy.version}
                    {older.length > 0 && <Badge tone="live">Latest</Badge>}
                  </h3>
                  <p className="mt-0.5 text-sm text-muted">
                    {describePolicy(policy)} · {plural(familyCount(policy.policy_id), "endpoint")}
                    {older.length > 0 && <> · {plural(older.length + 1, "version")}</>}
                  </p>
                </div>
                <Button
                  size="sm"
                  busy={busy}
                  aria-label={`New version of ${policy.name}`}
                  ref={(el) => {
                    if (el) versionRefs.current.set(policy.policy_version_id, el);
                    else versionRefs.current.delete(policy.policy_version_id);
                  }}
                  onClick={() => onOpenPolicyForm(policy)}
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
                          <span className="text-ink">v{v.version}</span> · {describePolicy(v)} · {plural(pinnedCount(v), "endpoint")}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {policyEdit === "new" && policyForm}
    </>
  );
}

function initialVisualPoliciesOf(start: PolicyVersion | undefined): Record<VisualEntityType, "mask" | "keep"> {
  return Object.fromEntries(
    VISUAL_ENTITY_TYPES.map((type) => {
      const saved = start?.entity_policies[type];
      return [type, saved === "keep" || saved === "mask" ? saved : visualDefaults[type]];
    }),
  ) as Record<VisualEntityType, "mask" | "keep">;
}

function visualDetectionHint(hosted: boolean, detection: VisualDetection): string {
  if (hosted) return "The hosted service detects on its own CPU only; SAM 3.1 needs a self-hosted install.";
  if (detection === "sam") {
    return "The original image is sent to Meta's API for signatures and stamps. Needs a SAM key on the server; a server set to on-device detection stays on-device.";
  }
  return "Faces, ID photos and signatures are found on the guard's CPU. Stamps cannot be detected on-device, so they can only be kept.";
}

function PolicyImagesFieldset({
  busy,
  hosted,
  detection,
  onDetection,
  visual,
  onVisualChange,
}: {
  busy: boolean;
  hosted: boolean;
  detection: VisualDetection;
  onDetection: (d: VisualDetection) => void;
  visual: Record<VisualEntityType, "mask" | "keep">;
  onVisualChange: (type: VisualEntityType, v: "mask" | "keep") => void;
}) {
  return (
    <fieldset disabled={busy} className="min-w-0">
      <legend className="mb-3 text-sm font-medium text-ink">Images</legend>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Detection" hint={visualDetectionHint(hosted, detection)}>
          <Select value={detection} onChange={(e) => onDetection(e.target.value as VisualDetection)}>
            <option value="local">{VISUAL_DETECTION_LABEL.local}</option>
            <option value="sam" disabled={hosted}>{VISUAL_DETECTION_LABEL.sam}</option>
          </Select>
        </Field>
        {VISUAL_ENTITY_TYPES.map((type) => (
          <Field key={type} label={ENTITY_META[type].label}>
            <Select value={visual[type]} onChange={(e) => onVisualChange(type, e.target.value as "mask" | "keep")}>
              <option value="mask">Mask</option>
              <option value="keep">Keep</option>
            </Select>
          </Field>
        ))}
      </div>
      {detection === "local" && visual.STAMP === "mask" && (
        <p role="alert" className="mt-2 text-sm text-warn">
          {hosted ? "Detection on the PII Guard server" : "On-device detection"} cannot find stamps, so every image would be refused. Keep stamps, or choose SAM 3.1.
        </p>
      )}
    </fieldset>
  );
}

function policyApplyHint(applyTo: Endpoint[], fromTune: Endpoint[]): string {
  if (!applyTo.length) return "";
  const pron = applyTo.length === 1 ? "it" : "them";
  const poss = applyTo.length === 1 ? "its" : "their";
  if (fromTune.length) {
    return ` Save and apply moves ${listNames(applyTo)} to the new version; Save only keeps ${pron} on ${poss} current version.`;
  }
  return ` Save new version keeps ${pron} on ${poss} current version; Save and apply asks before moving ${pron}.`;
}

function PolicyReviewSection({ policy, latest, affected, fromTune, applyTo }: { policy?: PolicyVersion; latest?: number; affected: Endpoint[]; fromTune: Endpoint[]; applyTo: Endpoint[] }) {
  const olderBase = Boolean(policy && latest !== undefined && latest > policy.version);
  const tuneNote = fromTune[0] ? `, the version '${fromTune[0].name}' uses` : "";
  return (
    <div className={REVIEW}>
      <p>
        {policy ? "Saving creates a new version." : "The new policy is available to endpoints in this project."}
        {olderBase && policy && latest !== undefined && (
          <>
            {" "}
            It starts from v{policy.version}
            {tuneNote}, not the latest v{latest}; v{latest + 1} gets these settings.
          </>
        )}
      </p>
      {policy && (
        <p className="mt-1">
          Endpoints using this policy: {affected.length ? affected.map((e) => `${e.name} (v${e.policy_version})`).join(", ") : "none"}.
          {policyApplyHint(applyTo, fromTune)}
        </p>
      )}
    </div>
  );
}

function policySubmitLabel(busy: boolean, policy: PolicyVersion | undefined, fromTuneCount: number, applyTo: Endpoint[]): string {
  if (busy) return "Saving…";
  if (!policy) return "Save policy";
  return fromTuneCount ? `Save and apply to ${listNames(applyTo)}` : "Save new version";
}

function policyConfirmTarget(applyTo: Endpoint[]): string {
  return applyTo.length === 1 && applyTo[0] ? `'${applyTo[0].name}'` : `${applyTo.length} endpoints`;
}

function PolicyFormActions({
  policy,
  busy,
  fromTune,
  applyTo,
  onSaveOnly,
  onSaveAndApply,
  onCancel,
}: {
  policy?: PolicyVersion;
  busy: boolean;
  fromTune: Endpoint[];
  applyTo: Endpoint[];
  onSaveOnly: () => void;
  onSaveAndApply: () => Promise<void>;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="primary" type="submit" busy={busy}>
        {policySubmitLabel(busy, policy, fromTune.length, applyTo)}
      </Button>
      {policy && fromTune.length > 0 && (
        <Button disabled={busy} onClick={onSaveOnly}>Save only</Button>
      )}
      {policy && !fromTune.length && applyTo.length > 0 && (
        <ConfirmAction
          trigger="Save and apply…"
          title={`Save and apply the new version to ${policyConfirmTarget(applyTo)}?`}
          body={`The next request through ${applyTo.map((e) => `'${e.name}'`).join(", ")} uses it. Other endpoints keep their versions.`}
          confirm={applyTo.length === 1 ? "Save and apply" : `Save and apply to ${applyTo.length}`}
          busy={busy}
          onConfirm={onSaveAndApply}
        />
      )}
      <Button variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button>
    </div>
  );
}

export interface PolicyFormProps {
  policy?: PolicyVersion;
  template?: PolicyVersion;
  endpoints: Endpoint[];
  preferred?: string | null;
  latest?: number;
  hosted: boolean;
  busy: boolean;
  onSave: (body: PolicyBody, applyTo: Endpoint[]) => Promise<void>;
  onCancel: () => void;
}

function resolveInitialModeAndDetection(start: PolicyVersion | undefined, hosted: boolean) {
  if (hosted || !start) return { mode: "fast", detection: "local" as VisualDetection };
  return {
    mode: start.mode || "fast",
    detection: (start.visual_detection || "local") as VisualDetection,
  };
}

function resolveInitialPolicyDefaults(policy: PolicyVersion | undefined, template: PolicyVersion | undefined, hosted: boolean) {
  const start = policy ?? template;
  const { mode, detection } = resolveInitialModeAndDetection(start, hosted);
  return {
    name: policy ? policy.name : "",
    entities: { ...(start ? start.entity_policies : defaults) },
    language: start ? start.language : "hu",
    mode,
    visual: initialVisualPoliciesOf(start),
    detection,
  };
}

export function PolicyForm({ policy, template, endpoints, preferred = null, latest, hosted, busy, onSave, onCancel }: PolicyFormProps) {
  const initial = resolveInitialPolicyDefaults(policy, template, hosted);
  const [name, setName] = useState(initial.name);
  const [entities, setEntities] = useState(initial.entities);
  const [language, setLanguage] = useState(initial.language);
  const [mode, setMode] = useState(initial.mode);
  const [visual, setVisual] = useState(initial.visual);
  const [detection, setDetection] = useState<VisualDetection>(initial.detection);
  const titleId = useId();
  useFocusOnOpen(titleId);
  const affected = endpoints.filter((e) => e.enabled && e.policy_id === policy?.policy_id);
  const fromTune = affected.filter((e) => e.id === preferred);
  const applyTo = fromTune.length ? fromTune : affected;
  const guard = useEscapeGuard(onCancel, busy);
  const body = (): PolicyBody => ({ name, entity_policies: { ...entities, ...visual }, language, mode, visual_detection: detection });

  return (
    <div onKeyDown={guard.onKeyDown}>
      <Card
        title={policy ? `New version of ${policy.name}` : "Create policy"}
        titleId={titleId}
        subtitle="Mask replaces detected values with reversible placeholders. Keep sends them unchanged. Block refuses the entire request when that type is detected."
      >
        <form
          aria-labelledby={titleId}
          className="space-y-4"
          onChange={guard.onChange}
          onSubmit={(e) => {
            e.preventDefault();
            void onSave(body(), policy && fromTune.length ? applyTo : []);
          }}
        >
          <fieldset disabled={busy} className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Policy name" required={!policy}>
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
              <Field label="Detection mode" hint="Escalate and audit need a server with the LLM detector's key.">
                <Select value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="fast">Fast</option>
                  <option value="escalate">Escalate</option>
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
          <PolicyImagesFieldset
            busy={busy}
            hosted={hosted}
            detection={detection}
            onDetection={setDetection}
            visual={visual}
            onVisualChange={(type, v) => setVisual((prev) => ({ ...prev, [type]: v }))}
          />
          <PolicyReviewSection policy={policy} latest={latest} affected={affected} fromTune={fromTune} applyTo={applyTo} />
          {guard.prompt}
          <PolicyFormActions
            policy={policy}
            busy={busy}
            fromTune={fromTune}
            applyTo={applyTo}
            onSaveOnly={() => void onSave(body(), [])}
            onSaveAndApply={() => onSave(body(), applyTo)}
            onCancel={onCancel}
          />
        </form>
      </Card>
    </div>
  );
}

function EndpointSnippetBlock({ endpoint, hosted }: { endpoint: Endpoint; hosted: boolean }) {
  const [copied, setCopied] = useState("");
  const url = `${globalThis.location.origin}${endpoint.base_path}`;
  const snippet = `from openai import OpenAI\nimport os\n\nclient = OpenAI(\n    base_url=${JSON.stringify(url)},\n    api_key=os.environ["PII_GUARD_ENDPOINT_KEY"],\n)\nresponse = client.chat.completions.create(\n    model=${JSON.stringify(endpoint.model ?? "<model-id>")},\n    messages=[{"role": "user", "content": "Hello, Robin Example."}],\n)`;
  const example = exampleModel(endpoint.provider);
  function copy(value: string, label: string) {
    void navigator.clipboard.writeText(value).then(() => setCopied(`${label} copied`)).catch(() => setCopied("Copy failed. Select the text and copy it manually."));
  }
  return (
    <div className="space-y-4">
      <Field label="OpenAI-compatible base URL"><Input readOnly value={url} className="font-mono" /></Field>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => copy(url, "URL")}>Copy URL</Button>
        <Button size="sm" onClick={() => copy(snippet, "Snippet")}>Copy Python snippet</Button>
        {hosted && (
          <a
            href="#connect"
            className="text-sm text-ink underline underline-offset-4"
            onClick={(e) => {
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
      {!endpoint.model && (
        <p className="text-xs text-muted">
          This endpoint has no pinned model: replace <span className="font-mono">&lt;model-id&gt;</span> with the model your client uses
          {example ? <>, for example <span className="font-mono">{example}</span></> : " (a model ID this endpoint serves)"}.
        </p>
      )}
    </div>
  );
}

function EndpointKeyForm({ enabled, busy, name, onName, onSubmit }: { enabled: boolean; busy: boolean; name: string; onName: (v: string) => void; onSubmit: () => void }) {
  const disabledHint = useId();
  const keyHint = useId();
  const canCreate = Boolean(name.trim() && enabled);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (canCreate) onSubmit();
      }}
    >
      <Field label="Endpoint key name" required className="min-w-40 flex-1">
        <Input maxLength={64} value={name} disabled={!enabled} onChange={(e) => onName(e.target.value)} aria-describedby={enabled ? keyHint : disabledHint} />
      </Field>
      <Button variant="primary" type="submit" busy={busy} disabled={!busy && !canCreate} aria-describedby={enabled ? undefined : disabledHint}>
        {busy ? "Working…" : "Create endpoint key"}
      </Button>
      {enabled ? <p id={keyHint} className="w-full text-xs text-muted">Name it after the app that uses it.</p> : <p id={disabledHint} className="w-full text-xs text-muted">This endpoint is disabled. Re-enable it to create endpoint keys.</p>}
    </form>
  );
}

function EndpointKeysLists({ loaded, keys, keysTitle, busy, onRevoke }: { loaded: boolean; keys: EndpointKey[]; keysTitle: string; busy: boolean; onRevoke: (key: EndpointKey) => Promise<void> }) {
  const active = keys.filter((k) => !k.revoked_at).sort(newestFirst);
  const revoked = keys.filter((k) => k.revoked_at).sort(newestFirst);
  return (
    <>
      {loaded && !keys.length && <p className="text-sm text-muted">No endpoint keys yet. Create one to connect an application to this endpoint.</p>}
      {active.length > 0 && (
        <ul className={LIST} aria-labelledby={keysTitle}>
          {active.map((key) => (
            <KeyRow key={key.id} item={key}>
              <ConfirmAction size="sm" trigger="Revoke" triggerLabel={`Revoke key ${key.name}`} title={`Revoke key '${key.name}'?`} body="Apps using it stop working." confirm="Revoke key" busy={busy} onConfirm={() => onRevoke(key)} />
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
    </>
  );
}

export function EndpointConnection({ endpoint, base, call, hosted }: { endpoint: Endpoint; base: string; call: Requester; hosted: boolean }) {
  const panel = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: "start", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, []);
  const [keys, setKeys] = useState<EndpointKey[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [secret, setSecret] = useState<{ id: string; name: string; key: string } | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [announce, setAnnounce] = useState("");
  const keysTitle = useId();
  const focusLater = useFocusLater();
  const keyPath = `${base}/endpoints/${encodeURIComponent(endpoint.id)}/keys`;
  useEffect(() => {
    let active = true;
    call<{ keys: EndpointKey[] }>(keyPath)
      .then((data) => {
        if (!Array.isArray(data.keys)) throw new Error("Invalid keys");
        if (active) {
          setKeys(data.keys);
          setLoaded(true);
        }
      })
      .catch((e: unknown) => {
        if (active) setError(configurationRecovery(e, hosted));
      });
    return () => {
      active = false;
    };
  }, [call, keyPath, hosted]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(configurationRecovery(e, hosted));
    } finally {
      setBusy(false);
    }
  }
  const createKey = () => {
    setSecret(null);
    void action(async () => {
      const created = await call<EndpointKey & { key: string }>(keyPath, { name });
      setSecret({ id: created.id, name: created.name, key: created.key });
      setKeys((prev) => [...prev, { id: created.id, name: created.name, created_at: created.created_at }]);
      setName("");
    });
  };
  const revoke = (key: EndpointKey) =>
    action(async () => {
      await call(`${keyPath}/${encodeURIComponent(key.id)}`, undefined, "DELETE");
      const at = new Date().toISOString();
      setKeys((prev) => prev.map((k) => (k.id === key.id ? { ...k, revoked_at: at } : k)));
      if (secret?.id === key.id) setSecret(null);
      setAnnounce(`Key '${key.name}' revoked.`);
      focusLater(byId(keysTitle));
    });
  return (
    <Card
      ref={panel}
      tabIndex={-1}
      aria-label={`Connect ${endpoint.name}`}
      title={`Connect ${endpoint.name}`}
      subtitle={`Endpoint keys authorize only this endpoint. Your provider key stays ${hosted ? "on the PII Guard server" : "in the guard"}; apps never see it.`}
      className="focus:outline-none"
    >
      <EndpointSnippetBlock endpoint={endpoint} hosted={hosted} />
      <div className="mt-6 space-y-4 border-t border-line pt-5">
        <h3 id={keysTitle} tabIndex={-1} className="text-lg font-normal text-ink focus:outline-none">Endpoint keys</h3>
        {error && <Notice tone="danger" live>{error}</Notice>}
        <EndpointKeyForm enabled={endpoint.enabled} busy={busy} name={name} onName={setName} onSubmit={createKey} />
        {secret && <SecretReveal label={`endpoint key '${secret.name}'`} secret={secret.key} envName="PII_GUARD_ENDPOINT_KEY" onDismiss={() => setSecret(null)} />}
        <Announcer message={announce} />
        <EndpointKeysLists loaded={loaded} keys={keys} keysTitle={keysTitle} busy={busy} onRevoke={revoke} />
      </div>
    </Card>
  );
}

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
