import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import full from "../test/trafficFull.json";
import fixture from "../content/trafficFixture.json";
import { parseTrafficEvent, type TrafficConnectOptions, type TrafficEvent, type TrafficStatus } from "../api/traffic";
import { Traffic } from "./Traffic";

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
    expect(within(list).getByTitle(/labelled “needs fast mode \(NER\)”: in rules-only mode its name is an expected miss/)).toBeInTheDocument();
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
    expect(screen.getByText(/Not kept\. The traffic log runs at/)).toBeInTheDocument();
    expect(within(screen.getByTestId("unmasked-response")).getByText(/put back before the answer reached your app/)).toBeInTheDocument();
    for (const v of [...ORIGINALS, "erika.mustermann@example.de"]) expect(container).not.toHaveTextContent(v);
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
    expect(await screen.findByText("Recorded demo traffic.")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByTestId("call-list")).getAllByRole("button").length).toBe(8));
    expect(screen.getByText("Recorded demo traffic never holds original values.")).toBeInTheDocument();
    for (const v of [...ORIGINALS, "jane.placeholder@example.net", "1051 Budapest"]) expect(container).not.toHaveTextContent(v);
    expect(screen.queryByRole("button", { name: "Send demo traffic" })).toBeNull();
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

  it("says which detectors ran, and that rules alone don't find names", async () => {
    const f = fakeConnect();
    render(<Traffic connect={f.connect} pageHost="localhost" />);
    f.push([asMasked(huChat)]);
    expect(await screen.findByText(/This call ran Rules only/)).toBeInTheDocument();
    expect(screen.getByText("not names")).toBeInTheDocument();
    expect(screen.getByText(/^fast: Rules\. Strict mode adds/)).toBeInTheDocument();
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
