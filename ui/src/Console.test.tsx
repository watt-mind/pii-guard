// The console shell (LAB-1287): sections, old links, Overview, Connect, Policy, and the folded-in
// fixes (LAB-1261, LAB-1264, LAB-1291, LAB-1294). Fictional data only.

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { ChatClient, ChatTurnRequest } from "./api/chat";
import { createMockChat } from "./api/chat";
import type { HttpGuardClient } from "./api/http";
import { UnreachableError } from "./api/http";
import { createMockClient } from "./api/mock";
import type { ServerStatus, StatusResult } from "./api/status";
import { parseTrafficEvent, type TrafficConnectOptions, type TrafficEvent, type TrafficStatus } from "./api/traffic";
import { totalMasked } from "./lib/traffic";
import full from "./test/trafficFull.json";

const EVENTS = (full.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];

const STATUS: ServerStatus = {
  version: "0.1.0",
  gateway: {
    url: "http://127.0.0.1:8899/v1",
    default_mode: "fast",
    modes: {
      fast: { detectors: ["rules"], available: true, reason: null },
      audit: {
        detectors: ["rules", "llm"],
        available: false,
        reason: "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY: the LLM detector has no key, so no text was sent",
        model: "meta-models/muse-spark-open-1026",
      },
    },
  },
  rest: { detectors: ["rules"] },
  ner: { available: false, model: null },
  upstream: { configured: true, mock: true, origin: null },
  images: { segmenter: "hybrid", sam: false, ocr_required: true, gaps: ["segmenter"], available: false },
  policies: { PERSON: "mask", EMAIL: "block", ORGANIZATION: "keep", SECRET: "mask" },
  auth: { token_required: false },
  default_language: "hu",
  traffic_log: "masked",
  metrics: false,
};

const statusOf = (overrides: Partial<ServerStatus> = {}) => vi.fn((): Promise<StatusResult> => Promise.resolve({ state: "ok", status: { ...STATUS, ...overrides } }));

function liveApi(): HttpGuardClient {
  const backend = createMockClient();
  return { health: () => Promise.resolve({ status: "ok", version: "0.1.0" }), analyze: backend.analyze, mask: backend.mask, unmask: backend.unmask };
}

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down };
}

/** A fake traffic connection the test drives, as the server would. */
function fakeConnect() {
  let opts: TrafficConnectOptions | null = null;
  const connect = vi.fn((o: TrafficConnectOptions) => {
    opts = o;
    return { close: vi.fn() };
  });
  const push = (events: TrafficEvent[], status: TrafficStatus = { state: "live", via: "sse", level: "masked", size: 200 }) =>
    act(() => {
      opts!.onStatus(status);
      if (events.length) opts!.onEvents(events);
    });
  return { connect, push, ready: () => waitFor(() => expect(opts).not.toBeNull()) };
}

const region = (name: string) => screen.getByRole("region", { name });

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, "", location.pathname);
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("console shell", () => {
  it("opens on the Overview, with seven sections in the sidebar", async () => {
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect }} loadStatus={statusOf()} />);
    const nav = screen.getByRole("navigation", { name: "Console" });
    expect(within(nav).getAllByRole("link")).toHaveLength(7);
    for (const name of ["Overview", "Playground", "Logs", "Vault", "Connect", "Policy", "Evaluation"]) expect(within(nav).getByRole("link", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /^Overview/ })).toHaveAttribute("aria-current", "page");
    expect(region("Overview")).toBeVisible();
  });

  it.each([
    ["#traffic", "Logs", "#logs"],
    ["#benchmarks", "Evaluation", "#evaluation"],
    ["#mask", "Playground", "#playground/text"],
    ["#chat", "Playground", "#playground/chat"],
    ["#images", "Playground", "#playground/images"],
  ])("redirects the old link %s to %s", async (old, section, now) => {
    history.replaceState(null, "", old);
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} loadStatus={statusOf()} />);
    expect(region(section)).toBeVisible();
    expect(location.hash).toBe(now);
  });

  it("switches sections on a hash change, also away from Images (LAB-1294)", async () => {
    history.replaceState(null, "", "#playground/images");
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} loadStatus={statusOf()} />);
    expect(screen.getByRole("tab", { name: "Images" })).toHaveAttribute("aria-selected", "true");
    act(() => {
      history.replaceState(null, "", "#logs");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(region("Logs")).toBeVisible();
    act(() => {
      history.replaceState(null, "", "#chat");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
    expect(location.hash).toBe("#playground/chat");
    // The skip link's #main is not a route: the section stays.
    act(() => {
      history.replaceState(null, "", "#main");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");
  });

  it("adds a history entry per section, so Back returns to the previous one", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} loadStatus={statusOf()} />);
    const before = history.length;
    const nav = screen.getByRole("navigation", { name: "Console" });
    await user.click(within(nav).getByRole("link", { name: /^Logs/ }));
    await user.click(within(nav).getByRole("link", { name: /^Policy/ }));
    expect(history.length).toBe(before + 2);
    expect(location.hash).toBe("#policy");
  });

  it("collapses the navigation into a menu that closes on a pick and on Escape", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} loadStatus={statusOf()} />);
    const menu = screen.getByRole("button", { name: "Menu" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await user.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    await user.click(within(screen.getByRole("navigation", { name: "Console" })).getByRole("link", { name: /^Connect/ }));
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(location.hash).toBe("#connect");
    await user.click(menu);
    await user.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
  });
});

