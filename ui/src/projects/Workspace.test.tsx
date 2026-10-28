import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { TEXT_ENTITY_TYPES } from "../api/types";
import type { Requester } from "../hosted/api";
import { ENTITY_META } from "../lib/entities";
import type { Endpoint, PolicyVersion } from "./api";
import { Workspace } from "./Workspace";

const first: PolicyVersion = { id: "policy-family", policy_id: "policy-family", policy_version_id: "version-one", name: "Default protection", version: 1, language: "hu", mode: "fast", detection_profile: "standard", entity_policies: Object.fromEntries(TEXT_ENTITY_TYPES.map((type) => [type, ENTITY_META[type].policy])) as PolicyVersion["entity_policies"] };
const second: PolicyVersion = { ...first, policy_version_id: "version-two", version: 2, entity_policies: { ...first.entity_policies, EMAIL: "block" } };
const endpoint: Endpoint = { id: "endpoint-one", project_id: "project-one", name: "Synthetic support", policy_id: first.policy_id, policy_version_id: first.policy_version_id, policy_version: 1, provider: "openai", base_url: "https://api.example.com/v1", model: "synthetic-model", credential_configured: true, enabled: true, base_path: "/e/endpoint-one/v1" };
function fixture(custom?: (path: string, body: unknown, method: string | undefined) => unknown) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => {
    if (body || method === "DELETE") return custom?.(path, body, method) ?? endpoint;
    if (path === "/v1/projects") return { projects: [{ id: "project-one", name: "Local project", default_policy_id: first.policy_id }, { id: "project-two", name: "Another project", default_policy_id: first.policy_id }], default_project_id: "project-one" };
    if (path.endsWith("/policies")) return { policies: [first, second] };
    if (path.endsWith("/endpoints")) return { endpoints: [endpoint] };
    if (path.endsWith("/keys")) return { keys: [] };
    throw new Error("Unexpected fixture route");
  }) as unknown as Requester;
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("project workspace", () => {
  it("offers local owner access recovery without hosted sign-in or demo guidance", async () => {
    const call = (async () => { throw new ApiError(401, "unauthorized", "Sensitive server text"); }) as Requester;
    render(<Workspace call={call} />);
    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("Open Local guard access");
    expect(error).not.toHaveTextContent(/Sign in|static example|Sensitive server text/);
    expect(await screen.findByText("Local guard access")).toBeInTheDocument();
  });

  it.each([false, true])("focuses and reveals connection details only after expansion (reduced motion: %s)", async (reduced) => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: reduced }));
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    const user = userEvent.setup(); render(<Workspace call={fixture()} />);
    await screen.findByText("Synthetic support");
    expect(scroll).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Connect & keys for Synthetic support" }));
    expect(screen.getByRole("region", { name: "Connect Synthetic support" })).toHaveFocus();
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: reduced ? "auto" : "smooth" });
  });

  it("requires an explicit policy version and never preloads a provider secret", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} />);
    await screen.findByText("Synthetic support");
    await user.click(screen.getByRole("button", { name: "Create endpoint" }));
    expect(screen.getByRole("combobox", { name: "Policy version" })).toHaveValue("");
    expect(within(screen.getByRole("form", { name: "Create endpoint" })).getByRole("button", { name: "Create endpoint" })).toBeDisabled();
    expect(screen.getByLabelText(/^Provider API key/)).toHaveValue("");
    expect(screen.queryByRole("option", { name: /Sponsored/ })).not.toBeInTheDocument();
  });

  it("reviews the affected endpoint before changing its pinned version", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Edit Synthetic support" }));
    expect(screen.getByLabelText("Replace provider API key (optional)")).toHaveValue("");
    await user.selectOptions(screen.getByRole("combobox", { name: "Policy version" }), second.policy_version_id);
    expect(screen.getByRole("button", { name: "Save endpoint" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Apply Default protection v2 to this endpoint" }));
    await user.click(screen.getByRole("button", { name: "Save endpoint" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one", { name: endpoint.name, provider: "openai", model: "synthetic-model", policy_version_id: "version-two", enabled: true }, "PUT"));
  });

  it("creates a new policy version without updating endpoints", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} hosted />);
    await user.click(await screen.findByRole("button", { name: "New version of Default protection v1" }));
    expect(screen.getByText(/Synthetic support \(v1\)/)).toBeInTheDocument();
    expect(screen.getByText(/No endpoint changes automatically/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Detection mode")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Face")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Email"), "block");
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/policies/policy-family", { name: first.name, language: "hu", mode: "fast", entity_policies: { ...first.entity_policies, EMAIL: "block" } }, "PUT"));
    expect(vi.mocked(call).mock.calls.filter(([path, body]) => path.includes("/endpoints/") && body)).toHaveLength(0);
  });

  it("reveals endpoint keys once, keeps the snippet secret-free, and revokes by endpoint scope", async () => {
    const call = fixture(() => ({ id: "key-one", name: "Synthetic integration", created_at: "2026-10-28T00:00:00Z", key: "synthetic-once-only-key" }));
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    expect(screen.getByLabelText("OpenAI-compatible base URL")).toHaveValue(`${location.origin}/e/endpoint-one/v1`);
    await user.type(screen.getByRole("textbox", { name: "Endpoint key name" }), "Synthetic integration");
    await user.click(screen.getByRole("button", { name: "Create endpoint key" }));
    await screen.findByText("synthetic-once-only-key");
    expect(screen.getByText(/from openai import OpenAI/).textContent).not.toContain("synthetic-once-only-key");
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    await user.click(screen.getByRole("button", { name: "Dismiss key" }));
    // Nothing was copied, so dismissing asks first.
    await user.click(screen.getByRole("button", { name: "I've stored it, dismiss" }));
    expect(screen.queryByText("synthetic-once-only-key")).not.toBeInTheDocument();
  });

  it("asks before revoking a key, keeps it listed as Revoked, announces it and focuses the key list", async () => {
    const call = fixture(() => ({ id: "key-one", name: "Synthetic integration", created_at: "2026-10-28T00:00:00Z", key: "synthetic-once-only-key" }));
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    await user.type(screen.getByRole("textbox", { name: "Endpoint key name" }), "Synthetic integration");
    await user.click(screen.getByRole("button", { name: "Create endpoint key" }));
    await screen.findByText("synthetic-once-only-key");
    await user.click(screen.getByRole("button", { name: "Revoke key Synthetic integration" }));
    // Asks first: nothing is deleted until the danger button is pressed.
    const confirm = screen.getByRole("group", { name: "Revoke key 'Synthetic integration'?" });
    expect(confirm).toHaveTextContent("Apps using it stop working.");
    expect(within(confirm).getByRole("button", { name: "Revoke key" })).toHaveFocus();
    expect(vi.mocked(call).mock.calls.some(([, , method]) => method === "DELETE")).toBe(false);
    await user.click(within(confirm).getByRole("button", { name: "Revoke key" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one/keys/key-one", undefined, "DELETE"));
    const list = await screen.findByRole("list", { name: "Endpoint keys" });
    expect(within(list).getByText("Synthetic integration")).toBeInTheDocument();
    expect(within(list).getByText("Revoked")).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /Revoke/ })).not.toBeInTheDocument();
    expect(screen.queryByText("synthetic-once-only-key")).not.toBeInTheDocument();
    expect(screen.getByText("Key 'Synthetic integration' revoked.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Endpoint keys" })).toHaveFocus());
  });

  it("cancels a revoke without deleting and returns focus to its trigger", async () => {
    const call = fixture();
    const fixtureKeys = vi.fn(async (path: string, body?: unknown, method?: string) => (path.endsWith("/keys") && !body && !method ? { keys: [{ id: "key-one", name: "ci", created_at: "2026-10-28T00:00:00Z" }] } : call(path, body, method as "GET"))) as unknown as Requester;
    const user = userEvent.setup(); render(<Workspace call={fixtureKeys} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    await user.click(await screen.findByRole("button", { name: "Revoke key ci" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Revoke key ci" })).toHaveFocus();
    expect(vi.mocked(fixtureKeys).mock.calls.some(([, , method]) => method === "DELETE")).toBe(false);
  });

  it("disables through PUT and explicitly re-enables the retained endpoint", async () => {
    let current = endpoint;
    const base = fixture();
    const call = vi.fn(async (path: string, body?: unknown, method?: string) => {
      if (path.endsWith("/endpoints") && !body) return { endpoints: [current] };
      if (path.endsWith("/endpoints/endpoint-one") && method === "PUT") { current = { ...current, ...(body as Partial<Endpoint>) }; return current; }
      return base(path, body, method as "GET" | "POST" | "PUT" | "DELETE" | undefined);
    }) as unknown as Requester;
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Edit Synthetic support" }));
    await user.click(screen.getByRole("button", { name: "Disable endpoint…" }));
    // The confirmation names the endpoint and takes focus on its danger button.
    expect(screen.getByRole("group", { name: "Disable endpoint 'Synthetic support'?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable and revoke keys" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Disable and revoke keys" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one", { name: endpoint.name, provider: endpoint.provider, model: endpoint.model, policy_version_id: endpoint.policy_version_id, enabled: false }, "PUT"));
    await screen.findByText(/· Disabled/);
    await user.click(screen.getByRole("button", { name: "Edit Synthetic support" }));
    await user.click(screen.getByRole("checkbox", { name: "Re-enable this endpoint; create a new endpoint key afterward" }));
    await user.click(screen.getByRole("button", { name: "Save endpoint" }));
    await waitFor(() => expect(call).toHaveBeenLastCalledWith("/v1/projects/project-one/endpoints"));
    expect(current.enabled).toBe(true);
    expect(vi.mocked(call).mock.calls.some(([, , method]) => method === "DELETE")).toBe(false);
  });

  it("does not reset the inspection namespace when the selected project is already valid", async () => {
    const selected = vi.fn(); render(<Workspace call={fixture()} projectId="project-one" onProject={selected} />);
    await screen.findByText("Synthetic support");
    expect(selected).not.toHaveBeenCalled();
  });

  it("closes the Connect & keys panel when an endpoint is opened for editing, and focuses the form", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    expect(screen.getByRole("region", { name: "Connect Synthetic support" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Synthetic support" }));
    expect(screen.getAllByRole("form", { name: "Edit Synthetic support" })).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Connect Synthetic support" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Edit Synthetic support" })).toHaveFocus();
    await user.selectOptions(screen.getByRole("combobox", { name: "Policy version" }), second.policy_version_id);
    expect(screen.getByRole("button", { name: "Save endpoint" })).toBeDisabled();
    expect(screen.getByText("Confirm the policy change below to save.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Edit Synthetic support" })).toHaveFocus();
  });

  it("confirms a created endpoint, announces it and focuses the endpoint list", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Create endpoint" }));
    const form = screen.getByRole("form", { name: "Create endpoint" });
    expect(screen.getByRole("heading", { name: "Create endpoint" })).toHaveFocus();
    await user.type(within(form).getByRole("textbox", { name: "Endpoint name" }), "Support assistant");
    await user.type(within(form).getByRole("textbox", { name: "Model ID" }), "synthetic-model");
    await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Policy version" }), first.policy_version_id);
    await user.click(within(form).getByRole("button", { name: "Create endpoint" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints", expect.objectContaining({ name: "Support assistant", api_key: "sk-test-fictional" }), "POST"));
    expect(await screen.findByText("Endpoint 'Support assistant' created. Next, create an endpoint key so your application can use it.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Gateway endpoints" })).toHaveFocus());
  });

  it("names the page Projects, writes providers and policies as words, and pluralises counts", async () => {
    render(<Workspace call={fixture()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Projects" })).toBeInTheDocument();
    await screen.findByText("Synthetic support");
    expect(screen.getByText(/^OpenAI ·/)).toBeInTheDocument();
    expect(screen.getByText("Hungarian · fast mode · 1 endpoint")).toBeInTheDocument();
    expect(screen.getByText("Hungarian · fast mode · 0 endpoints")).toBeInTheDocument();
  });

  it("preselects the only policy version, and says why Create endpoint waits for a policy", async () => {
    const one = vi.fn(async (path: string) => {
      if (path === "/v1/projects") return { projects: [{ id: "project-one", name: "Local project", default_policy_id: first.policy_id }], default_project_id: "project-one" };
      if (path.endsWith("/policies")) return { policies: [first] };
      if (path.endsWith("/endpoints")) return { endpoints: [] };
      return {};
    }) as unknown as Requester;
    const user = userEvent.setup(); const { unmount } = render(<Workspace call={one} />);
    expect(await screen.findByText(/No endpoints yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create endpoint" }));
    expect(screen.getByRole("combobox", { name: "Policy version" })).toHaveValue(first.policy_version_id);
    unmount();
    const none = vi.fn(async (path: string) => {
      if (path === "/v1/projects") return { projects: [{ id: "project-one", name: "Local project", default_policy_id: first.policy_id }], default_project_id: "project-one" };
      if (path.endsWith("/policies")) return { policies: [] };
      if (path.endsWith("/endpoints")) return { endpoints: [] };
      return {};
    }) as unknown as Requester;
    render(<Workspace call={none} />);
    expect(await screen.findByText(/No policies yet/)).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create endpoint" });
    expect(create).toBeDisabled();
    expect(create).toHaveAccessibleDescription(/Create a policy first/);
  });

  it("shows an empty state for an endpoint without keys", async () => {
    const user = userEvent.setup(); render(<Workspace call={fixture()} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    expect(await screen.findByText(/No endpoint keys yet/)).toBeInTheDocument();
  });

  it("clears one-time key and edits when switching projects", async () => {
    const call = fixture(() => ({ id: "key-one", name: "Synthetic integration", created_at: "2026-10-28T00:00:00Z", key: "synthetic-once-only-key" }));
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "Connect & keys for Synthetic support" }));
    await user.type(screen.getByRole("textbox", { name: "Endpoint key name" }), "Synthetic integration");
    await user.click(screen.getByRole("button", { name: "Create endpoint key" }));
    await screen.findByText("synthetic-once-only-key");
    await user.selectOptions(screen.getByLabelText("Current project"), "project-two");
    expect(screen.queryByText("synthetic-once-only-key")).not.toBeInTheDocument();
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-two/endpoints"));
  });
});
