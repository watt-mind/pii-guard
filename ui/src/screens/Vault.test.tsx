// The Vault screen (LAB-1328): session list, detail, reveal only in full mode, drop.
// Fictional data only.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import type { ServerStatus } from "../api/status";
import { createVaultClient, type VaultClient, type VaultSessionDetail, type VaultSessionSummary } from "../api/vault";
import { Vault } from "./Vault";
import { HostedSessionContext, type HostedSession } from "../hosted/session";
import { getSelectedEndpoint, setSelectedEndpoint, setSelectedProject } from "../projects/selection";

const NOW = new Date().toISOString();
const SESSIONS: VaultSessionSummary[] = [
  {
    ref: "s_1111aaaa2222bbbb",
    source: "path",
    client: "anonymous",
    created: NOW,
    last_used: NOW,
    ttl_left_seconds: 3500,
    generation: 4,
    entries: 2,
    occurrences: 4,
    known_values: 0,
    entity_counts: { EMAIL: 1, PERSON: 1 },
  },
  {
    ref: "s_3333cccc4444dddd",
    source: "api",
    client: null,
    created: null,
    last_used: NOW,
    ttl_left_seconds: 1200,
    generation: 1,
    entries: 1,
    occurrences: 1,
    known_values: 1,
    entity_counts: { PHONE: 1 },
  },
];

function detailOf(ref: string, reveal: boolean, mode: "masked" | "full"): VaultSessionDetail {
  const base = SESSIONS.find((s) => s.ref === ref)!;
  return {
    ...base,
    mode,
    revealed: reveal,
    session_id: reveal ? "d_0123456789abcdef0123456789abcdef" : null,
    items: [
      {
        placeholder: "[[PERSON_7f3a9c]]",
        entity_type: "PERSON",
        origin: "detected",
        count: 3,
        forms: 1,
        variant_of: null,
        hint: "T•••• E•••",
        ...(reveal ? { original: "Teszt Elek", known_forms: ["Teszt Eleké"] } : {}),
      },
      {
        placeholder: "[[EMAIL_1b2c3d]]",
        entity_type: "EMAIL",
        origin: "known",
        count: 1,
        forms: 0,
        variant_of: null,
        hint: "t••••.e•••@e••••••.c••",
        ...(reveal ? { original: "teszt.elek@example.com", known_forms: [] } : {}),
      },
    ],
  };
}

function fakeClient(mode: "masked" | "full" = "masked") {
  let sessions = [...SESSIONS];
  const client = {
    list: vi.fn(() => Promise.resolve({ mode, ttl_seconds: 3600, sessions })),
    detail: vi.fn((ref: string, reveal = false) => {
      if (!sessions.some((s) => s.ref === ref)) return Promise.reject(new ApiError(404, "not_found", "no live vault session has this ref"));
      if (reveal && mode !== "full") return Promise.reject(new ApiError(403, "vault_reveal_disabled", "no"));
      return Promise.resolve(detailOf(ref, reveal, mode));
    }),
    drop: vi.fn((ref: string) => {
      sessions = sessions.filter((s) => s.ref !== ref);
      return Promise.resolve();
    }),
  } satisfies VaultClient;
  return client;
}

