import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { HostedApp } from "./HostedApp";
import { recovery, type Account, type DemoResult, type Requester } from "./api";
import { modelName, resetsIn, runsLeft, usageLine } from "./landing";

const account: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const result: DemoResult = { sample_id: "hu-support", language: "hu", original: "Synthetic original", masked: "[[PERSON_1a2b]]", answer: "Hello [[PERSON_1a2b]]", restored: "Hello Synthetic Person", model: "test-model", session_id: "test-session", request_id: "test-request", entities: [{ start: 0, end: 9, type: "PERSON" }] };

function requester(handler: (path: string, body?: unknown, method?: string) => unknown) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => handler(path, body, method)) as unknown as Requester;
}

describe("public hosted workflow", () => {
  it("sends sign-in back to the console instead of the provider's bare page", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    await screen.findAllByText(/free runs/i);
    expect(screen.getByText(/Runs on Muse Spark 1.3 · no key needed/)).toHaveTextContent("3 of 3 free runs left today");
    expect(document.body.textContent).not.toMatch(/sponsor/i);
    const links = [...screen.getAllByRole("link", { name: "Sign in with Google" }), ...screen.getAllByRole("link", { name: "Console" })];
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) expect(link).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
  });
  it("labels the static mechanism, requests only a server sample, and shows all live stages", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const user = userEvent.setup();
    render(<HostedApp call={call} />);
    expect(screen.getByText("Worked example")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · answered by test-model");
    expect(call).toHaveBeenCalledWith("/v1/demo", { sample_id: "en-support", language: "en" });
    const stages = ["demo-input", "demo-sent", "demo-answer", "demo-restored"].map((id) => document.querySelector(`[aria-labelledby="${id}-title"] .doc`)?.textContent?.replace(/ \([^)]*\)/g, ""));
    expect(stages).toEqual([result.original, result.masked, result.answer, result.restored]);
    expect(screen.getByText("Live result ready: Person masked, answer restored. Model: test-model.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Entity legend" })).toHaveTextContent(/Person\s*1/);
    expect(document.querySelector("#demo [data-flow] mark[data-masked]")).toHaveTextContent("Synthetic original");
    expect(document.querySelector("#demo [data-flow] [data-placeholder]")).toHaveTextContent("[[PERSON_1a2b]]");
    expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Synthetic Person");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Vault")).not.toBeInTheDocument();
  });
  it("clears previous success on quota failure and makes static recovery explicit", async () => {
    let runs = 0;
    const call = requester((path) => { if (path === "/v1/account") return account; if (++runs === 1) return result; throw new ApiError(429, "quota_exceeded", "sensitive server text must never render"); });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · answered by test-model");
    await user.click(screen.getByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.queryByText(/sensitive server text/)).not.toBeInTheDocument();
    // A live failure never blanks the worked example.
    expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Robin Example");
    expect(screen.getByText("Live run didn’t finish · showing the worked example")).toBeInTheDocument();
    // The worked example is already on screen: no way back to it. Used up: no retry, sign in instead.
    expect(screen.queryByRole("button", { name: "Back to the worked example" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in for more runs" })).toBeInTheDocument();
    expect(screen.queryByText(/free runs left today/)).not.toBeInTheDocument();
  });
  it("offers Try again after a provider failure (LAB-1466)", async () => {
    const call = requester((path) => { if (path === "/v1/account") return account; throw new ApiError(502, "upstream_error", "x"); });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("rejects incomplete live results rather than showing a successful model run", async () => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, restored: "" });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert"); expect(screen.queryByText("Live result · answered by test-model")).not.toBeInTheDocument();
  });
  it.each([null, {}, { start: 0.5, end: 2, type: "PERSON" }, { start: 3, end: 2, type: "PERSON" }, { start: 0, end: 2, type: null }])("rejects malformed entity metadata without rendering a live success: %j", async (entity) => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, entities: [entity] });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Live result · answered by test-model")).not.toBeInTheDocument();
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.getByText("Live run didn’t finish · showing the worked example")).toBeInTheDocument();
  });
  it("offers honest unavailable state with reconnect and keeps the static walkthrough", async () => {
    const call = requester(() => { throw new Error("offline"); });
    render(<HostedApp call={call} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Run live example" })).toBeDisabled();
    expect(screen.getByText("Worked example")).toBeInTheDocument();
    expect(screen.getByText("The live service isn’t reachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect to API" })).toBeInTheDocument();
  });
  it("points a signed-in visitor of the public page to the console, without broad account keys", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...account, authenticated: true } : []);
    render(<HostedApp call={call} />);
    await screen.findByText(/You’re signed in/);
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute("href", account.logout_url);
    expect(screen.queryByRole("button", { name: "Create guard key" })).not.toBeInTheDocument();
    expect(screen.queryByText("Local guard access")).not.toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/v1/account/api-keys");
    expect(call).not.toHaveBeenCalledWith("/v1/projects");
  });
});

