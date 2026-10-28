import { useEffect, useState } from "react";
import { ButtonLink } from "../components/ui";
import { getSelectedProject } from "../projects/selection";
import { projectPath, type Endpoint, type EndpointKey, type PolicyVersion, type ProjectList } from "../projects/api";
import type { Account, Requester } from "./api";

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
  { id: "key", title: "Create an endpoint key", hint: "Your application authenticates with it. It is shown once.", href: "#projects", cta: "Create an endpoint key" },
  { id: "call", title: "Make a first call", hint: "Send a request through the endpoint, or mask a text in the Playground.", href: "#connect", cta: "Make a first call" },
];

/** Reads the current (or default) project's policies, endpoints and their keys. */
export async function loadSetup(call: Requester, account: Account): Promise<SetupState> {
  const list = await call<ProjectList>("/v1/projects");
  const projectId = getSelectedProject() ?? list.default_project_id ?? list.projects[0]?.id;
  let policy = false;
  let endpoint = false;
  let key = false;
  if (projectId) {
    const base = projectPath(projectId);
    const [p, e] = await Promise.all([call<{ policies: PolicyVersion[] }>(`${base}/policies`), call<{ endpoints: Endpoint[] }>(`${base}/endpoints`)]);
    policy = (p.policies ?? []).length > 0;
    const enabled = (e.endpoints ?? []).filter((x) => x.enabled);
    endpoint = enabled.length > 0;
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
    provider: account.connections.length > 0 || endpoint,
    policy,
    endpoint,
    key,
    call: account.usage.requests_today > 0,
  };
}

/** One ordered setup list with ticks and one primary action: the next step not yet done. */
export function SetupChecklist({ call, account, active, calls }: { call: Requester; account: Account; active: boolean; calls: number }) {
  const [state, setState] = useState<SetupState | null>(null);
  useEffect(() => {
    if (!active) return;
    let live = true;
    loadSetup(call, account).then(
      (s) => live && setState(s),
      () => live && setState(null),
    );
    return () => {
      live = false;
    };
  }, [call, account, active]);
  if (!state) return null;
  const done: SetupState = { ...state, call: state.call || calls > 0 };
  const next = SETUP_STEPS.find((s) => !done[s.id]);
  if (!next) return null;
  const count = SETUP_STEPS.filter((s) => done[s.id]).length;
  return (
    <section aria-labelledby="setup-title" className="mt-5 border-t border-line pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="setup-title" className="text-lg font-normal text-ink">
          Set up your gateway
        </h3>
        <span className="text-xs text-muted tabular-nums">
          {count} of {SETUP_STEPS.length} done
        </span>
      </div>
      <ol className="mt-3 space-y-2.5">
        {SETUP_STEPS.map((s, i) => {
          const ok = done[s.id];
          const current = s.id === next.id;
          return (
            <li key={s.id} className="flex items-start gap-3" aria-current={current ? "step" : undefined}>
              <span
                aria-hidden="true"
                className={[
                  "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border text-2xs tabular-nums",
                  ok ? "border-guard bg-guard-soft text-guard-ink" : current ? "border-ink text-ink" : "border-line-strong text-muted",
                ].join(" ")}
              >
                {ok ? (
                  <svg viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m3.5 8.5 3 3 6-7" />
                  </svg>
                ) : (
                  i + 1
                )}
              </span>
              <div className="min-w-0">
                <p className={["text-sm", ok ? "text-muted" : "font-medium text-ink"].join(" ")}>
                  {s.title}
                  <span className="sr-only">{ok ? " (done)" : current ? " (next)" : ""}</span>
                </p>
                {!ok && <p className="text-xs text-muted">{s.hint}</p>}
              </div>
            </li>
          );
        })}
      </ol>
      <ButtonLink variant="primary" href={next.href} className="mt-4">
        {next.cta} <span aria-hidden="true">→</span>
      </ButtonLink>
    </section>
  );
}
