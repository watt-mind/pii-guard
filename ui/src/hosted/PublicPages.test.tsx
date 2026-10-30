import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostedApp } from "./HostedApp";
import { type Account, type Requester } from "./api";

const visitor: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout", tier: "anonymous", providers: [], limits: { sponsored_enabled: false, requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-30T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const call = (signedIn = false) => vi.fn(async () => ({ ...visitor, authenticated: signedIn, limits: { ...visitor.limits, sponsored_enabled: signedIn } })) as unknown as Requester;
function open(hash: string) { history.replaceState(null, "", `/${hash}`); }
function navigate(hash: string) { act(() => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); }); }

describe("focused public pages", () => {
  it("keeps the hero and a short overview, without mounting the detailed pages", () => {
    render(<HostedApp call={call()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Send the work to the model.Keep the people out of it.");
    expect([...document.querySelectorAll("main > section")].map((el) => el.id)).toEqual(["", "image-preview", "how", "results", "account"]);
    expect(document.querySelector("#demo-input")).toBeNull();
    expect(screen.queryByRole("list", { name: "Meta models and what each does" })).toBeNull();
    expect(screen.queryByRole("list", { name: "What PII Guard doesn’t promise" })).toBeNull();
    expect(screen.getByRole("link", { name: "Explore the benchmarks" })).toHaveAttribute("href", "#evaluation");
  });

  it.each([["#demo", "Interactive demo"], ["#trust", "Privacy & trust"], ["#technical", "Technical overview"]])("opens %s at its page heading", async (hash, title) => {
    open(hash);
    const scroll = vi.spyOn(window, "scrollTo");
    render(<HostedApp call={call()} />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: title })).toHaveFocus());
    expect(scroll).toHaveBeenCalledWith(0, 0);
    expect(screen.queryByRole("heading", { name: /Send the work/ })).toBeNull();
    scroll.mockRestore();
  });

  it.each([["#images", "Interactive demo"], ["#data", "Privacy & trust"], ["#privacy", "Privacy & trust"], ["#meta", "Technical overview"], ["#europe", "Technical overview"]])("preserves the old public destination %s", (hash, title) => {
    open(hash);
    render(<HostedApp call={call()} console={() => <p>Private console</p>} />);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.queryByText("Private console")).toBeNull();
  });

  it("returns signed-in visitors to the overview through either public brand link", async () => {
    open("#trust");
    const user = userEvent.setup();
    render(<HostedApp call={call(true)} console={() => <p>Private console</p>} />);
    await screen.findByRole("link", { name: "Open console" });
    for (const link of screen.getAllByRole("link", { name: "PII Guard" })) expect(link).toHaveAttribute("href", "#site");
    await user.click(screen.getAllByRole("link", { name: "PII Guard" })[0]!);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Send the work to the model."));
    expect(screen.queryByText("Private console")).toBeNull();
  });

  it("keeps the disclosure and caveats on the demo and retains custom drafts across pages", async () => {
    open("#demo");
    const user = userEvent.setup();
    render(<HostedApp call={call(true)} console={() => <p>Private console</p>} />);
    expect(screen.getByText(/Detection can miss values\. PII Guard pseudonymizes/)).toHaveTextContent(/hosted guard receives your input in full/);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Input" }), "custom");
    await user.clear(screen.getByRole("textbox", { name: "Your text" }));
    await user.type(screen.getByRole("textbox", { name: "Your text" }), "Synthetic draft for the route test.");
    navigate("#trust");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Privacy & trust");
    expect(screen.getByText("Detection can miss")).toBeInTheDocument();
    navigate("#demo");
    expect(screen.getByRole("textbox", { name: "Your text" })).toHaveValue("Synthetic draft for the route test.");
    navigate("#site");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Send the work to the model.");
  });
  it.each(["Synthetic review draft.", ""])("preserves a custom draft and its language after sample comparison: %j", async (draft) => {
    open("#demo");
    const user = userEvent.setup();
    render(<HostedApp call={call(true)} />);
    const input = await screen.findByRole("combobox", { name: "Input" });
    await user.selectOptions(input, "custom");
    await user.clear(screen.getByRole("textbox", { name: "Your text" }));
    if (draft) await user.type(screen.getByRole("textbox", { name: "Your text" }), draft);
    await user.selectOptions(input, "curated");
    await user.click(within(screen.getByRole("radiogroup", { name: "Sample language" })).getByRole("radio", { name: "Hungarian" }));
    await user.selectOptions(input, "custom");
    expect(screen.getByRole("textbox", { name: "Your text" })).toHaveValue(draft);
    expect(within(screen.getByRole("radiogroup", { name: "Text language" })).getByRole("radio", { name: "English" })).toBeChecked();
  });

  it.each(["#demo", "#trust", "#technical"])("skips to main without leaving the signed-in public page: %s", async (hash) => {
    open(hash);
    const user = userEvent.setup();
    render(<HostedApp call={call(true)} console={() => <p>Private console</p>} />);
    await screen.findByRole("link", { name: "Open console" });
    await user.click(screen.getByRole("link", { name: "Skip to content" }));
    expect(location.hash).toBe(hash);
    expect(document.getElementById("main")).toHaveFocus();
    expect(screen.queryByText("Private console")).toBeNull();
  });

  it("preserves a custom draft when its language changes and labels the next steps", async () => {
    open("#demo");
    const user = userEvent.setup();
    render(<HostedApp call={call(true)} />);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Input" }), "custom");
    const editor = screen.getByRole("textbox", { name: "Your text" });
    expect(editor).toHaveFocus();
    await user.clear(editor);
    await user.type(editor, "Synthetic draft stays put.");
    await user.click(within(screen.getByRole("radiogroup", { name: "Text language" })).getByRole("radio", { name: "Hungarian" }));
    expect(editor).toHaveValue("Synthetic draft stays put.");
    expect(screen.getByRole("status")).toHaveTextContent("Language changed; your draft is preserved.");
    expect(screen.getByRole("navigation", { name: "On this page" })).toHaveTextContent("Text walkthroughImage masking");
    expect(screen.getByRole("complementary", { name: "Continue exploring" })).toHaveTextContent("Privacy & trust");
  });

  it("states policy-dependent image handling and self-hosting boundaries on Trust", () => {
    open("#trust");
    render(<HostedApp call={call()} />);
    expect(screen.getByText(/Self-hosting puts the guard/)).toHaveTextContent(/masked requests still go to your chosen model provider/);
    expect(screen.getByText(/Faces, ID photos and signatures are detected locally/)).toHaveTextContent(/project policy decides mask or keep.*stamp masking refuses/);
    expect(screen.getByRole("heading", { name: "Processing and access" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Images, retention and provider" })).toBeInTheDocument();
  });

  it("distinguishes model roles and remote detection on Technical overview", () => {
    open("#technical");
    render(<HostedApp call={call()} />);
    expect(screen.getByText("Training only")).toBeInTheDocument();
    expect(screen.getByText("Optional remote audit")).toBeInTheDocument();
    expect(screen.getByText(/The opt-in audit detector receives originals/)).toBeInTheDocument();
    expect(screen.getByText(/Answers in this demo after masking/)).toHaveTextContent(/Detection can miss values/);
    expect(screen.getByRole("complementary", { name: "Continue exploring" })).toHaveTextContent("integration guide");
  });

});
