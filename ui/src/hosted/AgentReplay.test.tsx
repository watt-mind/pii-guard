import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import recording from "../content/agentReplayRecording.json";
import { placeholderRegex } from "../lib/placeholders";
import AgentReplay from "./AgentReplay";
import { DemoVideo } from "./DemoVideo";
import { RECORD, replayValues, streamAt } from "./replayData";

const VALUES = ["Robin Example", "robin.example@example.com", "DE89 3704 0044 0532 0130 00"];

describe("agent-turn replay (LAB-1499)", () => {
  afterEach(() => vi.useRealTimers());

  it("the recording is value-free and every placeholder resolves to the fictional record", () => {
    const text = JSON.stringify(recording);
    for (const value of VALUES) expect(text).not.toContain(value);
    expect(RECORD).toContain(VALUES[0]);
    const values = replayValues();
    expect([...values.values()].sort()).toEqual([...VALUES].sort());
    for (const ph of text.match(placeholderRegex()) ?? []) expect(values.has(ph), ph).toBe(true);
    expect(recording.values_reaching_upstream).toBe(0);
  });

  it("the agent's chunks are the model's stream, with split placeholders held back", () => {
    for (const stream of [recording.send_call, recording.answer]) {
      expect(stream.agent.join("")).toBe(stream.upstream.join(""));
      // The gateway never releases half a placeholder.
      for (const piece of stream.agent) expect(piece.replace(placeholderRegex(), "")).not.toMatch(/\[\[|\]\]/);
      // Somewhere mid-stream a placeholder is split and held.
      const held = stream.upstream.map((_, k) => streamAt(stream.upstream, stream.agent, k + 1).held);
      expect(held.some((h) => h.includes("["))).toBe(true);
      expect(streamAt(stream.upstream, stream.agent, stream.upstream.length)).toMatchObject({ held: "", agent: stream.upstream.join("") });
    }
  });

  it("plays to the end, with restored values on the agent's side and placeholders on the model's", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const { container } = render(<AgentReplay />);
    await user.click(screen.getByRole("button", { name: "Play the replay" }));
    expect(screen.getByRole("button", { name: "Pause the replay" })).toBeInTheDocument();
    for (let i = 0; i < 60; i++) await act(async () => { vi.advanceTimersByTime(1_500); });
    expect(screen.getByRole("button", { name: "Replay the replay" })).toBeInTheDocument();
    const restored = [...container.querySelectorAll("mark")].map((m) => m.textContent);
    expect(restored).toContain("robin.example@example.com");
    expect(container.querySelector("[data-placeholder]")).not.toBeNull();
    expect(screen.getByText(/0 values reached the model/)).toBeInTheDocument();
  });

  it("with reduced motion shows the finished turn and no controls", () => {
    const original = window.matchMedia;
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener: () => {}, removeEventListener: () => {} })) as unknown as typeof window.matchMedia;
    try {
      const { container } = render(<AgentReplay />);
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(container.textContent).toContain("that the refund is on its way.");
    } finally { window.matchMedia = original; }
  });

  it("the demo video slot is a poster that links to the video", () => {
    render(<DemoVideo url="https://video.example.com/demo" />);
    expect(screen.getByRole("link", { name: /Watch the 3-minute demo video/ })).toHaveAttribute("href", "https://video.example.com/demo");
  });
});
