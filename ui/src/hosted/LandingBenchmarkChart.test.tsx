import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LandingBenchmarkChart } from "./LandingBenchmarkChart";

describe("landing benchmark comparison", () => {
  it("starts with the public CEE-PII dataset and exposes exact values without relying on color", () => {
    render(<LandingBenchmarkChart />);
    expect(screen.getByRole("combobox", { name: "Test dataset" })).toHaveValue("1");
    const rows = within(screen.getByRole("list", { name: "Leak rate by tool" })).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual(["PII GuardRules + NER0.8%", "PrivAiTe4.4%", "Presidio36.5%", "LLM Guard75.8%"]);
    expect(screen.getByText(/not a guarantee for your documents/)).toHaveTextContent("CEE-PII (451)");
  });

  it("updates all tools and the caption together when changing datasets, including zero leak", async () => {
    const user = userEvent.setup();
    render(<LandingBenchmarkChart />);
    await user.selectOptions(screen.getByRole("combobox", { name: "Test dataset" }), "0");
    const rows = within(screen.getByRole("list", { name: "Leak rate by tool" })).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual(["PII GuardRules + NER0.0%", "PrivAiTe13.0%", "Presidio25.5%", "LLM Guard46.3%"]);
    expect(screen.getByText(/not a guarantee for your documents/)).toHaveTextContent("Hand-written de + en + hu + pl (62)");
  });
});
