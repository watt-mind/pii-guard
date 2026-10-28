import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { HostedApp } from "./HostedApp";
import { recovery, type Account, type DemoResult, type Requester } from "./api";
import { usageLine } from "./landing";

const account: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const result: DemoResult = { sample_id: "hu-support", language: "hu", original: "Synthetic original", masked: "[[PERSON_1a2b]]", answer: "Hello [[PERSON_1a2b]]", restored: "Hello Synthetic Person", model: "test-model", session_id: "test-session", request_id: "test-request", entities: [{ start: 0, end: 9, type: "PERSON" }] };

function requester(handler: (path: string, body?: unknown, method?: string) => unknown) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => handler(path, body, method)) as unknown as Requester;
}

describe("public hosted workflow", () => {
  it("sends sign-in back to the console instead of the provider's bare page", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    await screen.findAllByText(/free runs today/);
    expect(screen.getByText(/Runs on Meta Muse Spark · no key needed/)).toHaveTextContent("0 of 3 free runs today");
    expect(document.body.textContent).not.toMatch(/sponsor/i);
    const links = screen.getAllByRole("link", { name: "Sign in with Google" });
    expect(links.length).toBeGreaterThanOrEqual(2);
    for (const link of links) expect(link).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
  });
  it("labels the static mechanism, requests only a server sample, and shows all live stages", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const user = userEvent.setup();
    render(<HostedApp call={call} />);
    expect(screen.getByText("Example · not a live run")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · answered by test-model");
    expect(call).toHaveBeenCalledWith("/v1/demo", { sample_id: "en-support", language: "en" });
    const stages = screen.getAllByRole("article").map((a) => a.querySelector(".document")?.textContent?.replace(/ \([^)]*\)/g, ""));
    expect(stages).toEqual([result.original, result.masked, result.answer, result.restored]);
    expect(screen.getByText("Live result ready: Person masked, answer restored. Model: test-model.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Detected entity types" })).toHaveTextContent("Person 1");
    expect(document.querySelector("#demo .flow .hl-original")).toHaveTextContent("Synthetic original");
    expect(document.querySelector("#demo .flow .hl-placeholder")).toHaveTextContent("[[PERSON_1a2b]]");
    expect(document.querySelector("#demo .flow .hl-restored")).toHaveTextContent("Synthetic Person");
    expect(screen.queryByLabelText("Your text")).not.toBeInTheDocument();
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
    expect(document.querySelector("#demo .flow .hl-restored")).toHaveTextContent("Robin Example");
    expect(screen.getByText("Live run did not complete · showing the example")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show the example" }));
    expect(screen.getByText("Example · not a live run")).toBeInTheDocument();
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
    expect(screen.getByText("Live run did not complete · showing the example")).toBeInTheDocument();
  });
  it("offers honest unavailable state with reconnect and keeps the static walkthrough", async () => {
    const call = requester(() => { throw new Error("offline"); });
    render(<HostedApp call={call} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Run live example" })).toBeDisabled();
    expect(screen.getByText("Example · not a live run")).toBeInTheDocument();
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

describe("sponsorship off (zero budget until the provider authorises it)", () => {
  const off: Account = { ...account, limits: { requests_per_day: 5, images_per_day: 0, max_image_bytes: 0, sponsored_enabled: false } };
  it("offers no live run to guests, keeps the worked example and points to sign-in", async () => {
    const call = requester((path) => path === "/v1/account" ? off : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Sign in with Google to run your own text" })).toHaveAttribute("href", account.login_url);
    expect(screen.queryByRole("button", { name: "Run live example" })).not.toBeInTheDocument();
    expect(screen.getByText("Example · not a live run")).toBeInTheDocument();
    expect(document.querySelector("#demo .flow .hl-placeholder")).toHaveTextContent("[[PERSON_3f9a1c]]");
    expect(screen.queryByText(/No login needed/)).not.toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/v1/demo", expect.anything());
    expect(screen.getByText("Live runs are paused right now. The worked example below shows the same flow, step by step.")).toBeInTheDocument();
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
    expect(recovery(new ApiError(503, "sponsored_unavailable", "x"), "site")).toMatch(/^Live runs are paused right now/);
    expect(recovery(new ApiError(503, "sponsored_unavailable", "x"))).toMatch(/Live runs on Meta’s model are paused/);
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
      expect(document.querySelector("#demo .flow .hl-restored")).toHaveTextContent("Robin Example");
    } finally { fetchSpy.mockRestore(); }
  });
  it("asks for a key instead of a failing run when there is neither", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...signed, limits: { requests_per_day: 5, sponsored_enabled: false }, connections: [] } : result);
    render(<HostedApp call={call} />);
    expect(await screen.findByRole("link", { name: "Add a provider key" })).toHaveAttribute("href", "#account");
    expect(screen.queryByRole("button", { name: /^Run/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Input")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sponsor/i);
    expect(document.querySelector("#demo .flow .hl-placeholder")).toHaveTextContent("[[PERSON_3f9a1c]]");
  });
});

describe("usage line", () => {
  it("says how many free runs are left and when they reset", () => {
    const now = Date.parse("2026-10-28T18:00:00Z");
    expect(usageLine({ ...account, limits: { requests_per_day: 5 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" } }, now)).toBe("0 of 5 free runs today · resets in 6 h");
    expect(usageLine({ ...account, limits: {}, usage: { requests_today: 1, resets_at: "2026-10-28T18:20:00Z" } }, now)).toBe("1 run today · resets in 20 min");
  });
});

describe("hosted recovery copy", () => {
  it("mentions the static example only on the public page, and never says reconnect for a 404", () => {
    for (const error of [new ApiError(404, "not_found", "x"), new ApiError(429, "rate_limited", "x"), new ApiError(503, "unavailable", "x"), new Error("offline")]) {
      expect(recovery(error)).not.toMatch(/static example/);
      expect(recovery(error, "site")).toMatch(/static example/);
    }
    expect(recovery(new ApiError(404, "not_found", "x"))).not.toMatch(/Reconnect/);
    expect(recovery(new ApiError(404, "not_found", "x"), "site")).not.toMatch(/Reconnect/);
  });
});
