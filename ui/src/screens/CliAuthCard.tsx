import { useEffect, useState, type FormEvent } from "react";
import { Button, ButtonLink, Card, Field, Input, Notice, Select } from "../components/ui";
import type { Requester } from "../hosted/api";
import type { CliHandoffParams } from "../lib/routes";
import { projectPath, type Project, type ProjectList } from "../projects/api";
import { localRequest } from "../projects/request";
import { getSelectedProject, setSelectedProject } from "../projects/selection";
import { CopyButton } from "./ConnectQuickstart";

/** `POST /v1/projects/{id}/cli-codes` (LAB-1708): a one-time, five-minute login code. */
export interface CliCode {
  code: string;
  expires_in: number;
}

type Telemetry = "masked" | "stats";

type LoadState =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "ok"; projects: Project[] };

const NEW_PROJECT_VALUE = "new";

/** The CLI's loopback callback: `state` and the one-time code only, never a key. */
function cliCallbackUrl(port: number, state: string, code: string): string {
  const query = new URLSearchParams({ state, code });
  return `http://127.0.0.1:${port}/callback?${query.toString()}`;
}

/** The waiting CLI's loopback callback, `null` for paste mode, or `"malformed"` to refuse. */
function callbackTarget(handoff: CliHandoffParams): { port: number; state: string } | null | "malformed" {
  const { port, state } = handoff;
  if (handoff.malformed) return "malformed";
  if (port === undefined && state === undefined) return null;
  if (port === undefined || !Number.isInteger(port) || port < 1 || port > 65535) return "malformed";
  if (!state || !/^[A-Za-z0-9_-]{1,128}$/.test(state)) return "malformed";
  return { port, state };
}

