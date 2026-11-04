import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import { HostedApp } from "./HostedApp";
import GuestPlayground from "./GuestPlayground";
import { createGuestFetch } from "./guestFetch";
import type { Account, Requester } from "./api";
import { setPlaygroundConnection, type HostedSession } from "./session";

// Fictional guest only (LAB-1812).
const guest: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 100, sponsored_enabled: true }, usage: { requests_today: 3, resets_at: new Date(Date.now() + 6 * 3_600_000).toISOString() }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };

const GUEST_PATHS = new Set(["/v1/analyze", "/v1/mask", "/v1/unmask", "/v1/sessions", "/v1/chat/completions"]);

function sse(events: unknown[]) {
  return events.map((e) => `data: ${typeof e === "string" ? e : JSON.stringify(e)}\n\n`).join("");
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** The guard as a guest sees it; `override` answers a path first. */
function guard(override: (path: string) => Response | undefined = () => undefined) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const answered = override(path);
    if (answered) return answered;
    if (path === "/v1/analyze") return json({ spans: [] });
    if (path === "/v1/mask") return json({ masked_text: "[[PERSON_1a2b3c]] wrote.", session_id: "s_guest", entities: [{ entity_type: "PERSON", placeholder: "[[PERSON_1a2b3c]]", count: 1 }] });
    if (path === "/v1/chat/completions") {
      const body = JSON.parse(String(init?.body)) as { messages: { role: string; content: string }[] };
      return new Response(sse([{ object: "pii_guard.masked_request", messages: body.messages }, { choices: [{ delta: { content: "Done." } }] }, "[DONE]"]), { headers: { "content-type": "text/event-stream", "x-pii-guard-session": "s_guest" } });
    }
    return json({ error: { code: "sign_in_required", message: "Sign in with Google to use this endpoint" } }, 401);
  });
}

function account(next: Account = guest) {
  return vi.fn(async (path: string) => {
    if (path === "/v1/account") return next;
    throw new Error(`unexpected ${path}`);
  }) as unknown as Requester & ReturnType<typeof vi.fn>;
}

const consoleStub = vi.fn(() => <p>Console stub</p>);
const renderGuest = (session: HostedSession) => <GuestPlayground session={session} />;

function open(hash: string) {
  history.replaceState(null, "", `/${hash}`);
}

/** Every request the page sent: path, method and headers. */
function sent(fetch: ReturnType<typeof guard>) {
  return fetch.mock.calls.map(([input, init]) => ({ path: String(input), method: init?.method ?? "GET", headers: new Headers(init?.headers), credentials: init?.credentials }));
}

beforeEach(() => {
  // A project and a connection picked earlier in this tab, while signed in: a guest never sends them.
  setSelectedProject("project-one");
  setSelectedEndpoint("ep-one");
  setPlaygroundConnection("conn-one");
});
afterEach(() => {
  vi.unstubAllGlobals();
  setSelectedProject(null);
  setSelectedEndpoint(null);
  setPlaygroundConnection("");
  consoleStub.mockClear();
  open("");
});

