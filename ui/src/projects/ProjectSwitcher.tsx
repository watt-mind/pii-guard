import { useEffect, useState } from "react";
import { request } from "../hosted/api";
import type { Endpoint, ProjectList } from "./api";
import { setSelectedEndpoint, setSelectedProject, useSelectedEndpoint, useSelectedProject } from "./selection";

export function ProjectSwitcher() {
  const selected = useSelectedProject();
  const endpoint = useSelectedEndpoint();
  const [revision, setRevision] = useState(0);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [list, setList] = useState<ProjectList | null>(null);
  useEffect(() => {
    let active = true;
    void request<ProjectList>("/v1/projects").then((data) => {
      if (!active || !Array.isArray(data.projects)) return;
      setList(data);
      if (!selected) setSelectedProject(data.default_project_id);
    }).catch(() => { /* Older/offline guards keep their existing local console. */ });
    return () => { active = false; };
  }, [selected]);
  useEffect(() => {
    const update = () => setRevision((n) => n + 1);
    window.addEventListener("pii-guard-project-configuration", update);
    return () => window.removeEventListener("pii-guard-project-configuration", update);
  }, []);
  useEffect(() => {
    let active = true;
    if (!selected) return;
    void request<{ endpoints: Endpoint[] }>(`/v1/projects/${encodeURIComponent(selected)}/endpoints`).then((data) => {
      if (active && Array.isArray(data.endpoints)) setEndpoints(data.endpoints);
    }).catch(() => { /* Endpoint management can still be retried in Projects. */ });
    return () => { active = false; };
  }, [selected, revision]);
  if (!list) return null;
  return <div><label className="mx-4 mb-3 grid gap-1 text-xs text-muted">Project<select aria-label="Project" className="h-9 min-w-0 rounded-lg border border-field bg-surface px-2 text-sm text-ink" value={selected ?? list.default_project_id} onChange={(e) => setSelectedProject(e.target.value)}>{list.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>{endpoints.length > 0 && <label className="mx-4 mb-3 grid gap-1 text-xs text-muted">Inspect activity & vault<select aria-label="Inspect activity & vault" className="h-9 min-w-0 rounded-lg border border-field bg-surface px-2 text-sm text-ink" value={endpoint ?? ""} onChange={(e) => setSelectedEndpoint(e.target.value || null)}><option value="">Project playground</option>{endpoints.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}</div>;
}