export function CliAuthCard({ cliHandoff, call = localRequest }: { cliHandoff: CliHandoffParams; call?: Requester }) {
  const target = callbackTarget(cliHandoff);
  const refused = target === "malformed";
  const callback = target === "malformed" ? null : target;
  const [loaded, setLoaded] = useState<LoadState>({ state: "loading" });
  const [selectedProject, setSelectedProjectState] = useState<string>("");
  const [newProjectName, setNewProjectName] = useState<string>("");
  const [telemetry, setTelemetry] = useState<Telemetry>(cliHandoff.telemetry ?? "masked");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>("");
  const [issued, setIssued] = useState<{ code: CliCode; project: string } | null>(null);

  useEffect(() => {
    if (refused) return;
    let live = true;
    call<ProjectList>("/v1/projects").then(
      (data) => {
        if (!live) return;
        const projects = Array.isArray(data.projects) ? data.projects : [];
        const current = getSelectedProject();
        const initial =
          projects.find((p) => p.id === cliHandoff.project)?.id ??
          projects.find((p) => p.id === current)?.id ??
          projects.find((p) => p.id === data.default_project_id)?.id ??
          projects[0]?.id ??
          NEW_PROJECT_VALUE;
        setSelectedProjectState(initial);
        setLoaded({ state: "ok", projects });
      },
      () => {
        if (live) setLoaded({ state: "failed" });
      },
    );
    return () => {
      live = false;
    };
  }, [call, refused, cliHandoff.project]);

  if (refused) {
    return (
      <Card title="Connect the pii-guard CLI">
        <div data-testid="cli-auth-card">
          <Notice tone="danger" live>
            This link has an invalid CLI request (its port or state is malformed or incomplete). Run <code className="font-mono text-xs">pii-guard login</code> in your terminal again and open the link it prints.
          </Notice>
        </div>
      </Card>
    );
  }

  const isNewProject = selectedProject === NEW_PROJECT_VALUE;
  const projects = loaded.state === "ok" ? loaded.projects : [];
  const projectName = isNewProject
    ? newProjectName.trim() || "a new project"
    : (projects.find((p) => p.id === selectedProject)?.name ?? "a project");
  const canSubmit = !submitting && (!isNewProject || newProjectName.trim().length > 0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      let target = selectedProject || "default";
      let name = projectName;
      if (isNewProject) {
        const created = await call<Project>("/v1/projects", { name: newProjectName.trim() });
        target = created.id;
        name = created.name;
      }
      const code = await call<CliCode>(`${projectPath(target)}/cli-codes`, { telemetry_level: telemetry });
      if (target !== "default") setSelectedProject(target);
      setIssued({ code, project: name });
    } catch {
      setError("Could not connect the CLI. Check your project selection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const minutes = issued ? Math.max(1, Math.round(issued.code.expires_in / 60)) : 0;
  const pasteCommand = "pii-guard login --code -";

  return (
    <Card
      title="Connect the pii-guard CLI"
      subtitle="Detection and masking always run on your machine; only the telemetry level you choose is sent to this dashboard. The CLI gets a key that can only write this project's Logs."
    >
      <div data-testid="cli-auth-card" className="space-y-4">
        <p className="text-sm text-ink" data-testid="cli-auth-request">
          {callback ? (
            <>
              A pii-guard CLI on this computer (port <code className="font-mono text-xs">{callback.port}</code>) is asking for access to <strong>{issued ? issued.project : projectName}</strong>.
            </>
          ) : (
            <>
              Approve a pii-guard CLI for <strong>{issued ? issued.project : projectName}</strong>; you will get a one-time code to paste into its terminal.
            </>
          )}
        </p>
        {loaded.state === "loading" ? (
          <p role="status" className="text-sm text-muted">
            Loading your projects…
          </p>
        ) : loaded.state === "failed" ? (
          <Notice tone="danger" live>
            Your projects could not be loaded. Check that you are signed in or that owner access is configured, then reload.
          </Notice>
        ) : issued ? (
          <div className="space-y-4" data-testid="cli-auth-success">
            <Notice live>
              Approved with <code className="font-mono text-xs">{telemetry}</code> telemetry. The code below works once and expires in {minutes} minutes.
            </Notice>
            {callback && (
              <div className="flex flex-wrap items-center gap-3">
                <ButtonLink variant="primary" href={cliCallbackUrl(callback.port, callback.state, issued.code.code)}>
                  Send to the CLI
                </ButtonLink>
                <span className="text-xs text-muted">Returns this one-time code to the CLI waiting on port {callback.port}.</span>
              </div>
            )}
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-ink">
                {callback ? "CLI on another machine, or no browser there? " : ""}Run <code className="font-mono text-xs" data-testid="cli-auth-paste">{pasteCommand}</code> in its terminal and paste this one-time code:
              </p>
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-canvas p-3">
                <code className="min-w-0 flex-1 font-mono text-xs break-all text-ink" data-testid="cli-auth-code">
                  {issued.code.code}
                </code>
                <CopyButton text={issued.code.code} label="Copy the one-time code" />
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Project" hint="Which project's Logs receive telemetry from your local CLI runs.">
                <Select value={selectedProject} onChange={(e) => setSelectedProjectState(e.target.value)}>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                  <option value={NEW_PROJECT_VALUE}>+ Create a new project</option>
                </Select>
              </Field>
              {isNewProject && (
                <Field label="New project name" required>
                  <Input
                    value={newProjectName}
                    onChange={(e) => setNewProjectName(e.target.value)}
                    placeholder="My CLI project"
                    maxLength={64}
                  />
                </Field>
              )}
            </div>

            <Field label="Telemetry capture level" hint="Raw PII never leaves your machine in either mode.">
              <Select value={telemetry} onChange={(e) => setTelemetry(e.target.value === "stats" ? "stats" : "masked")}>
                <option value="masked">Masked session traces — placeholders only, no raw PII (recommended)</option>
                <option value="stats">Stats only — counts, timings, and token usage; no message text</option>
              </Select>
            </Field>

            {error && (
              <Notice tone="danger" live>
                {error}
              </Notice>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" busy={submitting} disabled={!canSubmit}>
                Approve CLI access
              </Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
