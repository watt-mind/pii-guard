import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SAMPLES } from "./content/samples";
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
  // Most tests start on the Playground's Text tab; the console's own routes are tested below.
  history.replaceState(null, "", "#playground/text");
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("App in demo mode", () => {
  it("starts with the English support example and preserves explicit language and sample choices", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    const language = screen.getByRole("combobox", { name: "Document language" });
    expect(language).toHaveValue("en");
    expect(screen.getByLabelText("Document text")).toHaveValue(SAMPLES.find((s) => s.id === "support")!.text);
    await user.selectOptions(language, "hu");
    await user.type(screen.getByLabelText("Document text"), " ");
    expect(language).toHaveValue("hu");
    await user.click(screen.getByRole("radio", { name: /Property sale contract/i }));
    expect(language).toHaveValue("hu");
    expect(screen.getByLabelText("Document text")).toHaveValue(SAMPLES.find((s) => s.id === "contract")!.text);
    await user.click(screen.getByRole("radio", { name: /Support ticket/i }));
    expect(language).toHaveValue("en");
  });

  it("shows the demo badge when the API is unreachable", async () => {
    render(<App api={offlineApi()} mock={createMockClient()} />);
    expect(await screen.findByText("Demo mode", { selector: "span" })).toBeInTheDocument();
    expect(await screen.findByText(/API is not reachable, using the demo engine/)).toBeInTheDocument();
    expect(screen.getByText("API offline")).toBeInTheDocument();
    // Nobody chose the demo engine, so the notice above the content escalates.
    expect(screen.getByText("API not reachable.")).toBeInTheDocument();
    expect(screen.queryByText("Demo mode.")).toBeNull();
  });

  it("masks a sample, then restores the simulated answer on the round-trip screen", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);

    await user.click(screen.getByRole("radio", { name: /Property sale contract/i }));
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const playground = screen.getByRole("tabpanel", { name: "Text" });
    const masked = await within(playground).findByTestId("masked-text");
    expect(masked).toHaveTextContent(/\[\[PERSON_[0-9a-f]{4,}\]\]/);
    expect(masked).not.toHaveTextContent("Bárdos Kinga");
    expect(within(playground).getByRole("table")).toHaveTextContent("Tax ID (HU)");

    await user.click(screen.getByRole("radio", { name: "Round trip" }));
    const panel = screen.getByRole("tabpanel", { name: "Text" });
    const answer = within(panel).getByRole("textbox", { name: "Simulated model answer" }) as HTMLTextAreaElement;
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
    await user.click(screen.getByRole("radio", { name: /Property sale contract/i }));
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    await within(screen.getByRole("tabpanel", { name: "Text" })).findByTestId("masked-text");
    await user.click(screen.getByRole("radio", { name: "Round trip" }));

    const panel = screen.getByRole("tabpanel", { name: "Text" });
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
    expect(await screen.findByText("v0.1.0")).toBeInTheDocument();
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
    expect(await screen.findByText("API up", { selector: "span" })).toBeInTheDocument();
    // A quiet footer line: the version, with the state in the tooltip and for screen readers.
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /^API up\./ })).toBeInTheDocument();
    expect(screen.queryByText("API not reachable.")).toBeNull();
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const note = await screen.findByTestId("scope-note");
    expect(note).toHaveTextContent(/\d+ values masked by /);
    expect(note).toHaveTextContent("Anything without a highlight on the left was not detected");
    expect(screen.queryByText(/The model never sees the originals/)).toBeNull();

    const playground = screen.getByRole("tabpanel", { name: "Text" });
    const firstMark = playground.querySelector("mark")!;
    await user.hover(firstMark);
    expect(await screen.findByTestId("entity-popover")).toHaveTextContent(/found by/);
    await user.unhover(firstMark);
    expect(screen.queryByTestId("entity-popover")).toBeNull();

    await user.click(screen.getByRole("radio", { name: "Round trip" }));
    expect(screen.getByRole("heading", { level: 2, name: /masked values restored/ })).toBeInTheDocument();
  });
});

describe("Known values and Chat in demo mode", () => {
  it("pre-loads a known value, masks its inflected form with the known marker and reuses the session", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    await user.click(screen.getByText("Known values"));
    await user.click(screen.getByRole("button", { name: "Try a fictional example" }));
    const input = screen.getByLabelText("Document text");
    await user.clear(input);
    await user.type(input, "Kedves Gyakorló Tihamérnak küldöm.");
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const panel = screen.getByRole("tabpanel", { name: "Text" });
    const masked = await within(panel).findByTestId("masked-text");
    expect(masked).toHaveTextContent(/Kedves \[\[PERSON_[0-9a-f]{4,}\]\] \(Person placeholder\)nak küldöm\./);
    expect(panel.querySelector("[data-known]")).not.toBeNull();
    expect(within(panel).getByTestId("known-counts")).toHaveTextContent("1 known value loaded in this session (1 new)");
    await user.click(screen.getByRole("button", { name: /run again/i }));
    await waitFor(() => expect(within(panel).getByTestId("known-counts")).toHaveTextContent("1 known value loaded in this session (0 new)"));
  });

  it("shows a refused known value inline", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    await user.click(screen.getByText("Known values"));
    await user.click(screen.getByRole("button", { name: "+ Add a value" }));
    await user.type(screen.getByLabelText("Known value 1"), "ab");
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    expect(await screen.findByText(/Refused:/)).toBeInTheDocument();
    expect(screen.getByLabelText("Known value 1")).toHaveAttribute("aria-invalid", "true");
  });

  it("sends a chat message through the simulated gateway", async () => {
    const user = userEvent.setup();
    const mock = createMockClient();
    const { createMockChat } = await import("./api/chat");
    render(<App api={offlineApi()} mock={mock} chat={{ mock: createMockChat(mock, { delayMs: 0 }) }} />);
    await user.click(screen.getByRole("tab", { name: /chat/i }));
    const panel = screen.getByRole("tabpanel", { name: /chat/i });
    await user.click(within(panel).getByRole("button", { name: /send through PII Guard/i }));
    const received = await within(panel).findByRole("region", { name: "What the model received" });
    await waitFor(() => expect(received).toHaveTextContent(/\[\[PERSON_[0-9a-f]{4,}\]\]/));
    const back = within(panel).getByRole("region", { name: "What you got back" });
    await waitFor(() => expect(back.querySelector("mark[data-restored]")).not.toBeNull());
    expect(back).toHaveTextContent("Jane Placeholder");
  });
});

describe("Known values example", () => {
  it("adds a fictional value and a sentence using it, and says when no known value was found", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} />);
    await user.click(screen.getByText("Known values"));
    await user.click(screen.getByRole("button", { name: "Try a fictional example" }));
    expect((screen.getByLabelText("Document text") as HTMLTextAreaElement).value).toContain("Please hand the keys to Gyakorló Tihamér's assistant.");
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const panel = screen.getByRole("tabpanel", { name: "Text" });
    await within(panel).findByTestId("masked-text");
    expect(panel.querySelector("[data-known]")).not.toBeNull();
    // Editing a known value makes the result stale.
    await user.type(screen.getByLabelText("Known value 1"), "x");
    expect(within(panel).getByText("The settings changed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    expect(await within(panel).findByText(/None of your known values appear in this document/)).toBeInTheDocument();
  });
});

