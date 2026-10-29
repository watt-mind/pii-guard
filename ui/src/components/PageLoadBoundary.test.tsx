import { lazy, Suspense } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PageLoadBoundary } from "./PageLoadBoundary";

it("contains a rejected chunk and preserves other views until explicit reload", async () => {
  const BrokenView = lazy(() => Promise.reject(new Error("synthetic chunk download failure")));
  const reload = vi.fn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(<><input aria-label="Draft" defaultValue="Synthetic draft" /><PageLoadBoundary reload={reload}><Suspense fallback={<p>Loading</p>}><BrokenView /></Suspense></PageLoadBoundary></>);
    expect(await screen.findByRole("alert")).toHaveTextContent("This view could not be loaded");
    expect(screen.getByLabelText("Draft")).toHaveValue("Synthetic draft");
    expect(screen.queryByText("synthetic chunk download failure")).not.toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Reload page" }));
    expect(reload).toHaveBeenCalledTimes(1);
  } finally { log.mockRestore(); }
});
