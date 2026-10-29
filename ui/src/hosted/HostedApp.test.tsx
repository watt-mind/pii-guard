import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as chatApi from "../api/chat";
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
    expect(links.length).toBeGreaterThanOrEqual(2);
    for (const link of links) expect(link).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
  });
  it("labels the static mechanism, requests only a server sample, and shows all live stages", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const user = userEvent.setup();
    render(<HostedApp call={call} />);
    expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
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
  it("keeps pending feedback honest until the server returns the whole result", async () => {
    let finish!: (value: DemoResult) => void;
    const pending = new Promise<DemoResult>((resolve) => { finish = resolve; });
    const call = requester((path) => path === "/v1/account" ? account : pending);
    const user = userEvent.setup();
    render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
    expect(screen.getByText("Waiting for the live result")).toBeInTheDocument();
    expect(screen.getByText(/Individual stage progress isn’t available/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Live run progress" })).not.toBeInTheDocument();
    expect(document.querySelector("#demo")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("radio", { name: "Hungarian" })).toBeDisabled();
    await act(async () => { finish(result); });
    expect(screen.queryByText("Waiting for the live result")).not.toBeInTheDocument();
    expect(document.querySelector("#demo")).toHaveAttribute("aria-busy", "false");
    expect(screen.getByText("Live result · answered by test-model")).toBeInTheDocument();
  });
  it("clears previous success on quota failure and makes static recovery explicit", async () => {
    let runs = 0;
    const call = requester((path) => { if (path === "/v1/account") return account; if (++runs === 1) return result; throw new ApiError(429, "quota_exceeded", "sensitive server text must never render"); });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
    await screen.findByText("Live result · answered by test-model");
    await user.click(screen.getByRole("button", { name: "Run the live demo" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.queryByText(/sensitive server text/)).not.toBeInTheDocument();
    // A live failure never blanks the recorded run.
    expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Jane Placeholder");
    expect(screen.getByText("Live run didn’t finish · showing the recorded run")).toBeInTheDocument();
    // The recorded run is already on screen: no way back to it. Used up: no retry, sign in instead.
    expect(screen.queryByRole("button", { name: "Back to the recorded run" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in for more runs" })).toBeInTheDocument();
    expect(screen.queryByText(/free runs left today/)).not.toBeInTheDocument();
  });
  it("offers Try again after a provider failure (LAB-1466)", async () => {
    const call = requester((path) => { if (path === "/v1/account") return account; throw new ApiError(502, "upstream_error", "x"); });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("rejects incomplete live results rather than showing a successful model run", async () => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, restored: "" });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
    await screen.findByRole("alert"); expect(screen.queryByText("Live result · answered by test-model")).not.toBeInTheDocument();
  });
  it.each([null, {}, { start: 0.5, end: 2, type: "PERSON" }, { start: 3, end: 2, type: "PERSON" }, { start: 0, end: 2, type: null }])("rejects malformed entity metadata without rendering a live success: %j", async (entity) => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, entities: [entity] });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Live result · answered by test-model")).not.toBeInTheDocument();
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.getByText("Live run didn’t finish · showing the recorded run")).toBeInTheDocument();
  });
  it("offers honest unavailable state with reconnect and keeps the static walkthrough", async () => {
    const call = requester(() => { throw new Error("offline"); });
    render(<HostedApp call={call} />);
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Run the live demo" })).not.toBeInTheDocument();
    expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
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
    await screen.findByRole("button", { name: "Run the live demo" });
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
    await screen.findByRole("button", { name: "Run the live demo" });
    await user.click(screen.getByRole("link", { name: "Run the live demo" }));
    await screen.findByText("Live result · answered by test-model");
    expect(scroll).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
    vi.unstubAllGlobals(); scroll.mockRestore();
  });
  it("opens the custom-text editor from the signed-in hero without sending a request", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...account, authenticated: true } : result);
    const scroll = spyScroll();
    try {
      const user = userEvent.setup(); render(<HostedApp call={call} />);
      await user.click(await screen.findByRole("link", { name: "Run your own text" }));
      expect(screen.getByRole("combobox", { name: "Input" })).toHaveValue("custom");
      expect(screen.getByRole("textbox", { name: "Your text" })).toBeInTheDocument();
      expect(screen.getByText("Your text · ready for a live run")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "See exactly what the model sees." })).toHaveFocus();
      expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
    } finally { scroll.mockRestore(); }
  });
  it("explains why an empty or whitespace-only custom draft cannot run", async () => {
    const call = requester(() => ({ ...account, authenticated: true }));
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Input" }), "custom");
    const editor = screen.getByRole("textbox", { name: "Your text" });
    await user.clear(editor);
    expect(screen.getByText("Your text · add text to run")).toBeInTheDocument();
    await user.type(editor, "   ");
    expect(screen.getByText("Your text · add text to run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run your text" })).toBeDisabled();
    await user.type(editor, "Synthetic draft.");
    expect(screen.getByText("Your text · ready for a live run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run your text" })).toBeEnabled();
  });
  it("clears a shown custom result and reopens the editor from the signed-in hero", async () => {
    const send = vi.fn(async () => ({ sessionId: "synthetic", answer: "Synthetic answer", maskedAnswer: "Synthetic answer", maskedMessages: [{ role: "user" as const, content: "Synthetic draft." }], masked: 0, mode: "fast" as const, ms: 1 }));
    const chat = vi.spyOn(chatApi, "createHttpChat").mockReturnValue({ kind: "api", listModels: async () => ["test-model"], send });
    const scroll = spyScroll();
    try {
      const call = requester(() => ({ ...account, authenticated: true }));
      const user = userEvent.setup(); render(<HostedApp call={call} />);
      await user.selectOptions(await screen.findByRole("combobox", { name: "Input" }), "custom");
      await user.type(screen.getByRole("textbox", { name: "Your text" }), "Synthetic draft.");
      await user.click(screen.getByRole("button", { name: "Run your text" }));
      await screen.findByRole("button", { name: "Edit your text" });
      await user.click(screen.getByRole("link", { name: "Run your own text" }));
      expect(screen.queryByRole("button", { name: "Edit your text" })).not.toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Your text" })).toBeInTheDocument();
    } finally { chat.mockRestore(); scroll.mockRestore(); }
  });
  it("lets a custom result be edited with the draft and focus preserved, or return to the recording", async () => {
    const draft = "Synthetic draft. ".repeat(25);
    const send = vi.fn(async () => ({ sessionId: "synthetic", answer: "Synthetic answer", maskedAnswer: "Synthetic answer", maskedMessages: [{ role: "user" as const, content: draft }], masked: 0, mode: "fast" as const, ms: 1 }));
    const chat = vi.spyOn(chatApi, "createHttpChat").mockReturnValue({ kind: "api", listModels: async () => ["test-model"], send });
    try {
      const call = requester(() => ({ ...account, authenticated: true }));
      const user = userEvent.setup(); render(<HostedApp call={call} />);
      await user.selectOptions(await screen.findByRole("combobox", { name: "Input" }), "custom");
      await user.clear(screen.getByRole("textbox", { name: "Your text" }));
      await user.paste(draft);
      await user.click(screen.getByRole("button", { name: "Run your text" }));
      await user.click(await screen.findByRole("button", { name: "Edit your text" }));
      expect(screen.getByRole("textbox", { name: "Your text" })).toHaveValue(draft);
      expect(screen.getByRole("textbox", { name: "Your text" })).toHaveFocus();
      expect(send).toHaveBeenCalledTimes(1);
      await user.click(screen.getByRole("button", { name: "Run your text" }));
      await user.click(await screen.findByRole("button", { name: "Back to the recorded run" }));
      expect(screen.getByRole("combobox", { name: "Input" })).toHaveValue("curated");
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
    } finally { chat.mockRestore(); }
  });
  it("preserves a custom draft when the hero CTA is activated again", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...account, authenticated: true } : result);
    const scroll = spyScroll();
    try {
      const user = userEvent.setup(); render(<HostedApp call={call} />);
      const cta = await screen.findByRole("link", { name: "Run your own text" });
      await user.click(cta);
      const editor = screen.getByRole("textbox", { name: "Your text" });
      await user.clear(editor);
      await user.type(editor, "Synthetic draft for testing.");
      await user.click(cta);
      expect(editor).toHaveValue("Synthetic draft for testing.");
      expect(screen.getByRole("combobox", { name: "Input" })).toHaveValue("custom");
      expect(screen.getByRole("heading", { name: "See exactly what the model sees." })).toHaveFocus();
      expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
    } finally { scroll.mockRestore(); }
  });
  it("stays a plain anchor when guest runs are paused or a signed-in visitor needs a key", async () => {
    const off: Account = { ...account, limits: { requests_per_day: 5, sponsored_enabled: false } };
    for (const acct of [off, { ...off, authenticated: true }]) {
      const call = requester((path) => path === "/v1/account" ? acct : path === "/v1/demo" ? result : []);
      const user = userEvent.setup(); const { unmount } = render(<HostedApp call={call} />);
      const cta = await screen.findByRole("link", { name: "See the demo" });
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
  it("offers no live run to guests, keeps the recorded run and points to sign-in", async () => {
    const call = requester((path) => path === "/v1/account" ? off : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Sign in to run your own text" })).toHaveAttribute("href", account.login_url);
    expect(screen.queryByRole("button", { name: "Run the live demo" })).not.toBeInTheDocument();
    expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
    expect(document.querySelector("#demo [data-flow] [data-placeholder]")).toHaveTextContent(/\[\[PERSON_[0-9a-f]{6}\]\]/);
    expect(screen.queryByText(/No login needed/)).not.toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
    expect(screen.getByText("Free runs are paused right now")).toBeInTheDocument();
    expect(screen.getByText("The recorded run below shows the same flow, answered by a real model.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the demo" })).toHaveAttribute("href", "#demo");
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
    await user.click(await screen.findByRole("button", { name: "Run the live demo" }));
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
      await user.click(screen.getByRole("button", { name: "Run the live demo" }));
      await screen.findByRole("alert");
      expect(new Headers(fetchSpy.mock.calls[0]![1]!.headers).get("X-PII-Guard-Connection")).toBe("conn-one");
      expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
      expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Jane Placeholder");
    } finally { fetchSpy.mockRestore(); }
  });
  it("asks for a key instead of a failing run when there is neither", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...signed, limits: { requests_per_day: 5, sponsored_enabled: false }, connections: [] } : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Add a model key" })).toHaveAttribute("href", "#account");
    expect(screen.queryByRole("button", { name: /^Run/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Input")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sponsor/i);
    expect(document.querySelector("#demo [data-flow] [data-placeholder]")).toHaveTextContent(/\[\[PERSON_[0-9a-f]{6}\]\]/);
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
    expect(text).not.toMatch(/sponsor|Llama|GDPR[- ]compliant|compliant with GDPR|anonymi[sz]ed data|privacy firewall|Hungarian first|coming soon/i);
    // The differentiators come right after the hero, and only tools the integration docs test (LAB-1478, LAB-1499).
    expect(screen.getByRole("list", { name: "What makes it different" })).toHaveTextContent(/Agents, not just chat.*the coding agents Codex, OpenCode, Muse Code and pi: 115 requests, 0 values leaked, 0 of 10 turns refused.*No LLM, no GPU to mask.*Inflected EU languages.*One person, one placeholder.*Measured in the open/);
    // The problem in one line, and the proof signals under the call to action (LAB-1499).
    expect(text).toMatch(/Legal, HR and finance teams in the EU often can’t send case files to a hosted model/);
    expect(screen.getByRole("list", { name: "Proof" })).toHaveTextContent(/Tested with 4 real coding agents.*700\+ committed benchmark runs.*Published open NER model.*Apache-2\.0.*CI and tests/);
    // The Meta strip says what each model does, and Glimmer was the teacher, not a fine-tune.
    expect(screen.getByRole("list", { name: "Meta models and what each does" })).toHaveTextContent(/XLM-RoBERTa.*Muse Glimmer 30B.*served on Modal.*The teacher.*Muse Spark Open.*on Baseten.*SAM 3\.1.*Muse Spark 1\.3/);
    expect(text).not.toMatch(/LoRA|being finali[sz]ed|not a live run|Checking availability|written by hand/);
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

describe("landing round L3 (LAB-1515, LAB-1503)", () => {
  it("opens the demo on the recorded real-model run of the server's own sample, panes under the section h2", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    await screen.findByText(/Runs on Muse Spark 1.3/);
    expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
    expect(screen.getByText(/^Recorded \d+ \w{3} 2026 on this hosted preview: the real gateway masked the server’s fictional sample and Muse Spark 1\.3 answered\./)).toBeInTheDocument();
    const stages = ["demo-input", "demo-sent", "demo-answer", "demo-restored"].map((id) => document.querySelector(`[aria-labelledby="${id}-title"] .doc`)?.textContent ?? "");
    expect(stages[0]).toContain("I am Jane Placeholder");
    expect(stages[1]).not.toContain("Jane Placeholder");
    expect(stages[2]).toMatch(/\[\[PERSON_[0-9a-f]{6}\]\]/);
    expect(stages[3]).toContain("Jane Placeholder");
    for (const id of ["demo-input", "demo-sent", "demo-answer", "demo-restored"]) expect(document.getElementById(`${id}-title`)?.tagName).toBe("H3");
    expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
  });
  it("has the Why Europe cards with the disclaimer and the three steps, with no compliance claim", async () => {
    render(<HostedApp call={requester((path) => path === "/v1/account" ? account : result)} />);
    await screen.findByText(/Runs on Muse Spark 1.3/);
    expect(screen.getByRole("list", { name: "EU rules and what PII Guard does" })).toHaveTextContent(/Minimize before you send.*Less personal data crossing borders.*Built for regulated work/);
    expect(screen.getByText(/^A technical measure, not legal advice or a compliance feature: .* transfer assessment\./)).toBeInTheDocument();
    expect(screen.getByText(/placeholders go out, the mapping stays with your guard\. Your transfer obligations remain\./)).toBeInTheDocument();
    expect(screen.getByText(/PII Guard lists every call in Logs, outbound check included\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Meta Model API terms ↗" })).toHaveAttribute("href", "https://dev.meta.ai/legal/terms-of-service");
    expect(screen.getByRole("link", { name: "What we don’t claim ↗" })).toHaveAttribute("href", expect.stringMatching(/docs\/eu-regulation\.md#what-we-dont-claim$/));
    expect(screen.getByRole("list", { name: "Live in three steps" })).toHaveTextContent(/Change one base URL\..*Masking and restoring happen automatically: streaming, tool calls, images\..*See every request in Logs, with its outbound check result\./);
    expect(document.body.textContent).not.toMatch(/GDPR[- ]compliant|special categor|anonymi[sz]ed data/i);
  });
  it("offers a section menu where the nav links don't fit, closed after a link is followed", async () => {
    const user = userEvent.setup();
    render(<HostedApp call={requester((path) => path === "/v1/account" ? account : result)} />);
    const menu = screen.getByText("Sections").closest("details")!;
    await user.click(screen.getByText("Sections"));
    expect(menu).toHaveAttribute("open");
    await user.click(screen.getAllByRole("link", { name: "Why Europe" })[0]!);
    expect(menu).not.toHaveAttribute("open");
    await user.click(screen.getByText("Sections"));
    await user.keyboard("{Escape}");
    expect(menu).not.toHaveAttribute("open");
    expect(screen.getByText("Sections").closest("summary")).toHaveFocus();
    await user.click(screen.getByText("Sections"));
    await user.click(screen.getByRole("heading", { level: 1 }));
    expect(menu).not.toHaveAttribute("open");
  });
});

describe("landing recovery and keyboard navigation (LAB-1540)", () => {
  it("retries beside the recorded demo, prevents duplicate retries and recovers live actions", async () => {
    let finish!: (value: Account) => void;
    const call = vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockImplementationOnce(() => new Promise<Account>((resolve) => { finish = resolve; }));
    const user = userEvent.setup(); render(<HostedApp call={call as Requester} />);
    await user.click(await screen.findByRole("button", { name: "Retry live service" }));
    for (const button of screen.getAllByRole("button", { name: "Retrying…" })) expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getAllByRole("button", { name: "Retrying…" })[0]!);
    expect(screen.getByText("Recorded run · real model · fictional data")).toBeInTheDocument();
    finish(account);
    expect(await screen.findByRole("button", { name: "Run the live demo" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry live service" })).not.toBeInTheDocument();
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("can retry again after another outage without losing the recording", async () => {
    const call = vi.fn().mockRejectedValue(new Error("offline"));
    const user = userEvent.setup(); render(<HostedApp call={call as Requester} />);
    await user.click(await screen.findByRole("button", { name: "Retry live service" }));
    expect(await screen.findByRole("button", { name: "Retry live service" })).toBeEnabled();
    expect(document.querySelector("#demo [data-flow] [data-restored]")).toHaveTextContent("Jane Placeholder");
    expect(call).toHaveBeenCalledTimes(2);
  });

  it("closes when keyboard focus leaves and focuses the destination after following a section", async () => {
    const user = userEvent.setup(); render(<HostedApp call={requester(() => account)} />);
    const toggle = screen.getByText("Sections").closest("summary")!;
    const menu = toggle.closest("details")!;
    await user.click(toggle);
    await user.tab({ shift: true });
    expect(menu).not.toHaveAttribute("open");
    await user.click(toggle);
    await user.click(screen.getAllByRole("link", { name: "Why Europe" })[0]!);
    expect(menu).not.toHaveAttribute("open");
    await waitFor(() => expect(screen.getByRole("heading", { name: "What EU rules ask, and what PII Guard does." })).toHaveFocus());
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
      expect(recovery(error)).not.toMatch(/recorded run/);
      expect(recovery(error, "site")).toMatch(/recorded run/);
    }
    expect(recovery(new ApiError(404, "not_found", "x"))).not.toMatch(/Reconnect/);
    expect(recovery(new ApiError(404, "not_found", "x"), "site")).not.toMatch(/Reconnect/);
  });
});
