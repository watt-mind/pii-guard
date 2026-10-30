import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { TEXT_ENTITY_TYPES } from "../api/types";
import type { Requester } from "../hosted/api";
import { ENTITY_META } from "../lib/entities";
import { pendingPolicyEdit, requestPolicyEdit, type Endpoint, type PolicyVersion } from "./api";
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

  it("marks the latest policy version and opens a row's panels inside that row (LAB-1619)", async () => {
    const user = userEvent.setup(); render(<Workspace call={fixture()} />);
    await screen.findByText("Synthetic support");
    // Policies exist: no "create a policy first", and a new project name is optional.
    expect(screen.queryByText(/Create a policy first/)).toBeNull();
    expect(screen.getByLabelText("New project name")).not.toBeRequired();
    // One row per policy: its latest version, older versions folded under it (LAB-1626).
    const v2 = screen.getByRole("heading", { name: /Default protection · v2/ });
    expect(within(v2).getByText("Latest")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Default protection · v1/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: /^New version of/ })).toHaveLength(1);
    expect(screen.getByText("Older versions (1)")).toBeInTheDocument();
    // The endpoint pins v1 while v2 exists.
    expect(screen.getByText("v2 available")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit Synthetic support" }));
    const row = screen.getByRole("button", { name: "Edit Synthetic support" }).closest("li")!;
    expect(within(row).getByRole("form", { name: "Edit Synthetic support" })).toBeInTheDocument();
    expect(within(row).getByRole("option", { name: "Default protection · v2 (latest)" })).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Connect & keys for Synthetic support" }));
    expect(within(row).getByRole("region", { name: "Connect Synthetic support" })).toBeInTheDocument();
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

  it("creates a new policy version without updating endpoints with Save only", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} hosted />);
    await user.click(await screen.findByRole("button", { name: "New version of Default protection" }));
    expect(screen.getByText(/Synthetic support \(v1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Save only keeps it on its current version/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Detection mode")).not.toBeInTheDocument();
    // Images: on-device only on hosted; a version saved before visual types shows the defaults.
    expect(screen.getByRole("combobox", { name: "Detection" })).toHaveValue("local");
    expect(screen.getByRole("option", { name: /SAM 3\.1/ })).toBeDisabled();
    expect(screen.getByLabelText("Signature")).toHaveValue("mask");
    expect(screen.getByLabelText("Stamp")).toHaveValue("keep");
    await user.selectOptions(screen.getByLabelText("Email"), "block");
    await user.click(screen.getByRole("button", { name: "Save only" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/policies/policy-family", { name: first.name, language: "hu", mode: "fast", visual_detection: "local", entity_policies: { ...first.entity_policies, EMAIL: "block", FACE: "mask", SIGNATURE: "mask", ID_PHOTO: "mask", STAMP: "keep" } }, "PUT"));
    expect(vi.mocked(call).mock.calls.filter(([path, body]) => path.includes("/endpoints/") && body)).toHaveLength(0);
  });

  it("saves a version from Connect's Tune and applies it to that endpoint (LAB-1629)", async () => {
    const third = { ...second, policy_version_id: "version-three", version: 3 };
    const call = fixture((path) => (path.includes("/policies/") ? third : endpoint));
    requestPolicyEdit(first.policy_id, endpoint.id);
    const user = userEvent.setup(); render(<Workspace call={call} hosted />);
    const form = await screen.findByRole("form", { name: "New version of Default protection" });
    await user.selectOptions(within(form).getByLabelText("Email"), "keep");
    await user.click(within(form).getByRole("button", { name: "Save and apply to 'Synthetic support'" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one", { name: endpoint.name, provider: "openai", model: "synthetic-model", policy_version_id: "version-three", enabled: true }, "PUT"));
    expect(await screen.findByText("Policy 'Default protection' v3 saved and applied to 'Synthetic support'. The next request uses it.")).toBeInTheDocument();
  });

  it("applies a newer policy version from the endpoint row, and deletes a disabled endpoint (LAB-1629)", async () => {
    const off: Endpoint = { ...endpoint, id: "endpoint-off", name: "Old integration", enabled: false };
    const base = fixture();
    const call = vi.fn(async (path: string, body?: unknown, method?: string) => {
      if (path.endsWith("/endpoints") && !body) return { endpoints: [endpoint, off] };
      return base(path, body, method as "GET");
    }) as unknown as Requester;
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await screen.findByText("Synthetic support");
    // A disabled endpoint offers no newer version, only Delete.
    expect(screen.queryByRole("button", { name: "Apply v2 to Old integration" })).toBeNull();
    expect(screen.getAllByText("v2 available")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Apply v2 to Synthetic support" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one", expect.objectContaining({ policy_version_id: "version-two", enabled: true }), "PUT"));
    await user.click(await screen.findByRole("button", { name: "Delete Old integration" }));
    await user.click(screen.getByRole("button", { name: "Delete endpoint" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-off", undefined, "DELETE"));
    // Let the reload and its focus move finish inside this test.
    expect(await screen.findByText("Endpoint 'Old integration' deleted.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Gateway endpoints" })).toHaveFocus());
  });

  it("asks before Escape discards an edited form, and closes an untouched one (LAB-1629)", async () => {
    const user = userEvent.setup(); render(<Workspace call={fixture()} />);
    await user.click(await screen.findByRole("button", { name: "New version of Default protection" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form", { name: "New version of Default protection" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "New version of Default protection" }));
    const form = screen.getByRole("form", { name: "New version of Default protection" });
    await user.selectOptions(within(form).getByLabelText("Email"), "keep");
    await user.keyboard("{Escape}");
    expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(within(form).getByLabelText("Email")).toHaveValue("keep");
    await waitFor(() => expect(within(form).getByLabelText("Email")).toHaveFocus());
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.queryByRole("form", { name: "New version of Default protection" })).toBeNull();
  });

  it("sets image actions and SAM 3.1 detection, and warns that on-device detection cannot mask stamps", async () => {
    const call = fixture(); const user = userEvent.setup(); render(<Workspace call={call} />);
    await user.click(await screen.findByRole("button", { name: "New version of Default protection" }));
    const form = screen.getByRole("form", { name: "New version of Default protection" });
    expect(within(form).getByText(/found on the guard's CPU/)).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Stamp"), "mask");
    expect(within(form).getByRole("alert")).toHaveTextContent(/cannot find stamps/);
    await user.selectOptions(within(form).getByRole("combobox", { name: "Detection" }), "sam");
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();
    expect(within(form).getByText(/original image is sent to Meta's API/)).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Signature"), "keep");
    await user.click(within(form).getByRole("button", { name: "Save only" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/policies/policy-family", expect.objectContaining({ visual_detection: "sam", entity_policies: expect.objectContaining({ SIGNATURE: "keep", STAMP: "mask", FACE: "mask" }) }), "PUT"));
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
    // Revoked keys move out of the active list, into their own folded list (LAB-1626).
    const list = await screen.findByRole("list", { name: "Revoked endpoint keys" });
    expect(within(list).getByText("Synthetic integration")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Endpoint keys" })).not.toBeInTheDocument();
    expect(screen.getByText("Show 1 revoked key")).toBeInTheDocument();
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
    await screen.findByText("Disabled");
    // A disabled endpoint has no keys to manage (LAB-1626).
    expect(screen.queryByRole("button", { name: "Connect & keys for Synthetic support" })).not.toBeInTheDocument();
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
    await user.type(within(form).getByRole("textbox", { name: "Model (optional)" }), "synthetic-model");
    await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Policy version" }), first.policy_version_id);
    await user.click(within(form).getByRole("button", { name: "Create endpoint" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints", expect.objectContaining({ name: "Support assistant", api_key: "sk-test-fictional" }), "POST"));
    expect(await screen.findByText("Endpoint 'Support assistant' created. Next, create an endpoint key so your application can use it.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Gateway endpoints" })).toHaveFocus());
  });

  it("closes an inline form with Escape and returns focus to its row's button (LAB-1626)", async () => {
    const user = userEvent.setup(); render(<Workspace call={fixture()} />);
    await user.click(await screen.findByRole("button", { name: "Edit Synthetic support" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form", { name: "Edit Synthetic support" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Synthetic support" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "New version of Default protection" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form", { name: "New version of Default protection" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New version of Default protection" })).toHaveFocus();
  });

  it("lists active keys newest first, revoked ones folded apart, and disabled endpoints last (LAB-1626)", async () => {
    const off: Endpoint = { ...endpoint, id: "endpoint-off", name: "Old integration", enabled: false };
    const keys = [
      { id: "k1", name: "oldest", created_at: "2026-10-01T00:00:00Z" },
      { id: "k2", name: "gone", created_at: "2026-10-02T00:00:00Z", revoked_at: "2026-10-03T00:00:00Z" },
      { id: "k3", name: "newest", created_at: "2026-10-04T00:00:00Z" },
    ];
    const base = fixture();
    const call = vi.fn(async (path: string, body?: unknown, method?: string) => {
      if (path.endsWith("/endpoints") && !body) return { endpoints: [off, endpoint] };
      if (path.endsWith("/keys") && !body && !method) return { keys };
      return base(path, body, method as "GET");
    }) as unknown as Requester;
    const user = userEvent.setup(); render(<Workspace call={call} />);
    await screen.findByText("Synthetic support");
    const names = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(names.indexOf("Synthetic support")).toBeLessThan(names.indexOf("Old integrationDisabled"));
    await user.click(screen.getByRole("button", { name: "Connect & keys for Synthetic support" }));
    const active = await screen.findByRole("list", { name: "Endpoint keys" });
    expect(within(active).getAllByRole("listitem").map((li) => li.querySelector("p")?.firstChild?.textContent)).toEqual(["newest", "oldest"]);
    expect(within(screen.getByRole("list", { name: "Revoked endpoint keys" })).getByText("gone")).toBeInTheDocument();
  });

  it("opens a new version of the policy Connect asked to tune, with its form focused (LAB-1626)", async () => {
    requestPolicyEdit(first.policy_id);
    render(<Workspace call={fixture()} />);
    expect(await screen.findByRole("form", { name: "New version of Default protection" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New version of Default protection" })).toHaveFocus();
    expect(pendingPolicyEdit()).toBeNull();
  });

  it("names the page Projects, writes providers and policies as words, and pluralises counts", async () => {
    render(<Workspace call={fixture()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Projects" })).toBeInTheDocument();
    await screen.findByText("Synthetic support");
    expect(screen.getByText(/^OpenAI ·/)).toBeInTheDocument();
    // The family row counts every endpoint on any of its versions; the older version, its own.
    expect(screen.getByText("Hungarian · fast mode · 1 endpoint · 2 versions")).toBeInTheDocument();
    expect(screen.getByText((_, el) => el?.tagName === "LI" && el.textContent === "v1 · Hungarian · fast mode · 1 endpoint")).toBeInTheDocument();
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

  describe("endpoint model (LAB-1451)", () => {
    const catalogFixture = (models: string[] | Error) => fixture((path, body) => {
      if (path.endsWith("/endpoints/models")) { if (models instanceof Error) throw models; return { models }; }
      return { ...endpoint, ...(body as object) };
    });
    async function openCreate(call: Requester, hosted = false) {
      const user = userEvent.setup(); render(<Workspace call={call} hosted={hosted} />);
      await user.click(await screen.findByRole("button", { name: "Create endpoint" }));
      const form = screen.getByRole("form", { name: "Create endpoint" });
      await user.type(within(form).getByRole("textbox", { name: "Endpoint name" }), "Agent endpoint");
      await user.selectOptions(within(form).getByRole("combobox", { name: "Policy version" }), first.policy_version_id);
      return { user, form };
    }

    it("makes the model optional for an own key: empty sends null (pass-through)", async () => {
      const call = catalogFixture([]); const { user, form } = await openCreate(call);
      const field = within(form).getByRole("textbox", { name: "Model (optional)" });
      expect(field).not.toBeRequired();
      expect(within(form).getByText("Leave empty to let your client choose, e.g. Codex or Muse Code.")).toBeInTheDocument();
      expect(within(form).getByRole("button", { name: "Load models from OpenAI" })).toBeDisabled();
      expect(within(form).getByText("Enter the provider API key to load models.")).toBeInTheDocument();
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
      expect(within(form).getByRole("button", { name: "Load models from OpenAI" })).toBeEnabled();
      expect(within(form).queryByText("Enter the provider API key to load models.")).not.toBeInTheDocument();
      await user.click(within(form).getByRole("button", { name: "Create endpoint" }));
      await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints", expect.objectContaining({ name: "Agent endpoint", model: null, api_key: "sk-test-fictional" }), "POST"));
    });

    it("loads the provider's models with the typed key into a dropdown with a free-text option", async () => {
      const call = catalogFixture(["synthetic-a", "synthetic-b"]); const { user, form } = await openCreate(call);
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
      await user.click(within(form).getByRole("button", { name: "Load models from OpenAI" }));
      expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/models", { provider: "openai", api_key: "sk-test-fictional" }, "POST");
      const select = await within(form).findByRole("combobox", { name: "Model (optional)" });
      expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Client chooses (no pinned model)", "synthetic-a", "synthetic-b", "Other model ID…"]);
      expect(within(form).getByText("Pick ‘Client chooses’ to let Codex or Muse Code send their own model.")).toBeInTheDocument();
      await user.selectOptions(select, "synthetic-b");
      await user.click(within(form).getByRole("button", { name: "Create endpoint" }));
      await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints", expect.objectContaining({ model: "synthetic-b" }), "POST"));
    });

    it("switches to typing another model ID, and back to the list", async () => {
      const call = catalogFixture(["synthetic-a"]); const { user, form } = await openCreate(call);
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
      await user.click(within(form).getByRole("button", { name: "Load models from OpenAI" }));
      await user.selectOptions(await within(form).findByRole("combobox", { name: "Model (optional)" }), "Other model ID…");
      await user.type(within(form).getByRole("textbox", { name: "Model (optional)" }), "synthetic-typed");
      await user.click(within(form).getByRole("button", { name: "Choose from the list" }));
      expect(within(form).getByRole("combobox", { name: "Model (optional)" })).toHaveValue("synthetic-typed");
    });

    it("says when the provider did not list its models and keeps free text", async () => {
      const call = catalogFixture(new ApiError(502, "upstream_unavailable", "Provider model catalog unavailable")); const { user, form } = await openCreate(call);
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
      await user.click(within(form).getByRole("button", { name: "Load models from OpenAI" }));
      expect(await within(form).findByText("OpenAI did not list its models. Type a model ID, or leave it empty.")).toBeInTheDocument();
      expect(within(form).getByRole("textbox", { name: "Model (optional)" })).toBeInTheDocument();
    });

    it("asks to check the API key when the provider refuses it", async () => {
      const call = catalogFixture(new ApiError(502, "upstream_credential_rejected", "The provider refused the API key")); const { user, form } = await openCreate(call);
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-wrong");
      await user.click(within(form).getByRole("button", { name: "Load models from OpenAI" }));
      expect(await within(form).findByText(/OpenAI refused the API key\. Check the API key/)).toBeInTheDocument();
    });

    it("names a custom provider's load button for its endpoint and waits for its base URL", async () => {
      const call = catalogFixture(["synthetic-a"]); const { user, form } = await openCreate(call);
      await user.selectOptions(within(form).getByRole("combobox", { name: "Provider" }), "custom");
      await user.type(within(form).getByLabelText(/^Provider API key/), "sk-test-fictional");
      expect(within(form).getByRole("button", { name: "Load models from this endpoint" })).toBeDisabled();
      expect(within(form).getByText("Enter the base URL and provider API key to load models.")).toBeInTheDocument();
      await user.type(within(form).getByLabelText(/^Upstream base URL/), "https://models.example.com/v1");
      await user.click(within(form).getByRole("button", { name: "Load models from this endpoint" }));
      expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/models", { provider: "custom", base_url: "https://models.example.com/v1", api_key: "sk-test-fictional" }, "POST");
    });

    it("edits with the stored key: asks by endpoint id and keeps the pinned model listed", async () => {
      const call = catalogFixture(["synthetic-a"]); const user = userEvent.setup(); render(<Workspace call={call} />);
      await user.click(await screen.findByRole("button", { name: "Edit Synthetic support" }));
      await user.click(screen.getByRole("button", { name: "Load models from OpenAI" }));
      expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/models", { provider: "openai", endpoint_id: "endpoint-one" }, "POST");
      const select = await screen.findByRole("combobox", { name: "Model (optional)" });
      expect(select).toHaveValue("synthetic-model");
      await user.selectOptions(select, "");
      await user.click(screen.getByRole("button", { name: "Save endpoint" }));
      await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/endpoint-one", expect.objectContaining({ model: null }), "PUT"));
    });

    it("offers sponsored Meta only its allowed models, and requires one", async () => {
      const call = catalogFixture(["muse-spark-1.3", "muse-spark-1.2"]); const { user, form } = await openCreate(call, true);
      expect(within(form).getByRole("combobox", { name: "Provider" })).toHaveValue("sponsored");
      const select = await within(form).findByRole("combobox", { name: "Model" });
      expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints/models", { provider: "sponsored" }, "POST");
      expect(select).toBeRequired();
      expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["muse-spark-1.3", "muse-spark-1.2"]);
      expect(within(form).queryByText(/Leave empty/)).not.toBeInTheDocument();
      await user.selectOptions(select, "muse-spark-1.2");
      await user.click(within(form).getByRole("button", { name: "Create endpoint" }));
      await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects/project-one/endpoints", expect.objectContaining({ provider: "sponsored", model: "muse-spark-1.2" }), "POST"));
    });

    it("shows a pass-through endpoint as client-chosen with a placeholder in its snippet", async () => {
      const passThrough = { ...endpoint, model: null };
      const call = vi.fn(async (path: string) => (path.endsWith("/endpoints") ? { endpoints: [passThrough] } : (fixture() as unknown as (p: string) => Promise<unknown>)(path))) as unknown as Requester;
      const user = userEvent.setup(); render(<Workspace call={call} />);
      expect(await screen.findByText(/Client chooses the model/)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Connect & keys for Synthetic support" }));
      const panel = screen.getByRole("region", { name: "Connect Synthetic support" });
      expect(within(panel).getByText(/model="<model-id>"/)).toBeInTheDocument();
      expect(within(panel).getByText(/has no pinned model/)).toHaveTextContent("for example gpt-4.1-mini");
    });
  });
});

it("creates the first project after a successful empty list", async () => {
  const user = userEvent.setup();
  const onProject = vi.fn();
  const call = vi.fn(async (_path: string, body?: unknown) => body ? { id: "new", name: "Synthetic first", default_policy_id: "default" } : { projects: [], default_project_id: null }) as unknown as Requester;
  render(<Workspace hosted call={call} onProject={onProject} />);
  await screen.findByText(/No projects yet/);
  expect(screen.queryByText(/Loading your default project/)).toBeNull();
  await user.type(screen.getByLabelText(/New project name/), "Synthetic first");
  await user.click(screen.getByRole("button", { name: "Create project" }));
  await waitFor(() => expect(onProject).toHaveBeenCalledWith(expect.objectContaining({ id: "new" })));
});
