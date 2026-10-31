import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import full from "../test/trafficFull.json";
import fixture from "../content/trafficFixture.json";
import { parseTrafficEvent, type TrafficConnectOptions, type TrafficEvent, type TrafficStatus } from "../api/traffic";
import { Traffic } from "./Traffic";
import { setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import { HostedSessionContext, type HostedSession } from "../hosted/session";

const recorded = (full.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
const [huChat, huStream, deTools, refused] = recorded as [TrafficEvent, TrafficEvent, TrafficEvent, TrafficEvent];
const asMasked = (e: TrafficEvent): TrafficEvent => ({
  ...e,
  level: "masked",
  request: { masked: e.request?.masked },
  response: e.response ? { masked: e.response.masked, chunks: e.response.chunks } : null,
});
const ORIGINALS = ["teszt.elek@example.com", "+36 30 123 4567", "HU42 1177 3016 1111 1018 0000 0000", "123 456 788"];

/** A fake connection the test drives: push events and statuses as the server would. */
function fakeConnect() {
  let opts: TrafficConnectOptions | null = null;
  const connect = vi.fn((o: TrafficConnectOptions) => {
    opts = o;
    return { close: vi.fn() };
  });
  return {
    connect,
    push: (events: TrafficEvent[], status: TrafficStatus = { state: "live", via: "sse", level: events[0]?.level ?? "masked", size: 200 }) =>
      act(() => {
        opts!.onStatus(status);
        opts!.onEvents(events);
      }),
    status: (s: TrafficStatus) => act(() => opts!.onStatus(s)),
    restart: (boot: string) => act(() => opts!.onRestart!(boot)),
  };
}

beforeEach(() => {
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("Live traffic", () => {
  it("shows originals, the masked request and the restored answer at level full on localhost", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([huChat]);

    const original = await screen.findByTestId("original-request");
    expect(original).toHaveTextContent("teszt.elek@example.com");
    // Each original value is marked against its placeholder.
    expect(original.querySelectorAll("mark[data-restored]").length).toBe(4);

    const masked = screen.getByTestId("masked-request");
    expect(masked).toHaveTextContent(/\[\[EMAIL_[0-9a-f]+\]\]/);
    for (const v of ORIGINALS) expect(masked).not.toHaveTextContent(v);
    expect(masked.querySelectorAll("[data-placeholder]").length).toBe(4);

    const fromModel = screen.getByTestId("masked-response");
    expect(fromModel).toHaveTextContent(/Echo: .*\[\[PHONE_[0-9a-f]+\]\]/);
    for (const v of ORIGINALS) expect(fromModel).not.toHaveTextContent(v);
    const restored = screen.getByTestId("unmasked-response");
    expect(restored).toHaveTextContent("+36 30 123 4567");
    expect([...restored.querySelectorAll("mark[data-restored]")].map((m) => m.firstChild?.textContent)).toEqual(
      expect.arrayContaining(["teszt.elek@example.com", "+36 30 123 4567"]),
    );
  });

  it("selects the call it is asked to open, and moves focus to it once it arrives (LAB-1626)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" focus={{ id: huStream.id, nonce: 1 }} />);
    f.push([huChat]);
    // Not here yet: the latest call shows, focus stays put.
    await screen.findByTestId("original-request");
    expect(screen.getByRole("heading", { name: /^Call at/ })).not.toHaveFocus();
    f.push([huStream, deTools]);
    // The test request's call, even with a newer one after it.
    await waitFor(() => expect(screen.getByRole("heading", { name: /^Call at/ })).toHaveFocus());
    const rows = document.querySelectorAll("button[aria-current]");
    expect(rows).toHaveLength(1);
    // The middle of the three calls, not the newest.
    const all = [...document.querySelectorAll("button")].filter((b) => b.className.includes("text-left"));
    expect(all.indexOf(rows[0] as HTMLButtonElement)).toBe(all.length - 2);
  });

  it("labels the NER-only demo call as an expected miss in rules-only mode", async () => {
    const replay = (fixture.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
    const nerOnly = replay.find((e) => JSON.stringify(e.request).includes("Gipsz Jakab"))!;
    const others = replay.filter((e) => e !== nerOnly && e.outcome === "ok").slice(0, 2);
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([...others, nerOnly]);
    const list = await screen.findByTestId("call-list");
    expect(within(list).getAllByText(/needs NER/)).toHaveLength(2); // the tag and the row summary
    expect(within(list).getByText("1 name reached the model: expected, needs NER")).toBeInTheDocument();
    expect(within(list).getByTitle(/labeled “needs fast mode \(NER\)”: in rules-only mode its name is an expected miss/)).toBeInTheDocument();
    const note = within(screen.getByRole("region", { name: /Call at/ })).getByRole("note");
    expect(note).toHaveTextContent("Demo scenario hu-needs-ner: needs fast mode (NER). Expected miss in rules-only mode.");
    expect(note).toHaveTextContent("Gipsz Jakab");
    // the existing per-call detector caveat still explains why
    expect(screen.getByTestId("masked-request")).toHaveTextContent(/not names/);
  });

  it("never shows an original value at level masked", async () => {
    const f = fakeConnect();
    const { container } = render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat), asMasked(deTools)]);
    await screen.findByTestId("masked-request");
    expect(screen.queryByTestId("original-request")).toBeNull();
    expect(screen.getByText(/Not kept: the traffic log holds only what left the machine/)).toBeInTheDocument();
    expect(within(screen.getByTestId("unmasked-response")).getByText(/put back before the answer reached your app/)).toBeInTheDocument();
    for (const v of [...ORIGINALS, "erika.mustermann@example.de"]) expect(container).not.toHaveTextContent(v);
  });

  it("renders one h1, the request and response as shared panes, and the summary as metrics (LAB-1441)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat)]);
    await screen.findByTestId("masked-request");
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Logs"]);
    for (const name of ["Original request", "Masked request", "Response, masked → restored"]) {
      const pane = screen.getByRole("region", { name });
      expect(pane).toHaveAttribute("data-side");
      expect(within(pane).getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    const summary = screen.getByLabelText("Summary of the calls shown");
    expect(within(summary).getByText("Calls").nextElementSibling).toHaveTextContent("1");
  });

  it("hides originals a full-level server logged when the page is not on localhost", async () => {
    const f = fakeConnect();
    const { container } = render(<Traffic connect={f.connect} pageHost="demo.example.org" />);
    f.push([huChat]);
    await screen.findByTestId("masked-request");
    expect(screen.getByText(/only shown on a page served from localhost/)).toBeInTheDocument();
    for (const v of ORIGINALS) expect(container).not.toHaveTextContent(v);
  });

  it("shows tool definitions and tool-call arguments masked, and restores the arguments", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([deTools]);
    const masked = await screen.findByTestId("masked-request");
    expect(within(masked).getByText(/Tools \(1\)/)).toBeInTheDocument();
    expect(masked).toHaveTextContent("send_email");
    expect(screen.getByTestId("masked-response")).toHaveTextContent(/tool call · send_email.*\[\[EMAIL_[0-9a-f]+\]\]/);
    expect(screen.getByTestId("unmasked-response")).toHaveTextContent("erika.mustermann@example.de");
  });

  it("shows a streamed answer and its time to first token", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([huStream]);
    expect(await screen.findByTestId("masked-response")).toHaveTextContent(/streamed, \d+ chunks/);
    expect(screen.getByTestId("unmasked-response")).toHaveTextContent("1051 Budapest, Minta utca 12.");
    expect(screen.getByTestId("wf-ttft")).toHaveTextContent(`${huStream.timing.added_ttft_ms!.toFixed(2)} ms`);
  });

  it("explains a refused image request: nothing forwarded", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([refused]);
    expect(await screen.findByText(/Refused\. Nothing was sent to the model\./)).toBeInTheDocument();
    expect(screen.getByText("Nothing was forwarded.")).toBeInTheDocument();
    expect(screen.getByTestId("wf-upstream")).toHaveTextContent("not called");
    expect(screen.getAllByText(/The log keeps a summary of each image/).length).toBeGreaterThan(0);
  });

  it("shows the masked-image thumbnail in the masked request, matched by image index (LAB-1188)", async () => {
    const thumb = "data:image/webp;base64,UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==";
    const imageCall: TrafficEvent = {
      ...asMasked(huChat),
      id: "req_thumbnail",
      entities: { ...huChat.entities!, images: { count: 2, masked: { FACE: 1 }, kept: {}, ocr: true } },
      request: {
        masked: {
          model: "test-model",
          messages: [
            {
              role: "user",
              content: [
                { type: "text", text: "Two pictures" },
                { type: "image_url", image_url: { url: "[inline image/png, 5000 chars]" } },
                { type: "image_url", image_url: { url: "[inline image/png, 9000 chars]" } },
              ],
            },
          ],
        },
        thumbnails: [
          { index: 0, omitted: "too_large" },
          { index: 1, width: 1, height: 1, data: thumb },
        ],
      } as TrafficEvent["request"],
    };
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([imageCall]);
    const masked = await screen.findByTestId("masked-request");
    const img = within(masked).getByTestId("masked-thumbnail");
    expect(img).toHaveAttribute("src", thumb);
    expect(img).toHaveAccessibleName(/masked image as sent to the model/);
    expect(within(masked).getAllByTestId("masked-thumbnail")).toHaveLength(1);
    expect(masked).toHaveTextContent(/too large or unreadable for a thumbnail/);
    expect(masked).toHaveTextContent(/the original is never kept/);
  });

  it("draws the waterfall from the event's timing", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([huChat]);
    const wf = await screen.findByTestId("waterfall");
    const detect = wf.querySelector('[data-stage="detect"]')!;
    expect(Number(detect.getAttribute("data-ms"))).toBe(huChat.timing.stages_ms.detect);
    expect(screen.getByTestId("wf-overhead")).toHaveTextContent(`${huChat.timing.overhead_ms.toFixed(2)} ms`);
    expect(screen.getByTestId("wf-total")).toHaveTextContent(`${huChat.timing.total_ms.toFixed(2)} ms`);
  });

  it("follows the latest call, keeps a picked one, pauses and clears", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat)]);
    await screen.findByText("Following the latest call");
    f.push([asMasked(deTools)]);
    const list = screen.getByTestId("call-list");
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    // newest first; pick the older one
    await user.click(within(list).getAllByRole("button")[1]!);
    expect(screen.getByRole("button", { name: "Follow the latest call" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /pause/i }));
    f.push([asMasked(huStream)]);
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: /resume \(1 new\)/i }));
    expect(within(screen.getByTestId("call-list")).getAllByRole("button")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Clear view" }));
    expect(screen.queryByTestId("call-list")).toBeNull();
  });

  it("filters to blocked or failed calls", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat), asMasked(refused)]);
    await user.click(await screen.findByRole("checkbox", { name: /blocked or failed only/i }));
    const rows = within(screen.getByTestId("call-list")).getAllByRole("button");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Refused");
  });

  it("offers Clear filters when no call matches, returning the full list (LAB-1712)", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat), asMasked(deTools)]);
    await screen.findByTestId("call-list");
    // Both calls are ok: "blocked or failed only" matches nothing.
    await user.click(screen.getByRole("checkbox", { name: /blocked or failed only/i }));
    expect(await screen.findByText("No call matches these filters.")).toBeInTheDocument();
    expect(screen.queryByTestId("call-list")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(within(await screen.findByTestId("call-list")).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: /blocked or failed only/i })).not.toBeChecked();
    // The button unmounts: focus moves to the list it reveals, not to <body>.
    expect(screen.getByRole("heading", { name: "Calls" })).toHaveFocus();
  });

  it("explains a disabled log and offers the recorded traffic", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" fixtureIntervalMs={60_000} />);
    f.status({ state: "disabled", reason: "off", message: "the traffic log is off" });
    expect(await screen.findByText("The traffic log is off on this server.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show recorded demo traffic" }));
    expect(await screen.findByText("Recorded demo traffic.")).toBeInTheDocument();
    expect(screen.getByText(/traffic log is off, so these are calls recorded/)).toBeInTheDocument();
    expect(within(screen.getByTestId("call-list")).getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("falls back to the recorded traffic when the API is offline, with no original values", async () => {
    const f = fakeConnect();
    const { container } = render(<Traffic connect={f.connect} pageHost="localhost" fixtureIntervalMs={60_000} />);
    f.status({ state: "offline", message: "pii-guard API is not reachable" });
    // The first offline contact is retried once before falling back (LAB-1703).
    await waitFor(() => expect(f.connect).toHaveBeenCalledTimes(2), { timeout: 4000 });
    expect(screen.queryByText("Recorded demo traffic.")).toBeNull();
    f.status({ state: "offline", message: "pii-guard API is not reachable" });
    expect(await screen.findByText("Recorded demo traffic.")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId("call-list")).getAllByRole("button").length).toBe(8));
    expect(screen.getByText("Recorded demo traffic never holds original values.")).toBeInTheDocument();
    for (const v of [...ORIGINALS, "jane.placeholder@example.net", "1051 Budapest"]) expect(container).not.toHaveTextContent(v);
    expect(screen.queryByRole("button", { name: "Send demo traffic" })).toBeNull();
  });

  it("says the API is rate limiting, not unreachable, and stays on the live log (LAB-1437)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" fixtureIntervalMs={60_000} />);
    f.status({ state: "limited", message: "Request allowance reached; try again in 3 seconds", retryAfterMs: 3000 });
    expect(await screen.findByText("Too many requests just now.")).toBeInTheDocument();
    expect(screen.getByText(/retries in about 3 s/)).toBeInTheDocument();
    expect(screen.queryByText("Recorded demo traffic.")).toBeNull();
    expect(screen.queryByText(/isn't reachable|Lost the connection/)).toBeNull();
  });

  it("says the viewer is signed out or denied, not that the API is unreachable (LAB-1437)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" fixtureIntervalMs={60_000} />);
    f.status({ state: "denied", reason: "signed_out", message: "Sign in with Google to use this endpoint" });
    expect(await screen.findByText("You're signed out.")).toBeInTheDocument();
    expect(screen.queryByText("Recorded demo traffic.")).toBeNull();
    f.status({ state: "denied", reason: "forbidden", message: "denied" });
    expect(await screen.findByText("This account can't read this traffic log.")).toBeInTheDocument();
    expect(screen.queryByText(/isn't reachable|Lost the connection/)).toBeNull();
  });

  it("hosted: the status line describes the hosted service, not the machine (LAB-1619)", async () => {
    const f = fakeConnect();
    const session = { account: {}, error: "", refresh: async () => {}, call: vi.fn() } as unknown as HostedSession;
    render(<HostedSessionContext.Provider value={session}><Traffic connect={f.connect} pageHost="guard.example" demoTraffic={false} /></HostedSessionContext.Provider>);
    f.push([], { state: "live", via: "poll", level: "masked", size: 50 });
    expect(await screen.findByText("Only what was sent to the model is logged: placeholders, never values.")).toBeInTheDocument();
    expect(screen.queryByText(/left the machine/)).toBeNull();
  });

  it("hosted: a 401 in the console says the session ended (LAB-1519)", async () => {
    const f = fakeConnect();
    const session = { account: {}, error: "", refresh: async () => {}, call: vi.fn() } as unknown as HostedSession;
    render(<HostedSessionContext.Provider value={session}><Traffic connect={f.connect} pageHost="guard.example" fixtureIntervalMs={60_000} /></HostedSessionContext.Provider>);
    f.status({ state: "denied", reason: "signed_out", message: "Sign in" });
    expect(await screen.findByText("Your session ended.")).toBeInTheDocument();
    expect(screen.queryByText("You're signed out.")).toBeNull();
    expect(screen.queryByText(/answered 401/)).toBeNull();
  });

  it("plays the recorded traffic once, and Replay again never inflates the counters (LAB-1200)", async () => {
    const user = userEvent.setup();
    const total = (fixture.events as unknown[]).map(parseTrafficEvent).filter(Boolean).length;
    const facts = () => {
      const value = (label: string) => screen.getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
      return { calls: value("Calls"), masked: value("Values masked"), problems: value("Blocked or failed") };
    };
    const rows = () => within(screen.getByTestId("call-list")).getAllByRole("button").length;
    render(<Traffic forceFixture pageHost="localhost" fixtureIntervalMs={5} />);
    expect(await screen.findByText("Replaying the recorded calls once…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replay again" })).toHaveAttribute("aria-disabled", "true");

    expect(await screen.findByText("Replay finished: every recorded call was played once.", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(rows()).toBe(total);
    const onePass = facts();
    expect(onePass.calls).toBe(String(total));
    // Nothing loops: the counters stay put after the last recorded call.
    await new Promise((r) => setTimeout(r, 60));
    expect(facts()).toEqual(onePass);

    expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();

    // Cleared after the end: the empty list points at Replay again, not "waiting".
    await user.click(screen.getByRole("button", { name: /Clear/ }));
    expect(screen.getByText(/The recorded replay has finished/)).toBeInTheDocument();

    const again = screen.getByRole("button", { name: "Replay again" });
    await user.click(again);
    expect(again).toHaveFocus();
    expect(await screen.findByText("Replaying the recorded calls once…")).toBeInTheDocument();
    expect(Number(facts().calls)).toBeLessThanOrEqual(total);
    expect(await screen.findByText("Replay finished: every recorded call was played once.", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(rows()).toBe(total);
    expect(facts()).toEqual(onePass);
  });

  it("waits while paused, so the replay never claims it finished early (LAB-1200)", async () => {
    const user = userEvent.setup();
    const total = (fixture.events as unknown[]).map(parseTrafficEvent).filter(Boolean).length;
    const rows = () => within(screen.getByTestId("call-list")).getAllByRole("button").length;
    render(<Traffic forceFixture pageHost="localhost" fixtureIntervalMs={5} />);
    await waitFor(() => expect(rows()).toBeGreaterThan(0));
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByTestId("replay-state")).toHaveTextContent("Replay paused. Press Resume to continue.");
    // A call already in flight as Pause was pressed may land; after that, nothing moves.
    await new Promise((r) => setTimeout(r, 20));
    const shown = rows();
    const resume = screen.getByRole("button", { name: /^Resume/ }).textContent;
    await new Promise((r) => setTimeout(r, 120)); // well past one pass at 5 ms a call
    expect(rows()).toBe(shown);
    expect(screen.getByRole("button", { name: /^Resume/ }).textContent).toBe(resume); // not queueing
    expect(screen.queryByText(/Replay finished/)).toBeNull();

    // Replay again while paused also resumes; here, resume and let it finish.
    await user.click(screen.getByRole("button", { name: /^Resume/ }));
    expect(await screen.findByText("Replay finished: every recorded call was played once.", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(rows()).toBe(total);
  });

  it("offers Replay again only after a full pass, and the new pass can be paused", async () => {
    const user = userEvent.setup();
    render(<Traffic forceFixture pageHost="localhost" fixtureIntervalMs={5} />);
    const again = await screen.findByRole("button", { name: "Replay again" });
    await screen.findByText("Replay finished: every recorded call was played once.", undefined, { timeout: 3000 });
    // Paused, a replay never finishes, so Replay again (which also resumes) can't be hit paused.
    await user.click(again);
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(screen.getByRole("button", { name: /^Resume/ })).toBeInTheDocument();
    await screen.findByText("Replay paused. Press Resume to continue.");
    expect(again).toHaveAttribute("aria-disabled", "true");
  });

  it("sends demo traffic through the gateway and reports refusals", async () => {
    const user = userEvent.setup();
    const f = fakeConnect();
    const sendDemo = vi.fn(async (o: { onProgress?: (p: { done: number; total: number; refused: number }) => void } = {}) => {
      o.onProgress?.({ done: 1, total: 8, refused: 0 });
      return { done: 8, total: 8, refused: 1 };
    });
    render(<Traffic connect={f.connect} pageHost="localhost" sendDemo={sendDemo} />);
    f.push([], { state: "live", via: "sse", level: "masked", size: 200 });
    await user.click(await screen.findByRole("button", { name: "Send demo traffic" }));
    expect(sendDemo).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Sent 8 fictional calls; 1 refused/)).toBeInTheDocument();
  });

  it("doesn't offer demo traffic where the server has accounts (LAB-1435)", async () => {
    const f = fakeConnect();
    const sendDemo = vi.fn();
    render(<Traffic connect={f.connect} pageHost="localhost" sendDemo={sendDemo} demoTraffic={false} />);
    f.push([], { state: "live", via: "sse", level: "masked", size: 200 });
    expect(await screen.findByText(/Calls through any of this project's endpoints show here, each tagged with its endpoint\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send demo traffic" })).toBeNull();
    expect(screen.queryByText(/make demo-traffic/)).toBeNull();
    expect(sendDemo).not.toHaveBeenCalled();
  });

  it("says which detectors ran, and that rules alone don't find names", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat)]);
    expect(await screen.findByText(/This call ran Rules only/)).toBeInTheDocument();
    expect(screen.getByText("not names")).toBeInTheDocument();
    // NER first (LAB-1291): the fix is the on-device NER, not audit mode.
    expect(screen.getByTestId("masked-request")).toHaveTextContent(/names need the on-device NER: install the ner extra/);
  });

  it("doesn't claim there was nothing to restore in a streamed tool call", async () => {
    const streamedTool = (fixture.events as unknown[]).map(parseTrafficEvent).find((e) => e?.stream && JSON.stringify(e.request).includes("send_email"))!;
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([streamedTool]);
    expect(await screen.findByText(/streamed tool-call arguments were restored on the way to your app/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing to restore/)).toBeNull();
  });
});

