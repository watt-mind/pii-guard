import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LocalSpan } from "../lib/analysis";
import { alignRestored } from "../lib/placeholders";
import { EntityTable } from "./EntityTable";
import { HighlightedText } from "./HighlightedText";
import { Legend } from "./Legend";
import { MaskedText } from "./MaskedText";
import { RestoredText } from "./RestoredText";

const text = "Teszt Elek, teszt.elek@example.com, Minta Kft.";
const spans: LocalSpan[] = [
  { start: 0, end: 10, entityType: "PERSON", score: 0.97, detector: "ner", placeholder: "[[PERSON_7f3a]]" },
  { start: 12, end: 34, entityType: "EMAIL", score: 1, detector: "rules", placeholder: "[[EMAIL_19c0]]" },
  { start: 36, end: 46, entityType: "ORGANIZATION", score: 0.84, detector: "ner", placeholder: null },
];

describe("HighlightedText", () => {
  it("marks every span, keeps the text intact, and describes type, detector and score", () => {
    const { container } = render(<HighlightedText text={text} spans={spans} activeKey={null} onActivate={() => {}} />);
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(3);
    expect([...marks].map((m) => m.dataset.entity)).toEqual(["PERSON", "EMAIL", "ORGANIZATION"]);
    expect(marks[0]).toHaveTextContent("Teszt Elek");
    expect(marks[0]).toHaveTextContent("Person, masked as [[PERSON_7f3a]], found by Multilingual NER, confidence 97%");
    expect(marks[2]).toHaveTextContent("kept by policy");
    // Visible text (screen-reader descriptions removed) equals the input.
    const clone = container.cloneNode(true) as HTMLElement;
    clone.querySelectorAll(".sr-only").forEach((n) => n.remove());
    expect(clone.textContent).toBe(text);
  });

  it("reports hover and focus with the span's placeholder as key", () => {
    const onActivate = vi.fn();
    const { container } = render(<HighlightedText text={text} spans={spans} activeKey={null} onActivate={onActivate} />);
    const [person, , org] = container.querySelectorAll("mark");
    fireEvent.mouseEnter(person!);
    expect(onActivate).toHaveBeenLastCalledWith("[[PERSON_7f3a]]");
    fireEvent.focus(org!);
    expect(onActivate).toHaveBeenLastCalledWith("span:36:46");
    fireEvent.blur(org!);
    expect(onActivate).toHaveBeenLastCalledWith(null);
  });

  it("highlights the active span", () => {
    const { container } = render(<HighlightedText text={text} spans={spans} activeKey="[[EMAIL_19c0]]" onActivate={() => {}} />);
    const active = container.querySelectorAll("mark[data-active]");
    expect(active).toHaveLength(1);
    expect(active[0]).toHaveTextContent("teszt.elek@example.com");
  });
});

describe("MaskedText", () => {
  it("renders placeholders as typed chips and contains no original values", () => {
    const masked = "[[PERSON_7f3a]], [[EMAIL_19c0]], Minta Kft.";
    const { container } = render(<MaskedText text={masked} />);
    const chips = container.querySelectorAll("[data-placeholder]");
    expect([...chips].map((c) => c.getAttribute("data-placeholder"))).toEqual(["[[PERSON_7f3a]]", "[[EMAIL_19c0]]"]);
    expect(chips[0]).toHaveTextContent("Person placeholder");
    expect(screen.getByTestId("masked-text")).not.toHaveTextContent("Teszt Elek");
  });

  it("marks unresolved placeholders", () => {
    const { container } = render(<MaskedText text="Hi [[PERSON_dead]]" unresolved={["[[PERSON_dead]]"]} />);
    expect(container.querySelector("[data-placeholder]")).toHaveTextContent("unknown placeholder, not restored");
  });
});

describe("RestoredText", () => {
  it("highlights restored values and shows unknown placeholders as such", () => {
    const masked = "Kedves [[PERSON_7f3a]]! Ki az a [[PERSON_dead]]?";
    const unmasked = "Kedves Teszt Elek! Ki az a [[PERSON_dead]]?";
    const segments = alignRestored(masked, unmasked, ["[[PERSON_dead]]"])!;
    const { container } = render(<RestoredText segments={segments} />);
    const restored = container.querySelectorAll("mark[data-restored]");
    expect(restored).toHaveLength(1);
    expect(restored[0]).toHaveAttribute("data-restored", "[[PERSON_7f3a]]");
    expect(restored[0]).toHaveTextContent("Teszt Elek");
    expect(container.querySelector("[data-placeholder='[[PERSON_dead]]']")).not.toBeNull();
  });
});

describe("Legend and EntityTable", () => {
  it("lists types with counts and flags kept types", () => {
    render(<Legend counts={new Map([["PERSON", 3], ["ORGANIZATION", 1]])} />);
    const list = screen.getByRole("list", { name: "Entity legend" });
    expect(list).toHaveTextContent("Person3");
    expect(list).toHaveTextContent("Organization1kept");
  });

  it("maps placeholders to types without any value column", () => {
    render(
      <EntityTable
        entities={[{ placeholder: "[[PERSON_7f3a]]", entity_type: "PERSON", count: 2 }]}
        spans={spans}
        activeKey={null}
        onActivate={() => {}}
      />,
    );
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("[[PERSON_7f3a]]");
    expect(table).toHaveTextContent("2×");
    expect(table).toHaveTextContent("Multilingual NER");
    expect(table).not.toHaveTextContent("Teszt Elek");
  });
});
