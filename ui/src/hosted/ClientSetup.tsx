import { useEffect, useState, type ReactNode } from "react";
import { TOOLS, endpointSnippets, type SnippetsLoader } from "../api/connect";
import { ButtonLink, Field, Select } from "../components/ui";
import { projectPath, type Endpoint, type ProjectList } from "../projects/api";
import { getSelectedProject, setSelectedEndpoint, useSelectedEndpoint } from "../projects/selection";
import type { Requester } from "./api";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ok"; endpoints: Endpoint[] };

/**
 * Hosted Connect, "Connect your app or agent": a client reaches the model through one of the
 * owner's endpoints with an endpoint key. With no endpoint yet it shows what the setup will look
 * like and sends the owner to Projects; otherwise it picks an endpoint right here (the header's
 * selection when there is one, else the first enabled endpoint) and shows its client blocks.
 */
export function ClientSetup({ call, quickstart }: { call: Requester; quickstart: (load: SnippetsLoader, endpointId: string) => ReactNode }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const picked = useSelectedEndpoint();
  useEffect(() => {
    let live = true;
    (async () => {
      const list = await call<ProjectList>("/v1/projects");
      const projectId = getSelectedProject() ?? list.default_project_id ?? list.projects[0]?.id;
      if (!projectId) return [];
      const data = await call<{ endpoints: Endpoint[] }>(`${projectPath(projectId)}/endpoints`);
      return (data.endpoints ?? []).filter((e) => e.enabled);
    })().then(
      (endpoints) => live && setLoaded({ state: "ok", endpoints }),
      () => live && setLoaded({ state: "failed" }),
    );
    return () => {
      live = false;
    };
  }, [call]);

  const endpoints = loaded.state === "ok" ? loaded.endpoints : [];
  // The header's pick when it is one of these; otherwise the first enabled endpoint, shown
  // without changing the console's scope until the owner picks one here.
  const current = endpoints.find((e) => e.id === picked) ?? endpoints[0];
  const [loader, setLoader] = useState<{ id: string; load: SnippetsLoader } | null>(null);
  if (current && loader?.id !== current.id) setLoader({ id: current.id, load: endpointSnippets(current.id) });

  return (
    <section aria-labelledby="client-setup-title" className="space-y-4">
      <div>
        <h2 id="client-setup-title" className="text-lg font-normal text-ink">
          Connect your app or agent
        </h2>
        <p className="mt-0.5 text-sm text-muted">
          A client talks to the model through one of your endpoints and authenticates with that endpoint&apos;s key. Create the key in{" "}
          <a className="text-ink underline underline-offset-4" href="#projects">
            Projects → Connect &amp; keys
          </a>
          ; it is shown once.
        </p>
      </div>
      {loaded.state === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Loading your endpoints…
        </p>
      ) : loaded.state === "failed" ? (
        <p role="alert" className="text-sm text-danger">
          Your endpoints could not be loaded. Reload the page, or open Projects.
        </p>
      ) : !current ? (
        <NoEndpointPreview />
      ) : (
        <>
          <Field label="Endpoint" hint={endpoints.length > 1 ? "Also sets the endpoint the header's menu inspects." : undefined} className="sm:max-w-md">
            <Select value={current.id} onChange={(e) => setSelectedEndpoint(e.target.value)}>
              {endpoints.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </Field>
          {loader && <div key={loader.id}>{quickstart(loader.load, loader.id)}</div>}
        </>
      )}
    </section>
  );
}

/** No endpoint yet: what the client setup will look like, and the step that unlocks it. */
function NoEndpointPreview() {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 sm:p-5" data-testid="client-setup-preview">
      <div role="tablist" aria-label="Your tool (available once you have an endpoint)" className="-mx-1 flex gap-1 overflow-x-auto">
        {TOOLS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={false} disabled className="px-3 py-2 text-sm whitespace-nowrap text-faint disabled:cursor-not-allowed">
            {t.label}
          </button>
        ))}
      </div>
      <pre aria-label="Example client settings" className="mt-3 overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-ui whitespace-pre text-muted sm:p-4">
        {`OPENAI_BASE_URL=${globalThis.location?.origin ?? ""}/e/<your-endpoint>/v1\nOPENAI_API_KEY=<your endpoint key>`}
      </pre>
      <p className="mt-3 text-sm text-muted">
        Each endpoint has its own base URL and keys. Create a policy and an endpoint in Projects, then come back here for the blocks for Muse Code, Codex, Claude Code and the rest,
        filled in for that endpoint.
      </p>
      <ButtonLink variant="primary" href="#projects" className="mt-4">
        Create an endpoint <span aria-hidden="true">→</span>
      </ButtonLink>
    </div>
  );
}
