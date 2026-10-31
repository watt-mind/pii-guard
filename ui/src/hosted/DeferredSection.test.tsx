import { lazy } from "react";
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

it("shows a retryable error notice when the lazy import fails (LAB-1714)", async () => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  const BrokenChart = lazy(() => Promise.reject(new Error("synthetic chunk download failure")));
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<DeferredSection anchor="results" className="min-h-[340px]"><BrokenChart /></DeferredSection>);
    fireEvent.click(screen.getByRole("button", { name: "Load comparison chart" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This section could not be loaded");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("synthetic chunk download failure")).not.toBeInTheDocument();
  } finally { log.mockRestore(); }
});

it("recovers on retry after a transient failure (LAB-1714)", async () => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  let throws = true;
  const Flaky = () => { if (throws) throw new Error("synthetic transient render failure"); return <p>Recovered content</p>; };
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<DeferredSection anchor="results" className="min-h-[340px]"><Flaky /></DeferredSection>);
    fireEvent.click(screen.getByRole("button", { name: "Load comparison chart" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    throws = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByText("Recovered content")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  } finally { log.mockRestore(); }
});

it("offers a page reload when the section keeps failing (LAB-1714)", async () => {
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });
  const BrokenChart = lazy(() => Promise.reject(new Error("synthetic persistent chunk failure")));
  const reload = vi.fn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<DeferredSection anchor="results" className="min-h-[340px]" reload={reload}><BrokenChart /></DeferredSection>);
    fireEvent.click(screen.getByRole("button", { name: "Load comparison chart" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    // The rejected chunk stays rejected, so the remount fails again and the notice escalates.
    expect(await screen.findByRole("button", { name: "Reload page" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload page" }));
    expect(reload).toHaveBeenCalledTimes(1);
  } finally { log.mockRestore(); }
});
