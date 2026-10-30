import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentTrafficTable, OpenModelsTable, ProofFacts } from "./LandingProof";
import { AGENT_TRAFFIC, HARD_CASES, INFLECTION, OPEN_MODELS, POLISH } from "./proof";

describe("landing proof sections (LAB-1656)", () => {
  it("agent traffic leads with over-masking against the lowest-leak other tool, on the same documents", () => {
    render(<AgentTrafficTable />);
    const table = screen.getByRole("table", { name: /agent traffic/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(AGENT_TRAFFIC.length);
    for (const [i, r] of AGENT_TRAFFIC.entries()) {
      expect(rows[i]).toHaveTextContent(r.system);
      expect(rows[i]).toHaveTextContent(`${r.leak} %`) // the matcher folds the no-break space;
      expect(rows[i]).toHaveTextContent(`${r.over} %`);
      if (r.partial) expect(within(rows[i]!).getByLabelText("ran on fewer languages")).toBeInTheDocument();
    }
    expect(screen.getByText(/of masked spans weren’t personal data, against 35.2/)).toHaveTextContent("PrivAiTe");
    expect(AGENT_TRAFFIC.every((r) => r.docs === AGENT_TRAFFIC[0]!.docs)).toBe(true);
    expect(screen.queryByText(/§ Not run on every language/)).toBeNull();
  });

  it("renders every open model with a link to its card", () => {
    render(<OpenModelsTable />);
    for (const m of OPEN_MODELS) expect(screen.getByRole("link", { name: m.model })).toHaveAttribute("href", `https://huggingface.co/${m.id}`);
  });

  it("states the narrower facts from proof.ts, MAPA nowhere", () => {
    const { container } = render(<ProofFacts />);
    const text = container.textContent ?? "";
    expect(text).toContain(`${HARD_CASES.rows[0].valid}\u00a0% of checksum-valid numbers`);
    expect(text).toContain(`${INFLECTION.leak}\u00a0% of values leaked`);
    expect(text).toContain(`${POLISH.leak}\u00a0% leaked on the public pl-pii-bench set`);
    expect(screen.getByRole("heading", { name: "No leaks in any language" })).toBeInTheDocument();
    expect(text).not.toMatch(/MAPA|EUR-Lex/);
  });
});
