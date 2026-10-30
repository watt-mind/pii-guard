import { act, render, screen, waitFor } from "@testing-library/react";
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
});