describe("Upstream refusals in the drawer (LAB-1335)", () => {
  it("says the masked request reached the upstream, with its status and a hint", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    const rejected: TrafficEvent = {
      ...asMasked(huChat),
      outcome: "upstream_error",
      error: { code: "upstream_error", status: 404 },
      upstream: { status: 404, model: null, unresolved_placeholders: 0 },
      response: null,
    };
    f.push([rejected]);
    const note = await screen.findByText("The upstream refused the masked request (HTTP 404).");
    const box = note.closest("[role=note]")!;
    expect(box).toHaveTextContent("model not found on the upstream? Pick another model");
    expect(box).toHaveTextContent("Nothing unmasked left PII Guard.");
    expect(box).not.toHaveTextContent("Nothing was sent to the model");
  });

  it("labels a forwarded call whose upstream failed, and shows its model (LAB-1629)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    const failed: TrafficEvent = {
      ...asMasked(huChat),
      outcome: "upstream_failed",
      model: "synthetic-model",
      error: { code: "upstream_did_not_stream", status: 502 },
      upstream: { status: 200, model: null, unresolved_placeholders: 0 },
      response: null,
    };
    f.push([failed]);
    expect(await screen.findByText("The model answered without streaming.")).toBeInTheDocument();
    expect(screen.getAllByText("Upstream failed").length).toBeGreaterThan(0);
    expect(screen.queryByText("Refused")).toBeNull();
    expect(screen.queryByText("not forwarded")).toBeNull();
    expect(screen.getAllByText("synthetic-model").length).toBeGreaterThan(0);
    expect(screen.getByText(/the masked request was forwarded, but the model's provider did not answer usably/)).toBeInTheDocument();
  });

  it("keeps the refusal text when pii-guard stopped the request", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([refused]);
    expect(await screen.findByText(/Refused\. Nothing was sent to the model\./)).toBeInTheDocument();
    expect(screen.queryByText(/The upstream refused/)).toBeNull();
  });

  it("shows the server's message instead of the client-side reason (LAB-1314)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    const blocked: TrafficEvent = {
      ...asMasked(refused),
      outcome: "blocked",
      error: {
        code: "blocked_entity",
        status: 422,
        message: "the text contains entity types blocked by policy: EMAIL (1)",
        entity_types: { EMAIL: 1 },
      },
    };
    f.push([blocked]);
    expect(await screen.findByText("the text contains entity types blocked by policy: EMAIL (1)")).toBeInTheDocument();
  });
});

