import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DeferredSection } from "./DeferredSection";

afterEach(() => { vi.unstubAllGlobals(); history.replaceState(null, "", "/"); });
it("waits for proximity and keeps mounted content after leaving the viewport", () => {
  let notify!: IntersectionObserverCallback;
  const disconnect = vi.fn();
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback) { notify = callback; }
    observe() {}
    disconnect = disconnect;
  });
  render(<DeferredSection anchor="images" className="min-h-[420px]"><p>Image example content</p></DeferredSection>);
  expect(screen.queryByText("Image example content")).toBeNull();
  act(() => notify([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver));
  expect(screen.getByText("Image example content")).toBeInTheDocument();
  expect(disconnect).toHaveBeenCalled();
});
it("loads an anchor destination without requiring intersection", () => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  render(<DeferredSection anchor="results" className="min-h-[340px]"><p>Chart content</p></DeferredSection>);
  act(() => { history.replaceState(null, "", "#results"); dispatchEvent(new HashChangeEvent("hashchange")); });
  expect(screen.getByText("Chart content")).toBeInTheDocument();
});

it("offers an explicit load action without scrolling", () => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  render(<DeferredSection anchor="images" className="min-h-[420px]"><p>Image example content</p></DeferredSection>);
  fireEvent.click(screen.getByRole("button", { name: "Load image example" }));
  expect(screen.getByText("Image example content")).toBeInTheDocument();
});
