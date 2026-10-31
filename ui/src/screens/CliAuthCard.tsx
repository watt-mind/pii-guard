import { useEffect, useState, type FormEvent } from "react";
import { Button, ButtonLink, Card, Field, Input, Notice, Select } from "../components/ui";
import type { Requester } from "../hosted/api";
import type { CliAuthParams } from "../lib/routes";
import { projectPath, type Project, type ProjectList } from "../projects/api";
import { localRequest } from "../projects/request";
import { getSelectedProject, setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import { CopyButton } from "./ConnectQuickstart";

export interface CliSessionResult {
  project: { id: string; name: string };
  endpoint: { id: string; name: string };
  key: { id: string; name: string; key: string };
  telemetry_level: "masked" | "stats";
  gateway_url: string;
  dashboard_url: string;
  bundle: string;
}

type LoadState =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "ok"; projects: Project[]; defaultProjectId: string };

const NEW_PROJECT_VALUE = "new";

export function CliAuthCard({ cliAuth, call = localRequest }: { cliAuth: CliAuthParams; call?: Requester }) {
  const [loaded, setLoaded] = useState<LoadState>({ state: "loading" });
  const [selectedProject, setSelectedProjectState] = useState<string>("");
  const [newProjectName, setNewProjectName] = useState<string>("");
  const [telemetry, setTelemetry] = useState<"masked" | "stats">(cliAuth.telemetry ?? "masked");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string>("");
  const [authorized, setAuthorized] = useState<CliSessionResult | null>(null);

  useEffect(() => {
    let live = true;
    call<ProjectList>("/v1/projects").then(
      (data) => {
        if (!live) return;
        const projects = Array.isArray(data.projects) ? data.projects : [];
        const current = getSelectedProject();
        const initial =
          projects.find((p) => p.id === current)?.id ??
          projects.find((p) => p.id === data.default_project_id)?.id ??
          projects[0]?.id ??
          NEW_PROJECT_VALUE;
        setSelectedProjectState(initial);
        setLoaded({ state: "ok", projects, defaultProjectId: data.default_project_id });
      },
      () => {
        if (live) setLoaded({ state: "failed" });
      },
    );
    return () => {
      live = false;
    };
  }, [call]);

  const isNewProject = selectedProject === NEW_PROJECT_VALUE;
  const canSubmit = !submitting && (!isNewProject || newProjectName.trim().length > 0);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    try {
      const targetId = isNewProject ? NEW_PROJECT_VALUE : selectedProject || "default";
      const result = await call<CliSessionResult>(
        `${projectPath(targetId)}/endpoints`,
        {
          ...(isNewProject ? { project_name: newProjectName.trim() } : {}),
          telemetry_level: telemetry,
          key_name: "CLI",
        },
        "PUT",
      );
      setSelectedProject(result.project.id);
      setSelectedEndpoint(result.endpoint.id);
      setAuthorized(result);
      if (cliAuth.port && cliAuth.state && import.meta.env.MODE !== "test") {
        const callbackUrl = `http://127.0.0.1:${cliAuth.port}/callback?state=${encodeURIComponent(cliAuth.state)}&bundle=${encodeURIComponent(result.bundle)}`;
        globalThis.location?.assign?.(callbackUrl);
      }
    } catch {
      setError("Could not authorize the CLI session. Check your project selection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  const callbackUrl =
    authorized && cliAuth.port && cliAuth.state
      ? `http://127.0.0.1:${cliAuth.port}/callback?state=${encodeURIComponent(cliAuth.state)}&bundle=${encodeURIComponent(authorized.bundle)}`
      : null;

  return (
    <Card
      title="Authorize CLI session"
      subtitle="Connect local pii-guard CLI runs to a project in this dashboard. Local PII detection and masking always run on your machine; only the telemetry level you choose is sent here."
    >
      <div data-testid="cli-auth-card" className="space-y-4">
        {loaded.state === "loading" ? (
          <p role="status" className="text-sm text-muted">
            Loading your projects…
          </p>
        ) : loaded.state === "failed" ? (
          <Notice tone="danger" live>
            Your projects could not be loaded. Check that you are signed in or that owner access is configured, then reload.
          </Notice>
        ) : authorized ? (
          <div className="space-y-4" data-testid="cli-auth-success">
            <Notice live>
              Authorized <strong>{authorized.project.name}</strong> ({authorized.endpoint.name}) with{" "}
              <code className="font-mono text-xs">{authorized.telemetry_level}</code> telemetry.
            </Notice>
            {callbackUrl && (
              <div className="flex flex-wrap items-center gap-3">
                <ButtonLink variant="primary" href={callbackUrl}>
                  Complete login in terminal
                </ButtonLink>
                <span className="text-xs text-muted">
                  If your browser did not return to the terminal automatically, click above or copy the token below.
                </span>
              </div>
            )}
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-ink">CLI session token (for headless or manual login)</p>
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-canvas p-3">
                <code className="min-w-0 flex-1 font-mono text-xs break-all text-ink" data-testid="cli-auth-bundle">
                  {authorized.bundle}
                </code>
                <CopyButton text={authorized.bundle} label="Copy the CLI token" />
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Project" hint="Choose which project receives telemetry from your local CLI runs.">
                <Select value={selectedProject} onChange={(e) => setSelectedProjectState(e.target.value)}>
                  {loaded.projects.map((p) => (
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

            <Field
              label="Telemetry capture level"
              hint="Raw PII never leaves your machine in either mode."
            >
              <Select
                value={telemetry}
                onChange={(e) => setTelemetry(e.target.value === "stats" ? "stats" : "masked")}
              >
                <option value="masked">
                  Masked session traces — placeholders only, no raw PII (recommended)
                </option>
                <option value="stats">
                  Stats only — counts, timings, and token usage; no message text
                </option>
              </Select>
            </Field>

            {error && (
              <Notice tone="danger" live>
                {error}
              </Notice>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="primary" busy={submitting} disabled={!canSubmit}>
                Authorize CLI
              </Button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