const statusOf = (vault_inspect: "off" | "masked" | "full" | undefined) => ({ state: "ok" as const, status: { vault_inspect } as unknown as ServerStatus });

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("Vault", () => {
  it("lists sessions with their source, filters them and opens one with hints only", async () => {
    const client = fakeClient("masked");
    const user = userEvent.setup();
    render(<Vault status={statusOf("masked")} live active client={client} />);
    const list = await screen.findByRole("list", { name: "Vault sessions" });
    await waitFor(() => expect(within(list).getAllByRole("button")).toHaveLength(2));
    expect(within(list).getByText(/URL path · 2 placeholders/)).toBeInTheDocument();
    expect(within(list).getByText(/REST API · 1 placeholder · 1 known/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Source"), "api");
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    await user.selectOptions(screen.getByLabelText("Source"), "all");
    await user.type(screen.getByLabelText("Search by session ref"), "1111");
    expect(within(list).getAllByRole("button")).toHaveLength(1);

    await user.click(within(list).getByRole("button", { name: /s_1111aaaa2222bbbb/ }));
    const detail = screen.getByRole("region", { name: "Session detail" });
    expect(await within(detail).findByText("T•••• E•••")).toBeInTheDocument();
    expect(within(detail).getByText("[[PERSON_7f3a9c]]")).toBeInTheDocument();
    expect(within(detail).getByRole("cell", { name: "Known value" })).toBeInTheDocument();
    // masked: no reveal control, never a value
    expect(within(detail).queryByRole("button", { name: /Reveal values/ })).toBeNull();
    expect(document.body).not.toHaveTextContent("Teszt Elek");
    expect(client.detail).toHaveBeenCalledWith("s_1111aaaa2222bbbb", false);
    expect(client.detail).not.toHaveBeenCalledWith(expect.anything(), true);
  });

  it("reveals on demand in full mode, hides again and stores nothing", async () => {
    const client = fakeClient("full");
    const user = userEvent.setup();
    const { rerender } = render(<Vault status={statusOf("full")} live active client={client} />);
    await user.click(await screen.findByRole("button", { name: /s_1111aaaa2222bbbb/ }));
    const reveal = await screen.findByRole("button", { name: "Reveal values" });
    expect(document.body).not.toHaveTextContent("Teszt Elek");

    await user.click(reveal);
    expect(await screen.findByText("Teszt Elek")).toBeInTheDocument();
    expect(screen.getByText(/also Teszt Eleké/)).toBeInTheDocument();
    expect(screen.getByText(/id d_0123/)).toBeInTheDocument();
    expect(client.detail).toHaveBeenLastCalledWith("s_1111aaaa2222bbbb", true);
    expect(JSON.stringify({ ...localStorage })).not.toContain("Teszt");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("Teszt");

    await user.click(screen.getByRole("button", { name: "Hide values" }));
    await waitFor(() => expect(document.body).not.toHaveTextContent("Teszt Elek"));

    // Reveal, then leave the section: the values are gone and fetched again only on demand.
    await user.click(screen.getByRole("button", { name: "Reveal values" }));
    await screen.findByText("Teszt Elek");
    rerender(<Vault status={statusOf("full")} live active={false} client={client} />);
    await waitFor(() => expect(document.body).not.toHaveTextContent("Teszt Elek"));
    expect(client.detail).toHaveBeenLastCalledWith("s_1111aaaa2222bbbb", false);
  });

  it("reloads the open session when the list shows it changed, keeping the reveal", async () => {
    const client = fakeClient("full");
    const user = userEvent.setup();
    render(<Vault status={statusOf("full")} live active client={client} refreshMs={50} />);
    await user.click(await screen.findByRole("button", { name: /s_1111aaaa2222bbbb/ }));
    await user.click(await screen.findByRole("button", { name: "Reveal values" }));
    await screen.findByText("Teszt Elek");
    const calls = client.detail.mock.calls.length;
    client.list.mockImplementation(() =>
      Promise.resolve({ mode: "full" as const, ttl_seconds: 3600, sessions: SESSIONS.map((x) => (x.ref === "s_1111aaaa2222bbbb" ? { ...x, occurrences: 9 } : x)) }),
    );
    await waitFor(() => expect(client.detail.mock.calls.length).toBeGreaterThan(calls));
    expect(client.detail).toHaveBeenLastCalledWith("s_1111aaaa2222bbbb", true);
    expect(screen.getByText("Teszt Elek")).toBeInTheDocument();
  });

  it("drops a session after a confirmation", async () => {
    const client = fakeClient("masked");
    const user = userEvent.setup();
    render(<Vault status={statusOf("masked")} live active client={client} />);
    await user.click(await screen.findByRole("button", { name: /s_3333cccc4444dddd/ }));
    const trigger = await screen.findByRole("button", { name: "Drop session s_3333cccc4444dddd" });
    await user.click(trigger);
    expect(client.drop).not.toHaveBeenCalled();
    // The confirmation names the session, and its danger button takes focus.
    expect(screen.getByRole("group", { name: /Drop session s_3333cccc4444dddd\?/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Drop session" })).toHaveFocus();
    // Cancel returns focus to the trigger.
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Drop session s_3333cccc4444dddd" })).toHaveFocus();
    expect(client.drop).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Drop session s_3333cccc4444dddd" }));
    await user.click(screen.getByRole("button", { name: "Drop session" }));
    expect(client.drop).toHaveBeenCalledWith("s_3333cccc4444dddd");
    expect(await screen.findByRole("status")).toHaveTextContent(/Dropped session s_3333cccc4444dddd/);
    // Focus moves to the list it changed, not to <body>.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sessions" })).toHaveFocus());
    await waitFor(() => expect(screen.queryByRole("button", { name: /s_3333cccc4444dddd/ })).toBeNull());
  });

  it("opens the session a Logs row links to", async () => {
    const client = fakeClient("masked");
    render(<Vault status={statusOf("masked")} live active client={client} focus={{ ref: "s_3333cccc4444dddd", nonce: 1 }} />);
    expect(await screen.findByRole("heading", { name: /Session s_3333cccc4444dddd/ })).toBeInTheDocument();
  });

  it("says why it can't inspect: inspector off, demo mode", async () => {
    const client = fakeClient();
    const { rerender } = render(<Vault status={statusOf("off")} live active client={client} />);
    expect(screen.getByRole("status")).toHaveTextContent(/inspector is off/);
    rerender(<Vault status={{ state: "offline" }} live={false} active client={client} />);
    expect(screen.getByRole("status")).toHaveTextContent(/needs the live API/);
    expect(client.list).not.toHaveBeenCalled();
  });
});

describe("hosted Vault (LAB-1619)", () => {
  const session = { account: {}, error: "", refresh: async () => {}, call: vi.fn() } as unknown as HostedSession;

  afterEach(() => {
    vi.unstubAllGlobals();
    setSelectedEndpoint(null);
  });

  it("says where an endpoint's sessions are, offers the one endpoint, and never mentions demo traffic", async () => {
    setSelectedProject("project-one");
    const doFetch = vi.fn(async () =>
      new Response(JSON.stringify({ endpoints: [{ id: "ep-one", name: "Default endpoint", enabled: true }] }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", doFetch);
    const client = { list: vi.fn(() => Promise.resolve({ mode: "masked", ttl_seconds: 3600, sessions: [] })), detail: vi.fn(), drop: vi.fn() } as unknown as VaultClient;
    render(
      <HostedSessionContext.Provider value={session}>
        <Vault status={statusOf("masked")} live active client={client} />
      </HostedSessionContext.Provider>,
    );
    expect(await screen.findByText(/No sessions in this view\./)).toBeInTheDocument();
    expect(screen.queryByText(/Send demo traffic/)).toBeNull();
    expect(screen.getByText(/originals are never shown on the hosted service/)).toBeInTheDocument();
    expect(screen.queryByText(/localhost/)).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: "Show the sessions of Default endpoint" }));
    expect(getSelectedEndpoint()).toBe("ep-one");
  });
});

describe("createVaultClient", () => {
  it("calls the routes by ref, never caches, and maps contract errors", async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const responses = [
      new Response(JSON.stringify({ mode: "masked", ttl_seconds: 3600, sessions: [] }), { status: 200 }),
      new Response(JSON.stringify({ error: { code: "vault_reveal_disabled", message: "needs full" } }), { status: 403 }),
      new Response(null, { status: 204 }),
    ];
    const doFetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return Promise.resolve(responses.shift()!);
    }) as unknown as typeof fetch;
    const client = createVaultClient({ fetch: doFetch });
    expect((await client.list()).sessions).toEqual([]);
    await expect(client.detail("s_ab", true)).rejects.toMatchObject({ code: "vault_reveal_disabled", status: 403 });
    await client.drop("s_ab");
    expect(calls.map(([u, i]) => `${i?.method} ${u}`)).toEqual(["GET /v1/vault/sessions", "GET /v1/vault/sessions/s_ab?reveal=true", "DELETE /v1/vault/sessions/s_ab"]);
    expect(calls.every(([, i]) => i?.cache === "no-store")).toBe(true);
  });
});