describe("hero CTA (LAB-1479)", () => {
  const spyScroll = () => vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
  it("scrolls to the demo, focuses its heading and starts the guest run in one press", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const scroll = spyScroll();
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await screen.findByRole("button", { name: "Run live example" });
    const cta = screen.getByRole("link", { name: "Run the live demo" });
    expect(cta).toHaveAttribute("href", "#demo");
    await user.click(cta);
    await screen.findByText("Live result · answered by test-model");
    expect(call).toHaveBeenCalledWith("/v1/demo", { sample_id: "en-support", language: "en" });
    expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    expect(scroll.mock.contexts[0]).toBe(document.getElementById("demo"));
    const heading = screen.getByRole("heading", { name: "See exactly what the model sees." });
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(heading).toHaveFocus();
    scroll.mockRestore();
  });
  it("jumps without smooth scrolling under prefers-reduced-motion", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const scroll = spyScroll();
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false }) as MediaQueryList);
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await screen.findByRole("button", { name: "Run live example" });
    await user.click(screen.getByRole("link", { name: "Run the live demo" }));
    await screen.findByText("Live result · answered by test-model");
    expect(scroll).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
    vi.unstubAllGlobals(); scroll.mockRestore();
  });
  it("stays a plain anchor when runs are paused or the visitor is signed in", async () => {
    const off: Account = { ...account, limits: { requests_per_day: 5, sponsored_enabled: false } };
    for (const acct of [off, { ...account, authenticated: true }]) {
      const call = requester((path) => path === "/v1/account" ? acct : path === "/v1/demo" ? result : []);
      const user = userEvent.setup(); const { unmount } = render(<HostedApp call={call} />);
      const cta = await screen.findByRole("link", { name: acct === off ? "See how it works" : "Run your own text" });
      let prevented: boolean | null = null;
      const listener = (e: Event) => { prevented = e.defaultPrevented; e.preventDefault(); };
      document.addEventListener("click", listener);
      await user.click(cta);
      document.removeEventListener("click", listener);
      expect(prevented).toBe(false);
      expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
      unmount();
    }
  });
});

describe("sponsorship off (zero budget until the provider authorises it)", () => {
  const off: Account = { ...account, limits: { requests_per_day: 5, images_per_day: 0, max_image_bytes: 0, sponsored_enabled: false } };
  it("offers no live run to guests, keeps the worked example and points to sign-in", async () => {
    const call = requester((path) => path === "/v1/account" ? off : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Sign in to run your own text" })).toHaveAttribute("href", account.login_url);
    expect(screen.queryByRole("button", { name: "Run live example" })).not.toBeInTheDocument();
    expect(screen.getByText("Worked example")).toBeInTheDocument();
    expect(document.querySelector("#demo [data-flow] [data-placeholder]")).toHaveTextContent("[[PERSON_3f9a1c]]");
    expect(screen.queryByText(/No login needed/)).not.toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
    expect(screen.getByText("Free runs are paused right now")).toBeInTheDocument();
    expect(screen.getByText("The worked example below shows the same flow, step by step.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See how it works" })).toHaveAttribute("href", "#demo");
    expect(document.body.textContent).not.toMatch(/sponsor/i);
  });
  it("hides limits that are off", async () => {
    const call = requester((path) => path === "/v1/account" ? off : result);
    render(<HostedApp call={call} />);
    await screen.findByText("Current server limits");
    expect(screen.getByText("Requests per day")).toBeInTheDocument();
    expect(screen.queryByText("Images per day")).not.toBeInTheDocument();
    expect(screen.queryByText("Largest image (bytes)")).not.toBeInTheDocument();
  });
  it("maps sponsored_unavailable to its own copy", () => {
    expect(recovery(new ApiError(503, "sponsored_unavailable", "x"), "site")).toMatch(/^Free runs are paused right now/);
    expect(recovery(new ApiError(503, "sponsored_unavailable", "x"))).toMatch(/^Free runs are paused right now/);
    for (const context of ["site", "console"] as const) expect(recovery(new ApiError(503, "sponsored_unavailable", "x"), context)).not.toMatch(/sponsor/i);
  });
});

