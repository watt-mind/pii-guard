import { useSyncExternalStore } from "react";
import { getSelectedProject } from "../projects/selection";
import { projectPath, type Endpoint, type EndpointKey, type PolicyVersion, type ProjectList } from "../projects/api";
import type { Account, Requester } from "./api";
import { endpointState } from "./firstRun";

/** What the owner has set up, read from their own data; null while it loads or when it can't be read. */
export interface SetupState {
  provider: boolean;
  policy: boolean;
  endpoint: boolean;
  key: boolean;
  call: boolean;
}

interface Step {
  id: keyof SetupState;
  title: string;
  hint: string;
  href: string;
  cta: string;
}

/** The order a first-time owner needs: each step needs the one before it (LAB-1448). */
export const SETUP_STEPS: readonly Step[] = [
  { id: "provider", title: "Choose a model", hint: "Connect your own provider key, or use Sponsored Meta within the daily allowance.", href: "#connect", cta: "Connect a provider" },
  { id: "policy", title: "Create a policy", hint: "Decide what is masked, kept or blocked.", href: "#projects", cta: "Create a policy" },
  { id: "endpoint", title: "Create an endpoint", hint: "One upstream, model and policy version.", href: "#projects", cta: "Create an endpoint" },
  { id: "key", title: "Create an endpoint key", hint: "Your application authenticates with it. It is shown once.", href: "#connect", cta: "Create an endpoint key" },
  { id: "call", title: "Make a first call", hint: "Send a request through the endpoint, or mask a text in the Playground.", href: "#connect", cta: "Make a first call" },
];

/** Reads the current (or default) project's policies, endpoints and their keys. */
export async function loadSetup(call: Requester, account: Account): Promise<SetupState> {
  const list = await call<ProjectList>("/v1/projects");
  const projectId = getSelectedProject() ?? list.default_project_id ?? list.projects[0]?.id;
  let policy = false;
  let endpoint = false;
  let key = false;
  let answers = false;
  if (projectId) {
    const base = projectPath(projectId);
    const [p, e] = await Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]);
    policy = (p.policies ?? []).length > 0;
    const enabled = (e.endpoints ?? []).filter((x) => x.enabled);
    endpoint = enabled.length > 0;
    // A sponsored endpoint while sponsorship is off still needs a model key (LAB-1455).
    answers = enabled.some((x) => endpointState(x, account.limits.sponsored_enabled === true) === "ready");
    for (const ep of enabled.slice(0, 5)) {
      const k = await call<{ keys: EndpointKey[] }>(`${base}/endpoints/${encodeURIComponent(ep.id)}/keys`);
      if ((k.keys ?? []).some((x) => !x.revoked_at)) {
        key = true;
        break;
      }
    }
  }
  return {
    // An endpoint already names its upstream, so a model is chosen either way.
    provider: account.connections.length > 0 || answers,
    policy,
    endpoint,
    key,
    call: account.usage.requests_today > 0,
  };
}

// The last setup read, shared by every mounted list (a project switch remounts the console).
// Until the first read is in, the console holds its first paint, so the list doesn't push the
// Overview down once it arrives (layout shift, LAB-1448).
let firstReadDone = false;
let lastRead: SetupState | null = null;
const listeners = new Set<() => void>();
export function publish(next: SetupState | null) {
  lastRead = next;
  firstReadDone = true;
  for (const l of listeners) l();
}
export const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};
export const useSetupPending = () => useSyncExternalStore(subscribe, () => !firstReadDone, () => false);

export const getLastRead = () => lastRead;