describe("Endpoint traffic in project Logs (LAB-1492)", () => {
  const viaEndpoint = (e: TrafficEvent, id: string, name: string): TrafficEvent => ({ ...asMasked(e), id: `${e.id}_${id}`, endpoint: { id, name } });

  beforeEach(() => {
    setSelectedProject(null);
    setSelectedEndpoint(null);
  });

  it("tags each call with its endpoint when no endpoint is selected", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="example.com" demoTraffic={false} />);
    f.push([viaEndpoint(huChat, "ep_a", "Synthetic CLI"), asMasked(deTools)]);
    const list = await screen.findByTestId("call-list");
    expect(within(list).getByTitle("Endpoint: Synthetic CLI")).toBeInTheDocument();
    expect(within(list).getAllByTitle(/^Endpoint:/)).toHaveLength(1);
  });

  it("names the endpoint in the detail and sends its vault session to that endpoint's view", async () => {
    const f = fakeConnect();
    const onOpenSession = vi.fn();
    render(<Traffic connect={f.connect} pageHost="example.com" demoTraffic={false} onOpenSession={onOpenSession} />);
    f.push([{ ...viaEndpoint(huChat, "ep_a", "Synthetic CLI"), session_ref: "s_0123456789abcdef" }]);
    const detail = await screen.findByRole("region", { name: /Call at/ });
    expect(within(detail).getByText("Endpoint")).toBeInTheDocument();
    await userEvent.click(within(detail).getByRole("button", { name: "Open session in Synthetic CLI" }));
    expect(onOpenSession).not.toHaveBeenCalled();
    const { getSelectedEndpoint } = await import("../projects/selection");
    expect(getSelectedEndpoint()).toBe("ep_a");
  });

  it("reopens the call and puts focus back after the switch remounts the console (LAB-1619)", async () => {
    const f = fakeConnect();
    const ev = { ...viaEndpoint(huChat, "ep_a", "Synthetic CLI"), session_ref: "s_0123456789abcdef" };
    const first = render(<Traffic connect={f.connect} pageHost="example.com" demoTraffic={false} onOpenSession={vi.fn()} />);
    f.push([ev]);
    const detail = await screen.findByRole("region", { name: /Call at/ });
    await userEvent.click(within(detail).getByRole("button", { name: "Open session in Synthetic CLI" }));
    first.unmount();
    const g = fakeConnect();
    render(<Traffic connect={g.connect} pageHost="example.com" demoTraffic={false} onOpenSession={vi.fn()} />);
    g.push([ev, { ...viaEndpoint(deTools, "ep_a", "Synthetic CLI") }]);
    const open = await screen.findByRole("button", { name: /Open session s_0123456789abcdef in Vault/ });
    await waitFor(() => expect(open).toHaveFocus());
  });

  it("truncates a long provider model id in the row and keeps it in the title (LAB-1619)", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="example.com" demoTraffic={false} />);
    f.push([{ ...asMasked(huChat), model: "accounts/fireworks/models/llama-v3p3-70b-instruct-very-long-id" }]);
    const list = await screen.findByTestId("call-list");
    const model = within(list).getByTitle("accounts/fireworks/models/llama-v3p3-70b-instruct-very-long-id");
    expect(model).toHaveTextContent(/^llama-v3p3-70b-instruct-very-long-id$/);
    expect(model.className).toMatch(/\btruncate\b/);
    expect(model.className).not.toMatch(/shrink-0/);
  });

  it("drops the tag and says the view is filtered while an endpoint is selected", async () => {
    setSelectedEndpoint("ep_a");
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="example.com" demoTraffic={false} />);
    f.push([], { state: "live", via: "poll", level: "masked", size: 50 });
    expect(await screen.findByText(/Only calls through the endpoint picked in the header show here\./)).toBeInTheDocument();
    f.push([viaEndpoint(huChat, "ep_a", "Synthetic CLI")]);
    const list = await screen.findByTestId("call-list");
    expect(within(list).queryByTitle(/^Endpoint:/)).toBeNull();
  });
});

describe("backend restart", () => {
  it("marks the new run with a divider above its first call", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([huChat, huStream]);
    expect(screen.queryByText(/Server restarted/)).toBeNull();
    f.restart("boot_b");
    f.push([refused]);
    expect(await screen.findByText(/Server restarted/)).toBeInTheDocument();
    expect(screen.getByText(/sessions are keyed per server process/i)).toBeInTheDocument();
  });
});
