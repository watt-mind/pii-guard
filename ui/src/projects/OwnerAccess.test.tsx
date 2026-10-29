import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { getOwnerToken, setOwnerToken } from "../api/localOwner";
import OwnerAccess from "./OwnerAccess";

afterEach(() => setOwnerToken(null));
describe("local guard access", () => {
  it("keeps the submitted token in memory, empties its field, and explicitly clears it", async () => {
    const user = userEvent.setup(); render(<OwnerAccess />);
    await user.click(screen.getByText("Local guard access"));
    const field = screen.getByLabelText(/^Owner API token/);
    expect(field).toHaveAttribute("type", "password"); expect(field).toHaveAttribute("autocomplete", "off");
    await user.type(field, "synthetic-owner-token"); await user.click(screen.getByRole("button", { name: "Use owner token" }));
    expect(getOwnerToken()).toBe("synthetic-owner-token"); expect(field).toHaveValue("");
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    await user.click(screen.getByRole("button", { name: "Clear owner token" }));
    expect(getOwnerToken()).toBeNull(); expect(screen.queryByText("synthetic-owner-token")).not.toBeInTheDocument();
  });
});
