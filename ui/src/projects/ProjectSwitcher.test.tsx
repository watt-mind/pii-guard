// A failed projects fetch shows a retryable indicator, never silent null (LAB-1714).
// Fictional projects only.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { localRequest } from "./request";
import { setSelectedProject } from "./selection";

vi.mock("./request", () => ({ localRequest: vi.fn() }));
const mockRequest = vi.mocked(localRequest);

const projects = {
  projects: [{ id: "project-one", name: "Example support desk", default_policy_id: "policy-one" }],
  default_project_id: "project-one",
};

beforeEach(() => {
  setSelectedProject(null);
  mockRequest.mockReset();
});

it("shows a retryable failure indicator when the projects fetch fails", async () => {
  mockRequest.mockRejectedValue(new Error("synthetic projects fetch failure"));
  render(<ProjectSwitcher />);
  expect(await screen.findByRole("status")).toHaveTextContent("Projects unavailable");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(screen.queryByText("synthetic projects fetch failure")).not.toBeInTheDocument();
});

it("recovers on retry after a transient failure", async () => {
  let calls = 0;
  mockRequest.mockImplementation(async (path: string) => {
    if (path !== "/v1/projects") return { endpoints: [] };
    calls += 1;
    if (calls === 1) throw new Error("synthetic transient fetch failure");
    return projects;
  });
  render(<ProjectSwitcher />);
  expect(await screen.findByRole("status")).toHaveTextContent("Projects unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("button", { name: "Project: Example support desk" })).toBeInTheDocument();
  expect(screen.queryByRole("status")).toBeNull();
});