describe("signed-in example runs without a model picker", () => {
  const signed: Account = { ...account, authenticated: true, tier: "standard" };
  const conn = { id: "conn-one", provider: "meta", origin: "https://api.example.com", expires_at: "2026-10-28T20:00:00Z" };
  it("uses sponsored Meta when it's on, with no connection dropdown", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...signed, limits: { requests_per_day: 5, sponsored_enabled: true }, connections: [conn] } : result);
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · answered by test-model");
    expect(call).toHaveBeenCalledWith("/v1/demo", { sample_id: "en-support", language: "en" });
    expect(screen.queryByLabelText("Model connection")).not.toBeInTheDocument();
    expect(screen.queryByText(/Runs through your/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sponsor/i);
  });
  it("silently uses the first saved connection when sponsorship is off", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...signed, limits: { requests_per_day: 5, sponsored_enabled: false }, connections: [conn, { ...conn, id: "conn-two", provider: "openai" }] } : result);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    try {
      const user = userEvent.setup(); render(<HostedApp call={call} />);
      expect(await screen.findByText(/Runs through your Meta connection/)).toBeInTheDocument();
      expect(screen.queryByLabelText("Model connection")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Run live example" }));
      await screen.findByRole("alert");
      expect(new Headers(fetchSpy.mock.calls[0]![1]!.headers).get("X-PII-Guard-Connection")).toBe("conn-one");
      expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
      expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Robin Example");
    } finally { fetchSpy.mockRestore(); }
  });
  it("asks for a key instead of a failing run when there is neither", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...signed, limits: { requests_per_day: 5, sponsored_enabled: false }, connections: [] } : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Add a model key" })).toHaveAttribute("href", "#account");
    expect(screen.queryByRole("button", { name: /^Run/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Input")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sponsor/i);
    expect(document.querySelector("#demo [data-flow] [data-placeholder]")).toHaveTextContent("[[PERSON_3f9a1c]]");
  });
});

describe("positioning and copy (LAB-1466)", () => {
  it("leads with the positioning, names the model from the API and shows dated proof", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Send the work to the model.Keep the people out of it.");
    await screen.findByText(/Runs on Muse Spark 1.3/);
    expect(screen.getAllByText(/measured 27–28 Oct 2026/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Run the live demo" })).toHaveAttribute("href", "#demo");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/sponsor|Llama|GDPR|privacy firewall|Hungarian first|coming soon/i);
    // The differentiators come right after the hero, and only tools the integration docs test (LAB-1478, LAB-1499).
    expect(screen.getByRole("list", { name: "What makes it different" })).toHaveTextContent(/Agents, not just chat.*the coding agents Codex, OpenCode, Muse Code and pi: 115 requests, 0 values leaked, 0 of 10 turns refused.*No LLM, no GPU to mask.*EU languages, grammar-aware.*One person, one placeholder.*Measured in the open/);
    // The problem in one line, and the proof signals under the call to action (LAB-1499).
    expect(text).toMatch(/Legal, HR and finance teams in the EU can’t send case files to a hosted model/);
    expect(screen.getByRole("list", { name: "Proof" })).toHaveTextContent(/Tested with 4 real coding agents.*700\+ committed benchmark runs.*Published open NER model.*Apache-2\.0.*CI and tests/);
    // The Meta strip says what each model does, and Glimmer was the teacher, not a fine-tune.
    expect(screen.getByRole("list", { name: "Meta models and what each does" })).toHaveTextContent(/XLM-RoBERTa.*Muse Glimmer 30B.*served on Modal.*The teacher.*Muse Spark Open.*on Baseten.*SAM 3\.1.*Muse Spark 1\.3/);
    expect(text).not.toMatch(/LoRA|being finalised|not a live run|Checking availability|written by hand/);
    expect(text).not.toMatch(/Claude Code/);
    expect(screen.getByText(/^Next best: PrivAiTe 12\.7\s%$/)).toBeInTheDocument();
  });
  it("doesn't name a model the server didn't report", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...account, included_model: undefined } : result);
    render(<HostedApp call={call} />);
    await screen.findByText(/Runs on Meta’s model · no key needed/);
    expect(document.body.textContent).not.toMatch(/Muse Spark 1\.3/);
  });
  it("keeps one primary action in the header area: sign-in is secondary", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    await screen.findAllByText(/free runs/);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(nav.querySelector("a[href^='/.auth/login']")?.className).not.toMatch(/bg-primary/);
  });
});

describe("usage line", () => {
  it("says how many free runs are left and when they reset", () => {
    const now = Date.parse("2026-10-28T18:00:00Z");
    expect(usageLine({ ...account, limits: { requests_per_day: 5 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" } }, now)).toBe("0 of 5 free runs today · resets in 6 h");
    expect(usageLine({ ...account, limits: {}, usage: { requests_today: 1, resets_at: "2026-10-28T18:20:00Z" } }, now)).toBe("1 run today · resets in 20 min");
    expect(resetsIn({ ...account, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" } }, now)).toBe("in 6 h");
    expect(runsLeft({ ...account, limits: { requests_per_day: 5 }, usage: { requests_today: 2, resets_at: "" } })).toBe("3 of 5 free runs left today");
    expect(modelName("muse-spark-1.3")).toBe("Muse Spark 1.3");
  });
});

describe("hosted recovery copy", () => {
  it("mentions the static example only on the public page, and never says reconnect for a 404", () => {
    for (const error of [new ApiError(404, "not_found", "x"), new ApiError(429, "rate_limited", "x"), new ApiError(503, "unavailable", "x"), new Error("offline")]) {
      expect(recovery(error)).not.toMatch(/worked example/);
      expect(recovery(error, "site")).toMatch(/worked example/);
    }
    expect(recovery(new ApiError(404, "not_found", "x"))).not.toMatch(/Reconnect/);
    expect(recovery(new ApiError(404, "not_found", "x"), "site")).not.toMatch(/Reconnect/);
  });
});
