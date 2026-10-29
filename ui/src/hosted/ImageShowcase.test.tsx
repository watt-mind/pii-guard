import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IMAGE_LABELS } from "../content/imageLabels";
import ImageShowcase from "./ImageShowcase";

const holder = /\[\[PERSON_[0-9a-f]+\]\]/.exec(IMAGE_LABELS.message.masked)![0];

describe("landing image showcase (labels render, LAB-1484)", () => {
  it("covers every masked region, prints placeholders on the text covers, and restores the answer", () => {
    const { container } = render(<ImageShowcase />);
    // The model's image (the enlarged inset after it repeats the same covers).
    const figure = container.querySelector('img[alt^="The same card"]')!.parentElement!;
    const covers = figure.querySelectorAll("[data-cover]");
    expect(covers).toHaveLength(IMAGE_LABELS.image.regions.filter((r) => r.policy === "mask").length);
    const text = [...figure.querySelectorAll('[data-cover="text"]')].map((c) => c.getAttribute("data-label"));
    expect(text.length).toBeGreaterThan(0);
    expect(text.every((t) => /^\[\[[A-Z_]+_[0-9a-f]+\]\]$/.test(t ?? ""))).toBe(true);
    // The photo label is printed once, not again on the face inside it.
    expect([...figure.querySelectorAll('[data-cover="visual"]')].filter((c) => c.getAttribute("data-label")).length).toBe(1);
    const restored = screen.getByTestId("restored-text");
    const mark = restored.querySelector(`mark[data-restored="${holder}"]`);
    expect(mark?.firstChild?.textContent).toBe("Fiktív Mária");
    expect(restored.textContent?.replace(/\(Person, restored from [^)]+\)/, "")).not.toContain("[[");
    expect(screen.getAllByText((_, el) => el?.getAttribute("data-placeholder") === holder).length).toBeGreaterThan(2);
  });

});
