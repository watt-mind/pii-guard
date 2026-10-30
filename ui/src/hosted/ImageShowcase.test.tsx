import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { IMAGE_LABELS, IMAGE_LABELS_EN, SHOWCASE, type ImageLabelsRecording } from "../content/imageLabels";
import { zoomBox } from "../lib/imageRegions";
import ImageShowcase from "./ImageShowcase";

const holderOf = (r: ImageLabelsRecording) => /\[\[PERSON_[0-9a-f]+\]\]/.exec(r.message.masked)![0];

function expectMasked(container: HTMLElement, recording: ImageLabelsRecording, name: string) {
  const holder = holderOf(recording);
  // The model's image (the enlarged inset after it repeats the same covers).
  const figure = container.querySelector('img[alt^="The same card"]')!.parentElement!;
  const covers = figure.querySelectorAll("[data-cover]");
  expect(covers).toHaveLength(recording.image.regions.filter((r) => r.policy === "mask").length);
  const text = [...figure.querySelectorAll('[data-cover="text"]')].map((c) => c.getAttribute("data-label"));
  expect(text.length).toBeGreaterThan(0);
  expect(text.every((t) => /^\[\[[A-Z_]+_[0-9a-f]+\]\]$/.test(t ?? ""))).toBe(true);
  // The photo label is printed once, not again on the face inside it.
  expect([...figure.querySelectorAll('[data-cover="visual"]')].filter((c) => c.getAttribute("data-label")).length).toBe(1);
  const restored = screen.getByTestId("restored-text");
  const mark = restored.querySelector(`mark[data-restored="${holder}"]`);
  expect(mark?.firstChild?.textContent).toBe(name);
  expect(restored.textContent?.replace(/\(Person, restored from [^)]+\)/, "")).not.toContain("[[");
  expect(screen.getAllByText((_, el) => el?.getAttribute("data-placeholder") === holder).length).toBeGreaterThan(2);
}

describe("landing image showcase (labels render, LAB-1484; English specimen, LAB-1509)", () => {
  it("opens on the English specimen: face blocked, ID fields tokenized, the answer restored", () => {
    const { container } = render(<ImageShowcase />);
    expect(screen.getByRole("radio", { name: "English ID card" })).toBeChecked();
    expect(container.querySelector("img")).toHaveAttribute("src", "/samples/id-card-en.png");
    const types = new Set(IMAGE_LABELS_EN.image.regions.filter((r) => r.policy === "mask").map((r) => r.entity_type));
    expect([...types]).toEqual(expect.arrayContaining(["FACE", "ID_PHOTO", "PERSON", "DATE_OF_BIRTH", "ID_DOCUMENT"]));
    expectMasked(container, IMAGE_LABELS_EN, "Jane Placeholder");
  });

  it("the answer is a recorded Muse Spark run, labeled as one (LAB-1524)", () => {
    for (const rec of [IMAGE_LABELS_EN, IMAGE_LABELS]) {
      expect(rec.answer.model).toMatch(/^muse-spark/);
      expect(rec.answer.by).not.toMatch(/stand-in/);
    }
    render(<ImageShowcase />);
    expect(screen.getByText(/Muse Spark’s recorded answer/)).toBeInTheDocument();
  });

  it("switches to the Hungarian specimen, unchanged", async () => {
    const { container } = render(<ImageShowcase />);
    await userEvent.click(screen.getByRole("radio", { name: "Hungarian ID card" }));
    expect(container.querySelector("img")).toHaveAttribute("src", "/samples/id-card.png");
    expectMasked(container, IMAGE_LABELS, "Fiktív Mária");
  });

  it("shows no stray photo label in the enlarged crop (L2 carryover 2)", async () => {
    const { container } = render(<ImageShowcase />);
    for (const name of ["English ID card", "Hungarian ID card"]) {
      await userEvent.click(screen.getByRole("radio", { name }));
      const zoom = [...container.querySelectorAll("figure")].find((f) => f.textContent?.includes("as the model reads them"))!;
      expect(zoom.querySelectorAll("[data-cover]").length).toBeGreaterThan(0);
      expect(zoom.textContent).not.toMatch(/PHOTO/);
    }
  });

  it("starts the enlarged crop right of a photo cover that ends before the text", () => {
    for (const { recording } of SHOWCASE) {
      const { image } = recording;
      const [x1] = zoomBox(image.regions, image.width, image.height)!;
      for (const r of image.regions.filter((r) => r.source !== "ocr" && r.cover_box)) {
        const textLeft = Math.min(...image.regions.filter((t) => t.source === "ocr" && t.cover_box).map((t) => t.cover_box![0]));
        if (r.cover_box![2] < textLeft) expect(x1).toBeGreaterThan(r.cover_box![2]);
      }
    }
  });
});
