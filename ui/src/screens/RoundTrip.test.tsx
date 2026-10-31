// RoundTrip failure surfaces (LAB-1714): the empty state shows a failed mask attempt
// instead of a dead button, and every inbound recovery lives in the notice's action slot.
// Fictional data only.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { RoutingClient } from "../api/engine";
import { ApiError } from "../api/http";
import type { RunResult } from "../lib/run";
import { RoundTrip } from "./RoundTrip";

const client = { unmask: vi.fn() } as unknown as RoutingClient;

const result: RunResult = {
  input: "Seller: [[PERSON_ab12]]",
  language: "en",
  spans: [],
  mask: { masked_text: "Seller: [[PERSON_ab12]]", session_id: "synthetic-session", entities: [] },
  links: null,
  engine: "mock",
  ms: 1,
  sampleId: null,
  known: null,
  knownSignature: "",
};

it("shows a failed mask attempt with Retry in the empty state", () => {
  const onRun = vi.fn();
  render(
    <RoundTrip
      client={client}
      result={null}
      answer=""
      onAnswer={() => {}}
      running={false}
      onRun={onRun}
      maskError={{ code: "unreachable", message: "synthetic guard unreachable" }}
    />,
  );
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("The guard is not reachable. Nothing was sent.");
  fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
  expect(onRun).toHaveBeenCalledTimes(1);
});

it("shows no error in the empty state before the first attempt", () => {
  render(
    <RoundTrip client={client} result={null} answer="" onAnswer={() => {}} running={false} onRun={() => {}} maskError={null} />,
  );
  expect(screen.getByText("No masked document yet")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("retries the restore in place for an inbound failure", async () => {
  vi.mocked(client.unmask).mockRejectedValueOnce(new ApiError(503, "upstream_unavailable", "synthetic upstream outage"));
  render(
    <RoundTrip
      client={client}
      result={result}
      answer="Seller: [[PERSON_ab12]]"
      onAnswer={() => {}}
      running={false}
      onRun={() => {}}
      maskError={null}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Restore" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("The answer could not be restored.");
  const retry = within(alert).getByRole("button", { name: "Retry" });
  vi.mocked(client.unmask).mockResolvedValueOnce({ data: { text: "Seller: Example Name", unresolved: [] }, engine: "mock" });
  fireEvent.click(retry);
  expect(await screen.findByTestId("restored-text")).toBeInTheDocument();
});

it("recovers an expired session from inside the notice, with no separate retry", async () => {
  vi.mocked(client.unmask).mockRejectedValue(new ApiError(404, "not_found", "synthetic expired session"));
  const onRun = vi.fn();
  render(
    <RoundTrip
      client={client}
      result={result}
      answer="Seller: [[PERSON_ab12]]"
      onAnswer={() => {}}
      running={false}
      onRun={onRun}
      maskError={null}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Restore" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("This session is no longer known to the guard.");
  expect(within(alert).queryByRole("button", { name: "Retry" })).toBeNull();
  fireEvent.click(within(alert).getByRole("button", { name: "Mask the document again" }));
  expect(onRun).toHaveBeenCalledTimes(1);
});
