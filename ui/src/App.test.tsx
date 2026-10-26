import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { HttpGuardClient } from "./api/http";
import { ApiError, UnreachableError } from "./api/http";
import { createMockClient } from "./api/mock";

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down };
}

beforeEach(() => {
  localStorage.clear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("App in demo mode", () => {
  it("shows the demo badge when the API is unreachable", async () => {
    render(<App api={offlineApi()} mock={createMockClient()} />);
    expect(await screen.findByText("Demo mode", { selector: "span" })).toBeInTheDocument();
    expect(await screen.findByText(/API is not reachable, using the demo engine/)).toBeInTheDocument();
    expect(screen.getByText("API offline")).toBeInTheDocument();
  });

  it("masks a sample, then restores the simulated answer on the round-trip screen", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);

    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const playground = screen.getByRole("tabpanel", { name: /playground/i });
    const masked = await within(playground).findByTestId("masked-text");
    expect(masked).toHaveTextContent(/\[\[PERSON_[0-9a-f]{4,}\]\]/);
    expect(masked).not.toHaveTextContent("Bárdos Kinga");
    expect(within(playground).getByRole("table")).toHaveTextContent("Tax ID (HU)");

    await user.click(screen.getByRole("button", { name: /send it to the model/i }));
    const panel = screen.getByRole("tabpanel", { name: /round trip/i });
    const answer = within(panel).getByLabelText("Simulated model answer") as HTMLTextAreaElement;
    expect(answer.value).toMatch(/Seller: \[\[PERSON_[0-9a-f]{4,}\]\]/);
    expect(answer.value).not.toContain("Bárdos Kinga");

    await user.click(within(panel).getByRole("button", { name: "Restore" }));
    const restored = await within(panel).findByTestId("restored-text");
    expect(restored).toHaveTextContent("Seller: Bárdos Kinga");
    expect(restored.querySelectorAll("mark[data-restored]").length).toBeGreaterThanOrEqual(9);
  });

  it("streams the answer and flags a placeholder the model invented", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    await within(screen.getByRole("tabpanel", { name: /playground/i })).findByTestId("masked-text");
    await user.click(screen.getByRole("tab", { name: /round trip/i }));

    const panel = screen.getByRole("tabpanel", { name: /round trip/i });
    await user.click(within(panel).getByRole("button", { name: /invented placeholder/i }));
    await user.selectOptions(within(panel).getByLabelText("Stream speed"), "fast");
    await user.click(within(panel).getByRole("button", { name: /stream/i }));

    expect(await within(panel).findByTestId("chunk-stream")).toBeInTheDocument();
    await waitFor(() => expect(within(panel).getByText("Unknown placeholder left as is")).toBeInTheDocument(), { timeout: 8000 });
    expect(within(panel).getByTestId("restored-text")).toHaveTextContent("Bárdos Kinga");
  }, 15000);

  it("fails closed and says nothing was sent when the live API rejects the request", async () => {
    const user = userEvent.setup();
    const blocked = () => Promise.reject(new ApiError(503, "detection_failed", "detector timed out"));
    const api: HttpGuardClient = {
      health: () => Promise.resolve({ status: "ok", version: "0.1.0" }),
      analyze: blocked,
      mask: blocked,
      unmask: blocked,
    };
    render(<App api={api} mock={createMockClient()} />);
    expect(await screen.findByText("API v0.1.0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Blocked. Nothing was sent to the model.");
    expect(alert).toHaveTextContent("detection_failed");
    expect(screen.queryByTestId("masked-text")).toBeNull();
  });

  it("shows a neutral Connecting state, without the demo banner, while the health check is pending", () => {
    const pending = () => new Promise<never>(() => {});
    const api: HttpGuardClient = { health: pending, analyze: pending, mask: pending, unmask: pending };
    render(<App api={api} mock={createMockClient()} />);
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(screen.queryByText("Demo mode", { selector: "span" })).toBeNull();
    expect(screen.queryByText("Demo mode.")).toBeNull();
  });

  it("clears the document", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByLabelText("Document text")).toHaveValue("");
    expect(screen.getByRole("button", { name: /mask document/i })).toBeDisabled();
  });
});

describe("App against a live API", () => {
  function liveApi(): HttpGuardClient {
    // A live engine that, like a rules-only build, finds only some entities.
    const backend = createMockClient();
    return {
      health: () => Promise.resolve({ status: "ok", version: "0.1.0" }),
      analyze: backend.analyze,
      mask: backend.mask,
      unmask: backend.unmask,
    };
  }

  it("states what the engine did instead of claiming everything was masked, and shows details on hover", async () => {
    const user = userEvent.setup();
    render(<App api={liveApi()} mock={createMockClient()} />);
    expect(await screen.findByText("Live")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const note = await screen.findByTestId("scope-note");
    expect(note).toHaveTextContent(/\d+ values masked by .*Rules \+ checksum/);
    expect(note).toHaveTextContent("Anything without a highlight on the left was not detected");
    expect(screen.queryByText(/The model never sees the originals/)).toBeNull();

    const playground = screen.getByRole("tabpanel", { name: /playground/i });
    const firstMark = playground.querySelector("mark")!;
    await user.hover(firstMark);
    expect(await screen.findByTestId("entity-popover")).toHaveTextContent(/found by/);
    await user.unhover(firstMark);
    expect(screen.queryByTestId("entity-popover")).toBeNull();

    await user.click(screen.getByRole("tab", { name: /round trip/i }));
    expect(screen.getByRole("heading", { level: 1, name: /masked values restored/ })).toBeInTheDocument();
  });
});
