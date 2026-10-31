// The Connect quickstart (LAB-1331): harness tabs, paste-and-run blocks from
// GET /v1/connect/snippets, and the live "first request masked" check.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { firstRequest, newSessionId, parseSnippets, type Snippets, type SnippetsLoader } from "../api/connect";
import { parseTrafficEvent, type TrafficEvent } from "../api/traffic";
import type { Requester } from "../hosted/api";
import type { ServerStatusState } from "../hooks/useServerStatus";
import { Connect } from "./Connect";

const URL_OF = (session: string) => `http://127.0.0.1:8899/s/${session}/v1`;

function snippetsFor(session: string, overrides: Partial<Snippets> = {}): Snippets {
  const url = URL_OF(session);
  const tool = (id: string, label: string, kind: string, code: string, supported = true) => ({
    id,
    label,
    api: "chat",
    kind,
    supported,
    code,
    note: `${label} note`,
    tested_version: kind === "request" || !supported ? null : "1.0.0",
    docs: null,
  });
  return {
    gateway_url: "http://127.0.0.1:8899/v1",
    session,
    session_url: url,
    models: ["muse-spark-1.3", "muse-spark-1.2"],
    model: "muse-spark-1.3",
    auth: { token_required: false, token_env: "PII_GUARD_API_TOKEN" },
    upstream: { connected: false, mock: true, origin: null, preset: null, label: null },
    presets: [
      { id: "meta", label: "Meta Model API", base_url: "https://api.meta.ai/v1", key_env: "META_API_KEY", default_model: "muse-spark-1.3", command: "export META_API_KEY=<your-key>\npii-guard up --upstream meta" },
      { id: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", key_env: "OPENAI_API_KEY", default_model: null, command: "export OPENAI_API_KEY=<your-key>\npii-guard up --upstream openai" },
    ],
    tools: [
      tool("muse-code", "Muse Code", "connect", `pii-guard connect muse-code --gateway ${url}\nmuse`),
      tool("pi", "pi", "connect", `pii-guard connect pi --gateway ${url}`),
      tool("codex", "Codex", "launch", `codex -m muse-spark-1.3 -c 'model_providers.pii-guard={base_url="${url}"}'`),
      tool("opencode", "OpenCode", "launch", `export OPENCODE_CONFIG_CONTENT='{"baseURL":"${url}"}'\nopencode`),
      { ...tool("curl", "cURL", "request", `curl -si ${url}/chat/completions`), more: [{ title: "Responses API", code: `curl -s ${url}/responses -d '{"model":"muse-wonder-1.0"}'` }] },
      tool("python", "Python", "request", `OpenAI(base_url="${url}")`),
      tool("claude-code", "Claude Code", "unsupported", "", false),
    ],
    traffic_log: "masked",
    session_ref: `ref_${session}`,
    ...overrides,
  };
}

const okStatus: ServerStatusState = { state: "loading" };

function loader(overrides: Partial<Snippets> = {}) {
  return vi.fn<SnippetsLoader>((q) => Promise.resolve({ state: "ok", snippets: snippetsFor(q.session, { ...overrides, model: q.model ?? overrides.model ?? "muse-spark-1.3" }) }));
}

function event(sessionRef: string, extra: Record<string, unknown> = {}): TrafficEvent {
  return parseTrafficEvent({
    id: `req_${sessionRef}`,
    seq: 3,
    time: "2026-10-28T10:00:00Z",
    level: "masked",
    outcome: "ok",
    error: null,
    session_ref: sessionRef,
    entities: { detected: { EMAIL: 1, PERSON: 1 }, masked: { EMAIL: 1, PERSON: 1 }, texts: 1 },
    timing: { total_ms: 5, upstream_ms: 2, overhead_ms: 3, stages_ms: {} },
    ...extra,
  })!;
}

const live = (events: TrafficEvent[] = []) => ({ events, status: { state: "live", via: "sse", level: "masked", size: 200 } as const, source: "api" as const });

beforeEach(() => localStorage.clear());

describe("Connect quickstart", () => {
  it("shows the start command, the tool's block with copy buttons, and waits for the first request", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const load = loader();
    render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);

    const tabs = screen.getByRole("tablist", { name: "Your tool" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Muse Code", "pi", "Codex", "OpenCode", "cURL", "Python", "Claude Codesoon"]);
    expect(await screen.findByText(/pii-guard up --upstream meta/)).toBeInTheDocument();
    const session = load.mock.calls[0]![0].session;
    expect(session).toMatch(/^c_[0-9a-f]{32}$/);
    expect(screen.getByText(`pii-guard connect muse-code --gateway ${URL_OF(session)}`, { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Waiting for Muse Code…")).toBeInTheDocument();
    expect(screen.getByText(/Tested end to end with Muse Code 1\.0\.0/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy the Muse Code block" }));
    expect(writeText).toHaveBeenCalledWith(`pii-guard connect muse-code --gateway ${URL_OF(session)}\nmuse`);

    // Another provider's start command.
    await user.click(screen.getByRole("radio", { name: "OpenAI" }));
    expect(screen.getByText(/pii-guard up --upstream openai/)).toBeInTheDocument();
  });

  it("gives each tool its own stable session, and switches tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    const load = loader();
    const { unmount } = render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);
    await screen.findByText("Waiting for Muse Code…");
    await user.click(screen.getByRole("tab", { name: "Codex" }));
    expect(await screen.findByText("Waiting for Codex…")).toBeInTheDocument();
    expect(screen.getByText(/codex -m muse-spark-1\.3/)).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(await screen.findByText("Waiting for OpenCode…")).toBeInTheDocument();
    const sessions = load.mock.calls.map((c) => c[0].session);
    expect(new Set(sessions).size).toBe(3);
    unmount();

    // A reload keeps the tool and its session: the pasted block stays valid.
    const again = loader();
    render(<Connect status={okStatus} traffic={live()} loadSnippets={again} />);
    await screen.findByText("Waiting for OpenCode…");
    expect(again.mock.calls[0]![0].session).toBe(sessions[2]);
  });

  it("opens the deep-linked client tab first, and follows later links (LAB-1314)", async () => {
    const load = loader();
    const { rerender } = render(<Connect status={okStatus} traffic={live()} loadSnippets={load} initialClient="codex" />);
    expect(await screen.findByText("Waiting for Codex…")).toBeInTheDocument();
    rerender(<Connect status={okStatus} traffic={live()} loadSnippets={load} initialClient="pi" />);
    expect(await screen.findByText("Waiting for pi…")).toBeInTheDocument();
  });

  it("ignores an unknown deep-linked client (LAB-1314)", async () => {
    render(<Connect status={okStatus} traffic={live()} loadSnippets={loader()} initialClient="bogus" />);
    expect(await screen.findByText("Waiting for Muse Code…")).toBeInTheDocument();
  });

  it("turns step 3 green when the tool's first request arrives, and links to it in Logs", async () => {
    const user = userEvent.setup();
    const onOpenLog = vi.fn();
    const load = loader();
    const { rerender } = render(<Connect status={okStatus} traffic={live([event("ref_other")])} loadSnippets={load} onOpenLog={onOpenLog} />);
    await screen.findByText("Waiting for Muse Code…");
    const ref = `ref_${load.mock.calls[0]![0].session}`;
    rerender(<Connect status={okStatus} traffic={live([event("ref_other"), event(ref)])} loadSnippets={load} onOpenLog={onOpenLog} />);
    expect(await screen.findByText("✓ First request from Muse Code: 2 values masked, 0 of them reached the model.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open in Logs" }));
    expect(onOpenLog).toHaveBeenCalledWith(`req_${ref}`);
    expect(screen.queryByRole("button", { name: "Open session in Vault" })).toBeNull();
    const onOpenSession = vi.fn();
    rerender(<Connect status={okStatus} traffic={live([event(ref)])} loadSnippets={load} onOpenLog={onOpenLog} onOpenSession={onOpenSession} />);
    await user.click(screen.getByRole("button", { name: "Open session in Vault" }));
    expect(onOpenSession).toHaveBeenCalledWith(ref);
  });

  it("says when the first request was stopped, and counts values kept by policy", async () => {
    const load = loader();
    const { rerender } = render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);
    await screen.findByText("Waiting for Muse Code…");
    const ref = `ref_${load.mock.calls[0]![0].session}`;
    const refused = event(ref, { outcome: "refused", error: { code: "unsupported_content", status: 400 } });
    rerender(<Connect status={okStatus} traffic={live([refused])} loadSnippets={load} />);
    expect(await screen.findByText(/was stopped \(unsupported_content\): nothing was sent to the model/)).toBeInTheDocument();
    const kept = event(ref, { entities: { detected: { EMAIL: 1, ORGANIZATION: 1 }, masked: { EMAIL: 1 }, texts: 1 } });
    rerender(<Connect status={okStatus} traffic={live([kept])} loadSnippets={load} />);
    expect(await screen.findByText(/1 value masked, 1 more kept by policy/)).toBeInTheDocument();
  });

  it("says the gateway is connected when it has a real upstream, and refetches for another model", async () => {
    const user = userEvent.setup();
    const load = loader({ upstream: { connected: true, mock: false, origin: "https://api.meta.ai", preset: "meta", label: "Meta Model API" } });
    render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);
    expect(await screen.findByText(/Already connected to Meta Model API/)).toBeInTheDocument();
    expect(screen.queryByText(/pii-guard up --upstream/)).toBeNull();
    // Muse Code's block names no model (Muse picks its own): no picker there.
    expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Codex" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Model" }), "muse-spark-1.2");
    await waitFor(() => expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ model: "muse-spark-1.2" }), expect.anything()));
  });

  it("shows the Responses API request under the cURL block", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<Connect status={okStatus} traffic={live()} loadSnippets={loader()} />);
    await screen.findByText("Waiting for Muse Code…");
    await user.click(screen.getByRole("tab", { name: "cURL" }));
    expect(await screen.findByText("Responses API")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy the cURL Responses API block" }));
    expect(writeText).toHaveBeenCalledWith(expect.stringMatching(/\/responses -d '\{"model":"muse-wonder-1\.0"\}'$/));
  });

  it("shows Claude Code as coming soon, without a block", async () => {
    const user = userEvent.setup();
    render(<Connect status={okStatus} traffic={live()} loadSnippets={loader()} />);
    await screen.findByText("Waiting for Muse Code…");
    await user.click(screen.getByRole("tab", { name: /Claude Code/ }));
    expect(await screen.findByText("Claude Code is coming soon.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy the Claude Code block/ })).toBeNull();
  });

  it("warns that names pass when the server has no NER", async () => {
    render(<Connect status={{ state: "ok", status: { ner: { available: false, model: null }, gateway: { url: "http://127.0.0.1:8899/v1" }, version: "0.1.0", upstream: { mock: false } } as never }} traffic={live()} loadSnippets={loader()} />);
    expect(await screen.findByText(/free-text names are not \(they reach the model as written\)/)).toBeInTheDocument();
  });

  it("explains why it can't watch when the traffic log is off", async () => {
    render(<Connect status={okStatus} traffic={live()} loadSnippets={loader({ session_ref: null, traffic_log: "off" })} />);
    expect(await screen.findByText(/The traffic log is off/)).toBeInTheDocument();
  });

  it("falls back to the start command when the server can't be asked", async () => {
    render(<Connect status={{ state: "offline" }} loadSnippets={() => Promise.resolve({ state: "offline" })} />);
    expect(await screen.findByText(/isn't reachable from this page/)).toBeInTheDocument();
    expect(screen.getByText(/pii-guard connect muse-code --print/)).toBeInTheDocument();
  });

  it("never renders a key value", async () => {
    const { container } = render(<Connect status={okStatus} traffic={live()} loadSnippets={loader()} />);
    await screen.findByText("Waiting for Muse Code…");
    expect(container.textContent).toContain("<your-key>");
    expect(container.textContent).not.toMatch(/sk-|Bearer [A-Za-z0-9]{8}/);
  });

  it("renders the CLI authorization card for #cli-auth and issues a session bundle (LAB-1708)", async () => {
    const user = userEvent.setup();
    const callMock = vi.fn(async (path: string, body?: unknown, method?: string) => {
      if (path === "/v1/projects") {
        return {
          default_project_id: "prj_1",
          projects: [{ id: "prj_1", name: "Default project", default_policy_id: "pol_1" }],
        };
      }
      if (path === "/v1/projects/new/endpoints" && method === "PUT") {
        const req = body as { project_name: string; telemetry_level: "masked" | "stats" };
        return {
          project: { id: "prj_new", name: req.project_name },
          endpoint: { id: "ep_cli", name: "CLI telemetry" },
          key: { id: "key_1", name: "CLI", key: "pg_ep_aaa" },
          telemetry_level: req.telemetry_level,
          gateway_url: "https://guard.watt-mind.com/e/ep_cli/v1",
          dashboard_url: "https://guard.watt-mind.com/#logs",
          bundle: "pg_cli_synthetic_bundle",
        };
      }
      throw new Error(`unexpected request ${method ?? "GET"} ${path}`);
    });
    render(
      <Connect
        status={okStatus}
        traffic={live()}
        loadSnippets={loader()}
        cliAuth={{ port: 51234, state: "st_abc", telemetry: "masked" }}
        call={callMock as unknown as Requester}
      />,
    );

    const card = await screen.findByTestId("cli-auth-card");
    await within(card).findByRole("combobox", { name: /Project/ });
    await user.selectOptions(within(card).getByRole("combobox", { name: /Project/ }), "new");
    await user.type(within(card).getByRole("textbox", { name: /New project name/ }), "Agent CLI");
    await user.selectOptions(within(card).getByRole("combobox", { name: /Telemetry capture level/ }), "stats");
    await user.click(within(card).getByRole("button", { name: "Authorize CLI" }));

    expect(await screen.findByTestId("cli-auth-bundle")).toHaveTextContent("pg_cli_synthetic_bundle");
    const callbackLink = screen.getByRole("link", { name: "Complete login in terminal" });
    expect(callbackLink).toHaveAttribute(
      "href",
      "http://127.0.0.1:51234/callback?state=st_abc&bundle=pg_cli_synthetic_bundle",
    );
  });
});

describe("connect api helpers", () => {
  it("makes c_ + 32 hex session ids", () => {
    expect(newSessionId(() => new Uint8Array(16).fill(171))).toBe("c_" + "ab".repeat(16));
  });

  it("finds the oldest event of the session", () => {
    const a = { ...event("r1"), id: "a", seq: 9 };
    const b = { ...event("r1"), id: "b", seq: 4 };
    expect(firstRequest([a, b, event("r2")], "r1")?.id).toBe("b");
    expect(firstRequest([a], null)).toBeNull();
  });

  it("rejects a body that isn't a snippets document", () => {
    expect(parseSnippets({ tools: [] })).toBeNull();
    expect(parseSnippets(snippetsFor("c_x"))?.tools).toHaveLength(7);
  });

  it("tells a pass-through endpoint's client to fill in its own model (LAB-1451)", async () => {
    const load = vi.fn<SnippetsLoader>((q) => Promise.resolve({ state: "ok", snippets: snippetsFor(q.session, { model: null, models: [], endpoint: { id: "ep-one", name: "Agents", model: null } }) }));
    render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);
    expect(await screen.findByText(/This endpoint lets your client choose the model/)).toHaveTextContent("a model ID your endpoint serves");
    expect(screen.queryByText(/The gateway lists no model yet/)).not.toBeInTheDocument();
  });

  it("gives a pass-through endpoint's client an example model for its provider (LAB-1451)", async () => {
    const upstream = { connected: true, mock: false, origin: null, preset: "openai", label: "OpenAI" };
    const load = vi.fn<SnippetsLoader>((q) => Promise.resolve({ state: "ok", snippets: snippetsFor(q.session, { model: null, models: [], upstream, endpoint: { id: "ep-one", name: "Agents", model: null } }) }));
    render(<Connect status={okStatus} traffic={live()} loadSnippets={load} />);
    expect(await screen.findByText(/This endpoint lets your client choose the model/)).toHaveTextContent("for example gpt-4.1-mini");
  });
});
