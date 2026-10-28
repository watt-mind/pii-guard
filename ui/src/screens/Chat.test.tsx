import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMockChat, type ChatClient, type ChatTurnRequest, type ChatTurnResult } from "../api/chat";
import { ApiError } from "../api/http";
import { createMockClient } from "../api/mock";
import { Chat, MODEL_PREF } from "./Chat";

const META = ["muse-image-1.0", "sam-3.1", "muse-voice-transcribe-1.0", "muse-spark-1.2", "muse-wonder-1.0", "muse-spark-1.3"];

function liveChat(opts: { models?: () => Promise<string[]>; send?: (req: ChatTurnRequest) => Promise<ChatTurnResult> } = {}) {
  const calls: ChatTurnRequest[] = [];
  const client: ChatClient = {
    kind: "api",
    listModels: opts.models ?? (() => Promise.resolve(META)),
    send: (req) => {
      calls.push(req);
      return (
        opts.send?.(req) ??
        Promise.resolve({ sessionId: "s_1", answer: "ok", maskedAnswer: "ok", maskedMessages: req.messages, masked: 0, mode: req.mode, ms: 1, finishReason: "stop" })
      );
    },
  };
  return { client, calls };
}

const failWith = (err: Error) => () => Promise.reject(err);

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    // storage blocked: the screen must cope anyway
  }
});

describe("Chat model picker (LAB-1335)", () => {
  it("defaults to muse-spark-1.3 from /v1/models and lists only chat-capable ids", async () => {
    const { client } = liveChat();
    render(<Chat client={client} live draft={null} />);
    const picker = await screen.findByRole("combobox", { name: "Model" });
    expect(picker).toHaveValue("muse-spark-1.3");
    const ids = [...(picker as HTMLSelectElement).options].map((o) => o.value);
    expect(ids).toEqual(["muse-spark-1.2", "muse-wonder-1.0", "muse-spark-1.3"]);
  });

  it("uses the last-used model when the upstream still lists it, and remembers a new pick", async () => {
    localStorage.setItem(`pii-guard:${MODEL_PREF}`, "muse-wonder-1.0");
    const user = userEvent.setup();
    const { client, calls } = liveChat();
    render(<Chat client={client} live draft={null} />);
    const picker = await screen.findByRole("combobox", { name: "Model" });
    expect(picker).toHaveValue("muse-wonder-1.0");
    await user.selectOptions(picker, "muse-spark-1.2");
    expect(localStorage.getItem(`pii-guard:${MODEL_PREF}`)).toBe("muse-spark-1.2");
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.model).toBe("muse-spark-1.2");
  });

  it("ignores a remembered model the upstream no longer serves", async () => {
    localStorage.setItem(`pii-guard:${MODEL_PREF}`, "meta-models/muse-spark-open-1026");
    const { client } = liveChat();
    render(<Chat client={client} live draft={null} />);
    expect(await screen.findByRole("combobox", { name: "Model" })).toHaveValue("muse-spark-1.3");
  });

  it("asks for a model id when /v1/models fails, and won't send without one", async () => {
    const { client, calls } = liveChat({ models: failWith(new ApiError(502, "upstream_unavailable", "x")) });
    render(<Chat client={client} live draft={null} />);
    expect(await screen.findByTestId("models-failed")).toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Model" });
    expect(input).toHaveValue("");
    expect(screen.getByRole("button", { name: /send through pii-guard/i })).toBeDisabled();
    const user = userEvent.setup();
    await user.type(input, "my-model");
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    await waitFor(() => expect(calls[0]?.model).toBe("my-model"));
  });

  it("shows no picker for the demo engine, which still answers", { timeout: 15000 }, async () => {
    const user = userEvent.setup();
    const mock = createMockClient();
    render(<Chat client={createMockChat(mock, { delayMs: 0 })} live={false} draft={null} />);
    expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Model" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    expect(await screen.findByText(/Answers? received and restored/i, undefined, { timeout: 8000 })).toBeInTheDocument();
  });
});

