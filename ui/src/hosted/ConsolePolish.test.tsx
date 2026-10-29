import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { Settings, ProviderConnections } from "./AccountPanels";
import { SetupChecklist } from "./SetupChecklist";
import { HostedSessionContext } from "./session";
import { ClientSetup } from "./ClientSetup";
import { resetFirstRun } from "./firstRun";
import { publish } from "./setup";
import type { Account, Requester } from "./api";

const account: Account = {
  mode: "hosted", authenticated: true, tier: "standard", providers: [],
  login_url: "/login", logout_url: "/logout", limits: { sponsored_enabled: false },
  usage: { requests_today: 0, resets_at: "2026-10-30T00:00:00Z" },
  state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [],
};
beforeEach(() => { publish(null); localStorage.clear(); });

it("makes a failed setup read recoverable and announces a pending retry", async () => {
  let finish!: (value: unknown) => void;
  const call = vi.fn().mockRejectedValueOnce(new Error("private server detail"))
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; })) as unknown as Requester;
  render(<SetupChecklist call={call} account={account} active calls={0} />);
  const retry = await screen.findByRole("button", { name: "Retry setup" });
  expect(screen.queryByText(/private server detail/)).not.toBeInTheDocument();
  await userEvent.setup().click(retry);
  expect(screen.getByRole("status")).toHaveTextContent("Checking setup progress");
  expect(screen.queryByRole("button", { name: "Retry setup" })).not.toBeInTheDocument();
  await act(async () => { finish({ projects: [] }); });
  expect(await screen.findByText("0 of 5 done")).toBeInTheDocument();
  expect(screen.getByText("Free runs are paused. Connect your own provider key to choose a model.")).toBeInTheDocument();
});

it("keeps the last progress visible when a refresh fails", async () => {
  publish({ provider: true, policy: true, endpoint: false, key: false, call: false });
  const call = vi.fn().mockRejectedValue(new Error("unavailable")) as unknown as Requester;
  render(<SetupChecklist call={call} account={account} active calls={0} />);
  await screen.findByRole("button", { name: "Retry setup" });
  expect(screen.getByText("2 of 5 done")).toBeInTheDocument();
  expect(screen.getByText(/Showing the last available progress/)).toBeInTheDocument();
});

it("labels paused free inference without changing the selected connection", () => {
  const call = vi.fn() as unknown as Requester;
  render(<HostedSessionContext.Provider value={{ account, call, refresh: async () => {}, error: "" }}><ProviderConnections /></HostedSessionContext.Provider>);
  expect(screen.getByRole("option", { name: "Meta Muse Spark (free runs paused)" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Playground chat sends through" })).toHaveValue("");
  expect(screen.getByText(/No provider connections yet/)).toHaveTextContent("Free runs are paused");
});

it("rejects whitespace-only keys and trims pasted surrounding whitespace", async () => {
  const call = vi.fn().mockResolvedValue({}) as unknown as Requester;
  render(<Settings account={account} call={call} refresh={async () => {}} onDisconnect={() => {}} />);
  const user = userEvent.setup();
  const key = screen.getByLabelText(/Provider API key/);
  await user.type(key, "   ");
  expect(screen.getByRole("button", { name: "Connect provider" })).toBeDisabled();
  await user.type(key, "synthetic-test-key  ");
  await user.click(screen.getByRole("button", { name: "Connect provider" }));
  await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/connections", { provider: "openai", api_key: "synthetic-test-key" }));
  expect(key).toHaveValue("");
});

it("replaces endpoint failure with pending feedback while retrying", async () => {
  resetFirstRun();
  let finish!: (value: unknown) => void;
  let reads = 0;
  const call = vi.fn(async (path: string) => {
    if (path !== "/v1/projects") throw new Error("unavailable");
    if (++reads === 1) throw new Error("unavailable");
    return new Promise((resolve) => { finish = resolve; });
  }) as unknown as Requester;
  render(<ClientSetup call={call} />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Retry" }));
  expect(screen.getByRole("status")).toHaveTextContent("Preparing your endpoint");
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  await waitFor(() => expect(reads).toBe(2));
  await act(async () => { finish({ projects: [] }); });
  expect(await screen.findByTestId("client-setup-preview")).toBeInTheDocument();
});
