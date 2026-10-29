import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PublicHeader } from "./PublicHeader";

function menu() { return screen.getByText("Menu").closest("details")!; }
function trigger() { return menu().querySelector("summary")!; }

describe("public header navigation", () => {
  it("separates account access and preserves sign-in and signed-in destinations", () => {
    const { rerender } = render(<PublicHeader accountHref="/.auth/login/google?post_login_redirect_uri=%2F%23evaluation" />);
    const account = screen.getByRole("link", { name: "Sign in to console" });
    expect(account).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23evaluation");
    expect(screen.getByRole("navigation")).not.toContainElement(account);
    rerender(<PublicHeader signedIn accountHref="#overview" />);
    expect(screen.getByRole("link", { name: "Open console" })).toHaveAttribute("href", "#overview");
  });
  it("exposes every resource, marks the active section and restores Escape focus", async () => {
    const user = userEvent.setup();
    render(<PublicHeader current="data" accountHref="#overview" />);
    // jsdom does not implement native summary Enter activation; checked in browser.
    await user.click(trigger());
    expect(menu()).toHaveAttribute("open");
    expect(within(menu()).getByRole("link", { name: "Privacy" })).toHaveAttribute("aria-current", "location");
    for (const [label, href] of [["Model details", "#meta"], ["Image masking", "#images"], ["Privacy limits", "#privacy"], ["Why Europe", "#europe"], ["Get started", "#account"], ["Self-hosting guide", "https://github.com/watt-mind/pii-guard#try-it"]]) {
      expect(within(menu()).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    await user.tab();
    await user.keyboard("{Escape}");
    expect(menu()).not.toHaveAttribute("open");
    expect(trigger()).toHaveFocus();
  });
  it("dismisses on outside pointer, focus leave, and responsive breakpoint changes", async () => {
    const user = userEvent.setup(); render(<PublicHeader accountHref="#overview" />);
    await user.click(trigger());
    await user.click(screen.getByRole("link", { name: "PII Guard" }));
    expect(menu()).not.toHaveAttribute("open");
    await user.click(trigger());
    screen.getByRole("link", { name: "Sign in to console" }).focus();
    expect(menu()).not.toHaveAttribute("open");
    await user.click(trigger());
    fireEvent(window, new Event("resize"));
    expect(menu()).not.toHaveAttribute("open");
    expect(trigger()).toHaveFocus();
  });
  it("closes before focusing a destination rendered by hash routing, including repeat navigation", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<PublicHeader accountHref="#overview" />);
    await user.click(trigger());
    await user.click(within(menu()).getByRole("link", { name: "Why Europe" }));
    expect(menu()).not.toHaveAttribute("open");
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    rerender(<><PublicHeader accountHref="#overview" /><main><section id="europe"><h2 tabIndex={-1}>Synthetic destination</h2></section></main></>);
    await waitFor(() => expect(screen.getByRole("heading")).toHaveFocus());
    expect(scroll).toHaveBeenCalled();
    await user.click(trigger());
    await user.click(within(menu()).getByRole("link", { name: "Why Europe" }));
    await waitFor(() => expect(screen.getByRole("heading")).toHaveFocus());
    scroll.mockRestore();
  });
  it("dismisses on page scroll while allowing the panel itself to scroll", async () => {
    const user = userEvent.setup(); render(<PublicHeader accountHref="#overview" />);
    await user.click(trigger());
    fireEvent.scroll(menu().querySelector(".public-nav-panel")!);
    expect(menu()).toHaveAttribute("open");
    const scrollY = vi.spyOn(window, "scrollY", "get").mockReturnValue(100);
    fireEvent.scroll(window);
    expect(menu()).not.toHaveAttribute("open");
    scrollY.mockRestore();
  });
  it("preserves modified-click navigation without closing or moving focus", async () => {
    const user = userEvent.setup(); render(<PublicHeader accountHref="#overview" />);
    await user.click(trigger());
    fireEvent.click(within(menu()).getByRole("link", { name: "Why Europe" }), { ctrlKey: true });
    expect(menu()).toHaveAttribute("open");
  });
});