describe("Chat error copy per code (LAB-1335)", () => {
  async function sendWith(err: Error) {
    const user = userEvent.setup();
    const { client } = liveChat({ send: failWith(err) });
    render(<Chat client={client} live draft={null} />);
    await screen.findByRole("combobox", { name: "Model" });
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    return screen.findByRole("alert", undefined, { timeout: 5000 });
  }

  it("upstream_error: the masked request reached the upstream, which answered 404", async () => {
    const alert = await sendWith(new ApiError(404, "upstream_error", "upstream returned HTTP 404"));
    expect(alert).toHaveTextContent("The upstream refused the masked request (HTTP 404).");
    expect(alert).toHaveTextContent("model not found on the upstream? Pick another model");
    expect(alert).toHaveTextContent("Nothing unmasked left pii-guard.");
    expect(alert).not.toHaveTextContent("Nothing was sent to the model");
    expect(alert).not.toHaveTextContent("fails closed");
    expect(screen.getByText("The masked request was sent; the upstream refused it before answering.")).toBeInTheDocument();
  });

  it("detection_failed keeps the fail-closed text", async () => {
    const alert = await sendWith(new ApiError(503, "detection_failed", "detector timed out"));
    expect(alert).toHaveTextContent("Blocked. Nothing was sent to the model.");
    expect(alert).toHaveTextContent("fails closed");
    expect(screen.getByText("Nothing was sent.")).toBeInTheDocument();
  });

  it("blocked_entity keeps the policy text", async () => {
    const alert = await sendWith(new ApiError(403, "blocked_entity", "blocked"));
    expect(alert).toHaveTextContent("Blocked by policy. Nothing was sent to the model.");
  });
});

describe("Chat empty reasoning answer (LAB-1335)", () => {
  it("hints to raise max tokens when the answer is empty with finish_reason length", async () => {
    const user = userEvent.setup();
    const send = vi.fn((req: ChatTurnRequest) =>
      Promise.resolve({ sessionId: "s_1", answer: "", maskedAnswer: "", maskedMessages: req.messages, masked: 0, mode: req.mode, ms: 1, finishReason: "length" }),
    );
    const { client } = liveChat({ send });
    render(<Chat client={client} live draft={null} />);
    await screen.findByRole("combobox", { name: "Model" });
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    expect(await screen.findByTestId("empty-answer-hint", undefined, { timeout: 5000 })).toHaveTextContent("used its whole token budget reasoning");
    expect(screen.getByTestId("empty-answer-hint")).toHaveTextContent("raise max tokens");
  });
});

describe("Chat detection modes (LAB-1435)", () => {
  // Native radios: the visible text is on the wrapping label.
  const radios = () => screen.getAllByRole("radio").map((r) => r.closest("label")?.textContent);

  it("offers fast and audit by default, as the local console always has", async () => {
    const { client } = liveChat();
    render(<Chat client={client} live draft={null} />);
    await screen.findByRole("combobox", { name: "Model" });
    expect(radios()).toEqual(["Fast", "Audit"]);
  });

  it("offers only the server's modes, and never sends one it doesn't offer", async () => {
    const user = userEvent.setup();
    const { client, calls } = liveChat();
    render(<Chat client={client} live draft={null} modes={["fast"]} />);
    await screen.findByRole("combobox", { name: "Model" });
    expect(radios()).toEqual(["Fast"]);
    expect(screen.getByRole("radio", { name: "Fast" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.mode).toBe("fast");
  });
});

describe("Chat recovery and reset (LAB-1441)", () => {
  it("retries a refused message from the blocked notice", async () => {
    const user = userEvent.setup();
    let fail = true;
    const { client, calls } = liveChat({
      send: (req) =>
        fail
          ? Promise.reject(new ApiError(503, "detection_failed", "detector timed out"))
          : Promise.resolve({ sessionId: "s_1", answer: "ok", maskedAnswer: "ok", maskedMessages: req.messages, masked: 0, mode: req.mode, ms: 1, finishReason: "stop" }),
    });
    render(<Chat client={client} live draft={null} />);
    await screen.findByRole("combobox", { name: "Model" });
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    const alert = await screen.findByRole("alert", undefined, { timeout: 5000 });
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]!.messages.at(-1)!.content).toBe(calls[0]!.messages.at(-1)!.content);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("asks before New conversation clears the turns, and Cancel keeps them", async () => {
    const user = userEvent.setup();
    const { client } = liveChat();
    render(<Chat client={client} live draft={null} />);
    await screen.findByRole("combobox", { name: "Model" });
    await user.click(screen.getByRole("button", { name: /send through pii-guard/i }));
    await screen.findAllByRole("article", { name: "Chat turn" });
    const trigger = await screen.findByRole("button", { name: "New conversation" });
    await user.click(trigger);
    expect(screen.getByRole("group", { name: "Start a new conversation?" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getAllByRole("article", { name: "Chat turn" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "New conversation" }));
    await user.click(screen.getByRole("button", { name: "Clear and start over" }));
    expect(screen.queryByRole("article", { name: "Chat turn" })).not.toBeInTheDocument();
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
  });
});