describe("Overview", () => {
  it("shows an honest empty state when nothing has gone through the gateway", async () => {
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect }} loadStatus={statusOf()} />);
    await f.ready();
    f.push([]);
    const overview = region("Overview");
    expect(await within(overview).findByText("Nothing has gone through the gateway yet.")).toBeInTheDocument();
    expect(within(overview).getByRole("link", { name: "Connect a client" })).toHaveAttribute("href", "#connect");
    expect(within(overview).getByRole("button", { name: "Watch a recorded demo" })).toBeInTheDocument();
    expect(within(overview).queryByRole("list", { name: /counters/i })).toBeNull();
    expect(within(overview).queryByText("Requests")).toBeNull();
    expect(await within(overview).findByText("http://127.0.0.1:8899/v1")).toBeInTheDocument();
  });

  it("counts real calls: requests, values masked, blocked, top types and stage latency", async () => {
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect }} loadStatus={statusOf()} />);
    await f.ready();
    f.push(EVENTS);
    const counters = within(region("Overview")).getByLabelText("Counters");
    const value = (label: string) => within(counters).getByText(label).closest("div")!.querySelector("dd")!.textContent;
    expect(value("Requests")).toBe(String(EVENTS.length));
    expect(value("Values masked")).toBe(String(EVENTS.reduce((n, e) => n + totalMasked(e), 0)));
    expect(value("Requests blocked")).toBe(String(EVENTS.filter((e) => e.outcome === "blocked" || e.outcome === "refused").length));
    const types = within(region("Overview")).getByRole("region", { name: "Top entity types" });
    expect(within(types).getAllByRole("listitem")[0]).toHaveTextContent(/^(Bank account|Email|Phone)2$/);
    const stages = within(region("Overview")).getByRole("region", { name: "Latency per stage" });
    expect(within(stages).getByRole("rowheader", { name: "Detect" })).toBeInTheDocument();
    expect(within(region("Overview")).getByText(/Detectors seen in the shown calls\. Fast: Rules \+ Image pipeline\./)).toBeInTheDocument();
  });

  it("labels the recorded demo as recorded, never as the server's numbers", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect, fixtureIntervalMs: 60_000 }} loadStatus={statusOf()} />);
    await f.ready();
    f.push([]);
    await user.click(await within(region("Overview")).findByRole("button", { name: "Watch a recorded demo" }));
    expect(within(region("Overview")).getByText("Recorded demo traffic, not your server.")).toBeInTheDocument();
    expect(within(region("Overview")).getByLabelText("Counters of the recorded demo traffic")).toBeInTheDocument();
  });

  it("reports the mock upstream, the mode, and that rules alone miss names (LAB-1291)", async () => {
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect }} loadStatus={statusOf()} />);
    const overview = region("Overview");
    expect(await within(overview).findByText("Offline mock model")).toBeInTheDocument();
    expect(within(overview).getByText("Rules only: free-text names are not masked.")).toBeInTheDocument();
    expect(within(overview).getByText(/Unavailable: requests get 503/)).toBeInTheDocument();
  });

  it("says what it can't know in demo mode instead of guessing", async () => {
    render(<App api={offlineApi()} mock={createMockClient()} traffic={{ connect: vi.fn(() => ({ close() {} })), fixtureIntervalMs: 60_000 }} />);
    const overview = region("Overview");
    expect((await within(overview).findAllByText(/Unknown: the pii-guard API isn't reachable/)).length).toBe(2);
  });
});

describe("Connect", () => {
  it("shows copyable commands for each client with the gateway URL the server reports", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    history.replaceState(null, "", "#connect");
    render(<App api={liveApi()} mock={createMockClient()} loadStatus={statusOf()} />);
    const connect = region("Connect");
    expect(await within(connect).findByTestId("gateway-url")).toHaveTextContent("http://127.0.0.1:8899/v1");
    expect(within(connect).getByText("pii-guard connect pi --gateway http://127.0.0.1:8899/v1")).toBeInTheDocument();
    await user.click(within(connect).getAllByRole("button", { name: "Copy" })[0]!);
    expect(writeText).toHaveBeenCalledWith("pii-guard connect pi --gateway http://127.0.0.1:8899/v1");
    expect(await within(connect).findByText("Copied")).toBeInTheDocument();

    await user.click(within(connect).getByRole("radio", { name: /Muse Code/ }));
    expect(within(connect).getByText("pii-guard connect muse-code --gateway http://127.0.0.1:8899/v1 --check")).toBeInTheDocument();

    await user.click(within(connect).getByRole("radio", { name: /Claude Code/ }));
    expect(within(connect).getByText("Claude Code can't go through pii-guard yet.")).toBeInTheDocument();

    await user.click(within(connect).getByRole("radio", { name: /OpenAI SDK/ }));
    expect(within(connect).getByText(/export OPENAI_BASE_URL=http:\/\/127\.0\.0\.1:8899\/v1/)).toBeInTheDocument();

    await user.click(within(connect).getByRole("radio", { name: /curl/ }));
    // The mock upstream answers any model name; the command uses the mock's own.
    expect(within(connect).getByText(/curl -si http:\/\/127\.0\.0\.1:8899\/v1\/chat\/completions/)).toHaveTextContent('"model":"pii-guard-mock"');
  });

  it("falls back to the default address, and says so, when the server can't be asked", async () => {
    history.replaceState(null, "", "#connect");
    render(<App api={offlineApi()} mock={createMockClient()} />);
    const connect = region("Connect");
    expect(await within(connect).findByText(/the pii-guard API isn't reachable/)).toBeInTheDocument();
    expect(within(connect).getByTestId("gateway-url")).toHaveTextContent("http://127.0.0.1:8787/v1");
  });

  it("adds the token to the commands when the server needs one", async () => {
    history.replaceState(null, "", "#connect");
    const user = userEvent.setup();
    render(<App api={liveApi()} mock={createMockClient()} loadStatus={statusOf({ auth: { token_required: true } })} />);
    const connect = region("Connect");
    await within(connect).findByText(/This server needs a token/);
    await user.click(within(connect).getByRole("radio", { name: /curl/ }));
    expect(within(connect).getByText(/curl -si/)).toHaveTextContent('Authorization: Bearer $PII_GUARD_API_TOKEN');
  });
});

describe("Policy", () => {
  it("shows the server's mode, detectors and entity policies, read-only", async () => {
    history.replaceState(null, "", "#policy");
    render(<App api={liveApi()} mock={createMockClient()} loadStatus={statusOf()} />);
    const policy = region("Policy");
    expect(await within(policy).findByText("No NER: free-text names are not masked.")).toBeInTheDocument();
    const email = within(policy).getByRole("rowheader", { name: /^Email EMAIL/ }).closest("tr")!;
    expect(email).toHaveTextContent("Blocks the request");
    expect(email).toHaveTextContent("changed");
    expect(within(policy).getByRole("rowheader", { name: /^Secret SECRET/ }).closest("tr")).toHaveTextContent("Masked");
    expect(within(policy).getByText(/Refused \(fail closed\)/)).toBeInTheDocument();
    expect(within(policy).getByText(/no per-value allow-list/)).toBeInTheDocument();
    expect(within(policy).queryByRole("textbox")).toBeNull();
  });

  it("shows the documented defaults when the server predates /v1/status", async () => {
    history.replaceState(null, "", "#policy");
    render(<App api={liveApi()} mock={createMockClient()} loadStatus={() => Promise.resolve({ state: "missing" })} />);
    const policy = region("Policy");
    expect(await within(policy).findByText(/predates \/v1\/status/)).toBeInTheDocument();
    expect(within(policy).getByRole("rowheader", { name: /^Organization ORGANIZATION/ }).closest("tr")).toHaveTextContent("Kept in place");
  });
});

describe("Playground fixes", () => {
  function spyChat(): ChatClient & { calls: ChatTurnRequest[] } {
    const calls: ChatTurnRequest[] = [];
    return {
      kind: "api",
      calls,
      send: (req) => {
        calls.push(req);
        return Promise.resolve({ sessionId: req.sessionId ?? "s_live", answer: "ok", maskedAnswer: "ok", maskedMessages: req.messages, masked: 0, sessionSource: "header", mode: req.mode, ms: 1 });
      },
    };
  }

  it("warns in Chat that names pass when the server runs rules only (LAB-1291), and names the mock upstream (LAB-1264)", async () => {
    history.replaceState(null, "", "#playground/chat");
    const chat = spyChat();
    render(<App api={liveApi()} mock={createMockClient()} chat={{ api: chat }} loadStatus={statusOf()} />);
    const panel = screen.getByRole("tabpanel", { name: "Chat" });
    expect(await within(panel).findByTestId("rules-only-note")).toHaveTextContent("Names are not detected.");
    expect(within(panel).getByText("Mock upstream.")).toBeInTheDocument();
    fireEvent.click(within(panel).getByText("Connection details"));
    expect(within(panel).getByText("Mock upstream (echo): the model name is ignored")).toBeInTheDocument();
  });

  it("doesn't warn when the server runs the NER", async () => {
    history.replaceState(null, "", "#playground/chat");
    render(<App api={liveApi()} mock={createMockClient()} chat={{ api: spyChat() }} loadStatus={statusOf({ ner: { available: true, model: null } })} />);
    const panel = screen.getByRole("tabpanel", { name: "Chat" });
    await within(panel).findByText("Mock upstream.");
    expect(within(panel).queryByTestId("rules-only-note")).toBeNull();
  });

  it("hands the Text screen's session to Chat, so placeholders keep their numbers (LAB-1261)", async () => {
    history.replaceState(null, "", "#playground/text");
    const user = userEvent.setup();
    const mock = createMockClient();
    const chat = createMockChat(mock, { delayMs: 0 });
    const send = vi.spyOn(chat, "send");
    render(<App api={offlineApi()} mock={mock} chat={{ mock: chat }} />);
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const text = screen.getByRole("tabpanel", { name: "Text" });
    const masked = await within(text).findByTestId("masked-text");
    const session = within(text).getByTitle(/^s_demo_/).getAttribute("title")!;
    const person = /\[\[PERSON_[0-9a-f]+\]\]/.exec(masked.textContent ?? "")![0];
    await user.click(screen.getByRole("button", { name: /send it to the model/i }));
    const panel = screen.getByRole("tabpanel", { name: "Chat" });
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0]![0].sessionId).toBe(session);
    const received = await within(panel).findByRole("region", { name: "What the model received" });
    await waitFor(() => expect(received).toHaveTextContent(person));
    fireEvent.click(within(panel).getByText("Connection details"));
    expect(within(panel).getByText(/Continued from Text: the same values keep the same placeholders/)).toBeInTheDocument();
  });

  it("shows how the gateway picked the session in Logs (LAB-1286)", async () => {
    history.replaceState(null, "", "#logs");
    const f = fakeConnect();
    render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: f.connect }} loadStatus={statusOf()} />);
    await f.ready();
    f.push([{ ...EVENTS[0]!, session_source: "path", level: "masked", request: { masked: EVENTS[0]!.request?.masked } }]);
    const logs = region("Logs");
    expect(await within(logs).findByText("session in the base URL")).toBeInTheDocument();
    // The mock upstream echoes whatever model was asked for (LAB-1264).
    expect(within(logs).getByTitle("mock upstream (echo)")).toBeInTheDocument();
  });
});
