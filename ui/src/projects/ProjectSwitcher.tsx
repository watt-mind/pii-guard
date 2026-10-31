import { useEffect, useId, useState, type RefObject } from "react";
import { localRequest as request } from "./request";
import type { Endpoint, Project, ProjectList } from "./api";
import { setSelectedEndpoint, setSelectedProject, useSelectedEndpoint, useSelectedProject } from "./selection";
import { MenuHeading, MenuPanel, MenuSeparator } from "../components/Menu";
import { MENU_ITEM, useMenu } from "../hooks/useMenu";

// A pick remounts the console (LocalConsole is keyed by the selection), and the switcher with
// it; this tells the new switcher to take focus back, as the menu-button pattern expects.
let refocusAfterSwitch = false;
const requestRefocus = () => { refocusAfterSwitch = true; };
const takeRefocus = () => { const wanted = refocusAfterSwitch; refocusAfterSwitch = false; return wanted; };

function useProjectSwitcherData(selected: string | null, enabled: boolean, triggerRef: RefObject<HTMLButtonElement | null>) {
  const [revision, setRevision] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [list, setList] = useState<ProjectList | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void request<ProjectList>("/v1/projects").then((data) => {
      if (!active || !Array.isArray(data.projects)) return;
      setList(data);
      if (!selected) setSelectedProject(data.default_project_id);
    }).catch(() => {
      // Older/offline guards keep their existing local console, but the failure is shown
      // (LAB-1714): it must never read as "no projects".
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, [selected, enabled, attempt]);

  const retry = () => { setFailed(false); setAttempt((n) => n + 1); };

  useEffect(() => {
    const update = () => setRevision((n) => n + 1);
    window.addEventListener("pii-guard-project-configuration", update);
    return () => window.removeEventListener("pii-guard-project-configuration", update);
  }, []);

  useEffect(() => {
    if (!enabled || !selected) return;
    let active = true;
    void request<{ endpoints: Endpoint[] }>(`/v1/projects/${encodeURIComponent(selected)}/endpoints`).then((data) => {
      if (active && Array.isArray(data.endpoints)) setEndpoints(data.endpoints);
    }).catch(() => { /* Endpoint management can still be retried in Projects. */ });
    return () => { active = false; };
  }, [selected, revision, enabled]);

  useEffect(() => {
    if (!list || !takeRefocus()) return;
    triggerRef.current?.focus();
  }, [list, triggerRef]);

  return { list, endpoints, failed, retry };
}

function ProjectMenuContent({
  projects,
  currentId,
  endpoints,
  endpoint,
  manage,
  onPick,
  onClose,
}: {
  projects: readonly Project[];
  currentId: string;
  endpoints: readonly Endpoint[];
  endpoint: string | null;
  manage: boolean;
  onPick: (apply: () => void, changed: boolean) => void;
  onClose: () => void;
}) {
  const projectsHeading = useId();
  const endpointsHeading = useId();
  const activeEndpoint = endpoint ?? null;
  return (
    <>
      <div role="group" aria-labelledby={projectsHeading}>
        <MenuHeading id={projectsHeading}>Your projects</MenuHeading>
        {projects.map((project) => (
          <button
            key={project.id}
            type="button"
            role="menuitemradio"
            aria-checked={project.id === currentId}
            tabIndex={-1}
            onClick={() => onPick(() => setSelectedProject(project.id), project.id !== currentId)}
            className={MENU_ITEM}
          >
            <span className="min-w-0 flex-1 truncate" title={project.name}>{project.name}</span>
            <Check on={project.id === currentId} />
          </button>
        ))}
      </div>
      {endpoints.length > 0 && (
        <>
          <MenuSeparator />
          <div role="group" aria-labelledby={endpointsHeading}>
            <MenuHeading id={endpointsHeading}>Inspect activity &amp; vault</MenuHeading>
            {[{ id: null, name: "All endpoints" }, ...endpoints].map((item) => (
              <button
                key={item.id ?? ""}
                type="button"
                role="menuitemradio"
                aria-checked={item.id === activeEndpoint}
                tabIndex={-1}
                onClick={() => onPick(() => setSelectedEndpoint(item.id), item.id !== activeEndpoint)}
                className={MENU_ITEM}
              >
                <span className="min-w-0 flex-1 truncate" title={item.name}>
                  {item.name}
                  {/* Logs merge every endpoint here (LAB-1492); the Vault stays on the project's own playground. */}
                  {item.id === null && <span className="block text-xs text-muted">Logs of every endpoint · playground vault</span>}
                </span>
                <Check on={item.id === activeEndpoint} />
              </button>
            ))}
          </div>
        </>
      )}
      {manage && (
        <>
          <MenuSeparator />
          <a role="menuitem" tabIndex={-1} href="#projects" onClick={onClose} className={MENU_ITEM}>
            <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 4h5l1-2h6v11H2zM5 7h6M5 10h4" />
            </svg>
            Manage projects
          </a>
        </>
      )}
    </>
  );
}

function formatProjectButtonLabel(project: Project | undefined, endpoint: Endpoint | undefined): string {
  const projectLabel = project?.name ?? "none";
  const endpointSuffix = endpoint ? `, inspecting ${endpoint.name}` : "";
  return `Project: ${projectLabel}${endpointSuffix}`;
}

function resolveCurrentSelection(list: ProjectList, endpoints: readonly Endpoint[], selected: string | null, endpoint: string | null) {
  const currentId = selected ?? list.default_project_id;
  const current = list.projects.find((p) => p.id === currentId);
  const currentEndpoint = endpoints.find((e) => e.id === endpoint);
  return { currentId, current, currentEndpoint, title: current?.name ?? "Choose a project" };
}

/**
 * The header's project menu: the current project's name and a chevron. It lists the owner's
 * projects with a check on the current one, the endpoints whose activity and vault the console
 * inspects, and a way to the Projects screen.
 */
export function ProjectSwitcher({ manage = true, enabled = true }: { manage?: boolean; enabled?: boolean }) {
  const selected = useSelectedProject();
  const endpoint = useSelectedEndpoint();
  const { open, close, triggerProps, menuProps } = useMenu();
  const { list, endpoints, failed, retry } = useProjectSwitcherData(selected, enabled, triggerProps.ref);

  // A fetch failure is shown, never swallowed: non-hosted used to render null, so a failure
  // read as "no projects" (LAB-1714). The indicator holds the same header height as the menu;
  // role=status keeps it polite so it never competes with the screen's assertive error alert.
  if (!list && failed) {
    return (
      <div data-header-item role="status" className="inline-flex h-9 max-w-full min-w-0 items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 text-sm text-warn pointer-coarse:h-11">
        <span className="truncate">Projects unavailable</span>
        <button type="button" onClick={retry} className="shrink-0 font-medium underline underline-offset-2 hover:text-ink">
          Retry
        </button>
      </div>
    );
  }

  // Hosted, the switcher always arrives: hold its place meanwhile, so the header doesn't shift (CLS, LAB-1626).
  if (!list) {
    return import.meta.env.VITE_PII_GUARD_HOSTED === "true" ? (
      <div data-header-item aria-hidden="true" className="h-9 w-40 max-w-full min-w-0 rounded-lg border border-line bg-surface pointer-coarse:h-11" />
    ) : null;
  }
  const { currentId, current, currentEndpoint, title } = resolveCurrentSelection(list, endpoints, selected, endpoint);

  const pick = (apply: () => void, changed: boolean) => {
    if (!changed) return close(true);
    requestRefocus();
    close(false);
    apply();
  };

  return (
    <div data-header-item className="relative min-w-0">
      <button
        {...triggerProps}
        aria-label={formatProjectButtonLabel(current, currentEndpoint)}
        className="inline-flex h-9 max-w-full min-w-0 items-center gap-2 rounded-lg pointer-coarse:h-11 border border-line-strong bg-surface px-3 text-sm text-ink transition-colors hover:bg-surface-2 aria-expanded:bg-surface-2"
      >
        <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-accent" />
        <span className="truncate font-medium" title={current?.name}>{title}</span>
        {currentEndpoint && <span className="hidden truncate text-muted sm:inline">/ {currentEndpoint.name}</span>}
        <Chevron open={open} />
      </button>
      {open && (
        <MenuPanel menuProps={menuProps} label="Projects">
          <ProjectMenuContent
            projects={list.projects}
            currentId={currentId}
            endpoints={endpoints}
            endpoint={endpoint}
            manage={manage}
            onPick={pick}
            onClose={() => close(false)}
          />
        </MenuPanel>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={["size-3.5 shrink-0 text-muted transition-transform", open ? "rotate-180" : ""].join(" ")} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="m4 6 4 4 4-4" />
    </svg>
  );
}

function Check({ on }: { on: boolean }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className={["size-4 shrink-0 text-accent", on ? "" : "invisible"].join(" ")} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="m3.5 8.5 3 3 6-7" />
    </svg>
  );
}
