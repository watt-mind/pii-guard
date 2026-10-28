// Playground → Text: sample radios, a busy run that keeps focus, and retry from a blocked run
// (LAB-1441). Fictional data only.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SAMPLES } from "../content/samples";
import type { RunError } from "../lib/run";
import { Playground } from "./Playground";

function renderPlayground(over: Partial<Parameters<typeof Playground>[0]> = {}) {
  const props = {
    text: "Write to jane.placeholder@example.net",
    onText: vi.fn(),
    sampleId: null,
    onSample: vi.fn(),
    result: null,
    running: false,
    error: null,
    onRun: vi.fn(),
    onContinue: vi.fn(),
    language: "en" as const,
    onLanguage: vi.fn(),
    known: [],
    onKnown: vi.fn(),
    onTryKnown: vi.fn(),
    knownSignature: "",
    ...over,
  };
  const view = render(<Playground {...props} />);
  return { ...props, ...view };
}

describe("Playground Text (LAB-1441)", () => {
  it("offers the samples as one radio group, with the chosen one checked", async () => {
    const user = userEvent.setup();
    const { onSample, rerender, ...props } = renderPlayground({ sampleId: SAMPLES[0]!.id });
    const group = screen.getByRole("group", { name: "Fictional samples" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(SAMPLES.length);
    expect(within(group).getByRole("radio", { name: new RegExp(SAMPLES[0]!.title) })).toBeChecked();
    await user.click(within(group).getByRole("radio", { name: new RegExp(SAMPLES[1]!.title) }));
    expect(onSample).toHaveBeenCalledWith(SAMPLES[1]);
    rerender(<Playground {...props} onSample={onSample} sampleId={SAMPLES[1]!.id} />);
    expect(within(group).getByRole("radio", { name: new RegExp(SAMPLES[1]!.title) })).toBeChecked();
  });

  it("keeps Mask document focusable while it runs", async () => {
    const user = userEvent.setup();
    const { onRun, rerender, ...props } = renderPlayground();
    const button = screen.getByRole("button", { name: /mask document/i });
    await user.click(button);
    expect(onRun).toHaveBeenCalledTimes(1);
    rerender(<Playground {...props} onRun={onRun} running />);
    const busy = screen.getByRole("button", { name: /masking/i });
    expect(busy).not.toBeDisabled();
    expect(busy).toHaveAttribute("aria-disabled", "true");
    await user.click(busy);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("keeps the language select and Mask document above the panes, Clear in the pane's footer (LAB-1448)", () => {
    renderPlayground();
    const pane = screen.getByRole("region", { name: "Your document" });
    const header = pane.querySelector("header")!;
    const footer = pane.querySelector("footer")!;
    // The pane headers hold only their titles, so the two stay the same height.
    expect(within(header).queryByRole("combobox")).toBeNull();
    expect(within(header).queryByRole("button")).toBeNull();
    expect(screen.getByRole("combobox", { name: "Document language" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mask document/i })).toBeInTheDocument();
    expect(within(footer).getByRole("button", { name: "Clear" })).toBeInTheDocument();
  });

  it("retries a blocked run from the notice", async () => {
    const user = userEvent.setup();
    const error: RunError = { code: "detection_failed", message: "detection_failed" };
    const { onRun } = renderPlayground({ error });
    const alert = screen.getByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});
