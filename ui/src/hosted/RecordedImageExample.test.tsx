import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { RecordedImageExample } from "./RecordedImageExample";

vi.mock("./ImageShowcase", async () => { throw new Error("synthetic chunk download detail"); });

it("contains a rejected image import while preserving the surrounding draft and recovery choices", async () => {
  const report = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<main><label>Synthetic draft<input /></label><RecordedImageExample /></main>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the recorded image example");
    await userEvent.setup().type(screen.getByRole("textbox", { name: "Synthetic draft" }), "Draft stays available.");
    expect(await screen.findByText("The recorded image example could not be loaded")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Synthetic draft" })).toHaveValue("Draft stays available.");
    expect(screen.getByRole("link", { name: "text walkthrough" })).toHaveAttribute("href", "#run");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
    expect(screen.getByText(/clears unsaved drafts/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("synthetic chunk download detail");
  } finally { report.mockRestore(); }
});