describe("the guest Playground (LAB-1812)", () => {
  it("opens for a guest at #playground/text and masks through the guest routes only", async () => {
    const fetch = guard();
    vi.stubGlobal("fetch", fetch);
    open("#playground/text");
    const call = account();
    const user = userEvent.setup();
    render(<HostedApp call={call} console={consoleStub} guest={renderGuest} />);

    expect(await screen.findByRole("heading", { level: 1, name: "Playground" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Sign in to see/ })).toBeNull();
    expect(screen.getByText("Guest session · shared default policy")).toBeInTheDocument();
    expect(screen.getByText("97 of 100 free requests left today")).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/fictional data only/);
    expect(consoleStub).not.toHaveBeenCalled();

    const pane = await screen.findByRole("region", { name: "What the model saw" });
    await user.click(within(pane).getByRole("button", { name: /mask this document/i }));
    await waitFor(() => expect(screen.getByRole("region", { name: "What the model saw" }).textContent).toMatch(/PERSON_1a2b3c/));

    const requests = sent(fetch);
    expect(requests.map((r) => r.path)).toEqual(["/v1/analyze", "/v1/mask"]);
    for (const r of requests) {
      expect(r.method).toBe("POST");
      expect(r.credentials).toBe("same-origin");
      expect(r.headers.has("X-PII-Guard-Project")).toBe(false);
      expect(r.headers.has("X-PII-Guard-Endpoint")).toBe(false);
      expect(r.headers.has("X-PII-Guard-Connection")).toBe(false);
    }
    // The allowance line follows the run.
    await waitFor(() => expect(call.mock.calls.filter(([path]) => path === "/v1/account").length).toBeGreaterThan(1));
  });

  it("chats with the included model, with no model list, connection or project", async () => {
    const fetch = guard();
    vi.stubGlobal("fetch", fetch);
    open("#playground/chat");
    const user = userEvent.setup();
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);

    expect(await screen.findByRole("combobox", { name: "Model" })).toHaveValue("muse-spark-1.3");
    await user.click(screen.getByRole("button", { name: /Send through PII Guard/ }));
    expect(await screen.findByText("Done.")).toBeInTheDocument();

    const requests = sent(fetch);
    expect(requests.map((r) => r.path)).toEqual(["/v1/chat/completions"]);
    expect(requests[0]!.headers.has("X-PII-Guard-Connection")).toBe(false);
    expect(requests[0]!.headers.has("X-PII-Guard-Project")).toBe(false);
    expect(JSON.parse(String(fetch.mock.calls[0]![1]?.body)).model).toBe("muse-spark-1.3");
  });

  it("keeps Images signed-in only, and never asks for an image", async () => {
    const fetch = guard();
    vi.stubGlobal("fetch", fetch);
    open("#playground/images");
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);

    const prompt = await screen.findByRole("region", { name: "Sign in to mask your own images" });
    expect(within(prompt).getByRole("link", { name: "Sign in with Google" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23playground%2Fimages");
    expect(within(prompt).getByRole("link", { name: "See the recorded image example" })).toHaveAttribute("href", "#images");
    expect(screen.getByRole("tab", { name: "Images" })).toHaveAttribute("aria-selected", "true");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("says when today's free requests are used up, with the way to sign in", async () => {
    const fetch = guard((path) => (path === "/v1/analyze" ? json({ error: { code: "quota_exceeded", message: "Daily allowance used" } }, 429) : undefined));
    vi.stubGlobal("fetch", fetch);
    open("#playground/text");
    const user = userEvent.setup();
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);

    const pane = await screen.findByRole("region", { name: "What the model saw" });
    await user.click(within(pane).getByRole("button", { name: /mask this document/i }));
    const notice = (await screen.findByText("Today’s free requests are used up")).closest("[role=alert], [role=status], div")!;
    expect(notice.textContent).toMatch(/resets in 6 h/);
    const links = screen.getAllByRole("link", { name: "Sign in with Google" });
    expect(links.every((l) => l.getAttribute("href") === "/.auth/login/google?post_login_redirect_uri=%2F%23playground%2Ftext")).toBe(true);
  });

  it("names the throttle, and an allowance /v1/account already reports as spent", async () => {
    vi.stubGlobal("fetch", guard((path) => (path === "/v1/mask" ? json({ error: { code: "abuse_throttled", message: "slow down" } }, 429) : undefined)));
    open("#playground/text");
    const user = userEvent.setup();
    const { unmount } = render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);
    const pane = await screen.findByRole("region", { name: "What the model saw" });
    await user.click(within(pane).getByRole("button", { name: /mask this document/i }));
    expect(await screen.findByText("Requests are coming in too fast")).toBeInTheDocument();
    unmount();

    render(<HostedApp call={account({ ...guest, usage: { ...guest.usage, requests_today: 100 } })} console={consoleStub} guest={renderGuest} />);
    expect(await screen.findByText("Today’s free requests are used up")).toBeInTheDocument();
    expect(screen.getByText("0 of 100 free requests left today")).toBeInTheDocument();
  });

  it("says Chat is paused when free answers are off, instead of letting it fail", async () => {
    const fetch = guard();
    vi.stubGlobal("fetch", fetch);
    open("#playground/chat");
    render(<HostedApp call={account({ ...guest, limits: { ...guest.limits, sponsored_enabled: false } })} console={consoleStub} guest={renderGuest} />);
    expect(await screen.findByRole("region", { name: "Chat is paused for guests" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send through PII Guard/ })).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("leaves every other console screen, and an ended session, signed out", async () => {
    vi.stubGlobal("fetch", guard());
    open("#logs");
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in to see your logs" })).toBeInTheDocument();
  });

  it("points guests from the landing demo to the Playground", async () => {
    open("#demo");
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);
    expect(await screen.findByRole("link", { name: "Now try your own text →" })).toHaveAttribute("href", "#playground/text");
  });

  it("leads guests to the Playground from the hero and the menu (LAB-1814)", async () => {
    open("");
    render(<HostedApp call={account()} console={consoleStub} guest={renderGuest} />);
    expect(await screen.findByRole("link", { name: "Try it with your own text" })).toHaveAttribute("href", "#playground/text");
    expect(screen.getByText(/No sign-in · /)).toHaveTextContent("No sign-in · 100 free requests a day · text and chat");
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getAllByRole("link", { name: "Playground" })[0]).toHaveAttribute("href", "#playground/text");
  });
});

describe("createGuestFetch", () => {
  it("sends only the guest routes, POST and same-origin, without owner headers", async () => {
    const network = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>(async () => json({}));
    const answers: unknown[] = [];
    const doFetch = createGuestFetch((limit) => answers.push(limit), network as unknown as typeof fetch);
    for (const path of GUEST_PATHS) await doFetch(path, { method: "POST", headers: { "X-PII-Guard-Project": "p", "X-PII-Guard-Connection": "c", "X-PII-Guard-Endpoint": "e", "X-PII-Guard-Mode": "fast" } });
    expect(network.mock.calls.map(([path]) => path)).toEqual([...GUEST_PATHS]);
    for (const [, init] of network.mock.calls as unknown as [string, RequestInit][]) {
      const headers = new Headers(init.headers);
      expect([headers.has("X-PII-Guard-Project"), headers.has("X-PII-Guard-Connection"), headers.has("X-PII-Guard-Endpoint")]).toEqual([false, false, false]);
      expect(headers.get("X-PII-Guard-Mode")).toBe("fast");
      expect(init.credentials).toBe("same-origin");
    }
    expect(answers).toEqual([null, null, null, null, null]);
  });

  it("refuses owner-only routes without a request", async () => {
    const network = vi.fn(async () => json({}));
    const doFetch = createGuestFetch(() => undefined, network as unknown as typeof fetch);
    const refused = [
      ["/v1/status", "GET"], ["/v1/models", "GET"], ["/v1/projects", "GET"], ["/v1/traffic", "GET"], ["/v1/vault/sessions", "GET"],
      ["/v1/connect/snippets", "GET"], ["/v1/mask/image", "POST"], ["/v1/sessions/s_1/known-values", "POST"], ["/e/ep-one/v1/chat/completions", "POST"],
      ["/v1/mask", "GET"], ["https://elsewhere.example/v1/mask", "POST"],
    ];
    for (const [path, method] of refused) expect((await doFetch(path!, { method })).status).toBe(401);
    expect(network).not.toHaveBeenCalled();
  });
});
