import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { HttpGuardClient } from "../api/http";
import { ApiError, UnreachableError } from "../api/http";
import { IMAGE_RECORDINGS } from "../api/imageMock";
import { createMockClient } from "../api/mock";
import type { ImageMaskResponse } from "../api/types";

const loadImage = vi.fn(async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }));

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down, maskImage: down };
}

function liveApi(maskImage: HttpGuardClient["maskImage"]): HttpGuardClient {
  const backend = createMockClient();
  return {
    health: () => Promise.resolve({ status: "ok", version: "0.1.0" }),
    analyze: backend.analyze,
    mask: backend.mask,
    unmask: backend.unmask,
    maskImage,
  };
}

function recorded(id: string, overrides: Partial<ImageMaskResponse> = {}): ImageMaskResponse {
  return { ...structuredClone(IMAGE_RECORDINGS.samples[id]!), image: "iVBORw0KGgo=", ...overrides };
}

async function openImages(api: HttpGuardClient) {
  const user = userEvent.setup();
  render(<App api={api} mock={createMockClient()} loadImage={loadImage} />);
  await user.click(screen.getByRole("tab", { name: /images/i }));
  return { user, panel: screen.getByRole("tabpanel", { name: /images/i }) };
}

beforeEach(() => {
  localStorage.clear();
  loadImage.mockClear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
  URL.createObjectURL ??= vi.fn(() => "blob:fake");
  URL.revokeObjectURL ??= vi.fn();
});

describe("Images screen", () => {
  it("is the third tab and reachable with the arrow keys", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} loadImage={loadImage} />);
    await user.click(screen.getByRole("tab", { name: /chat/i }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /images/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: /images/i })).toBeVisible();
  });

  it("in demo mode replays recorded regions for a sample and draws the masking in the browser", async () => {
    const { user, panel } = await openImages(offlineApi());
    // One click: picking a sample masks it.
    await user.click(within(panel).getByRole("button", { name: /signed letter/i }));

    expect(await within(panel).findByTestId("demo-masked-image")).toBeInTheDocument();
    const rec = IMAGE_RECORDINGS.samples["signed-letter"]!;
    const masked = rec.regions.filter((r) => r.policy === "mask").length;
    expect(within(panel).getAllByTestId("demo-mask")).toHaveLength(masked);
    expect(within(panel).getAllByTestId("region-box")).toHaveLength(rec.regions.length);
    expect(within(panel).getByRole("button", { name: "Stamp, found by SAM 3.1, kept by policy" })).toBeInTheDocument();
    expect(within(panel).getByTestId("image-scope-note")).toHaveTextContent(/Recorded .* Nothing was sent anywhere/);
    expect(within(panel).getByText(/black boxes are drawn in your browser/)).toBeInTheDocument();
    expect(within(panel).getByRole("table")).toHaveTextContent("Signature");
    // Labels follow what ran: the recorded run used the Muse Spark LLM detector.
    expect(within(panel).getByRole("table")).toHaveTextContent("OCR + Muse Spark 1.3 (Meta API)");
    expect(within(panel).getByRole("table")).toHaveTextContent(/OCR \+ Rules(?! \+)/);
  });

  it("marks the upload tile as needing the live API in demo mode", async () => {
    const { panel } = await openImages(offlineApi());
    await waitFor(() => expect(within(panel).getByText("Needs the live API: SAM runs on the server.")).toBeInTheDocument());
  });

  it("tells a user who chose the demo engine with the API up to switch to Live API", async () => {
    localStorage.setItem("pii-guard:mode", "mock");
    const { user, panel } = await openImages(liveApi(vi.fn()));
    await screen.findByText("API v0.1.0");
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    expect(within(panel).getByText("Nothing has been sent yet")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/switch Engine in the header to Live API/);
  });

  it("says an undecodable image could not be decoded", async () => {
    const maskImage = vi.fn().mockRejectedValue(new ApiError(422, "invalid_image", "image could not be decoded"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("Live");
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("This image couldn't be decoded.");
  });

  it("refuses an upload in demo mode and says nothing was sent", async () => {
    const { user, panel } = await openImages(offlineApi());
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    expect(within(panel).getByText("mine.png")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("Uploads need the live API.");
    expect(alert).toHaveTextContent("was not sent anywhere");
  });

  it("rejects unsupported uploads before anything runs", async () => {
    const { panel } = await openImages(offlineApi());
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(input, new File(["GIF89a"], "anim.gif", { type: "image/gif" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Only PNG and JPEG");
  });

  it("shows the API's masked PNG, the regions and what ran", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card"));
    const { user, panel } = await openImages(liveApi(maskImage));
    expect(await screen.findByText("Live")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));

    const figure = await within(panel).findByTestId("masked-image");
    expect(figure.querySelector("img")!.getAttribute("src")).toBe("data:image/png;base64,iVBORw0KGgo=");
    expect(maskImage).toHaveBeenCalledWith(expect.objectContaining({ sampleId: "id-card", language: "hu" }));
    expect(loadImage).toHaveBeenCalledWith("/samples/id-card.png");
    const note = within(panel).getByTestId("image-scope-note");
    expect(note).toHaveTextContent("SAM 3.1 looked for faces, signatures, ID photos and stamps");
    expect(note).not.toHaveTextContent("Not covered"); // rules + llm ran: nothing to flag
    expect(within(panel).getByText(/exactly as the API returned it/)).toBeInTheDocument();

    // Hover a region box: the matching legend type lights up; the toggle hides the boxes.
    const face = within(panel).getByRole("button", { name: "Face, found by SAM 3.1, masked" });
    await user.hover(face);
    expect(face).toHaveAttribute("aria-pressed", "true");
    await user.click(within(panel).getByRole("checkbox", { name: "Show regions" }));
    expect(within(panel).queryAllByTestId("region-box")).toHaveLength(0);
  });

  it("says when OCR did not run", async () => {
    const data = recorded("visitor-badge", {
      regions: recorded("visitor-badge").regions.filter((r) => r.source === "sam"),
      analysis: { sam: { model: "sam-3.1", entity_types: ["FACE"] }, ocr: { ran: false, engine: null, detectors: [], reason: "tesseract_unavailable" } },
    });
    const { user, panel } = await openImages(liveApi(vi.fn().mockResolvedValue(data)));
    await screen.findByText("Live");
    await user.click(within(panel).getByRole("button", { name: /visitor badge/i }));
    expect(await within(panel).findByText(/Text in this image was not checked/)).toBeInTheDocument();
  });

  it("fails closed: a 503 shows the blocked notice and no masked image", async () => {
    const maskImage = vi.fn().mockRejectedValue(new ApiError(503, "detection_failed", "SAM request failed: HTTP 500"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("Live");
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("Blocked. Nothing was sent to the model.");
    expect(alert).toHaveTextContent("detection_failed");
    expect(within(panel).queryByTestId("masked-image")).toBeNull();
  });

  it("drops the result when an upload replaces the sample, and waits for a click", async () => {
    const maskImage = vi.fn().mockResolvedValue(recorded("id-card"));
    const { user, panel } = await openImages(liveApi(maskImage));
    await screen.findByText("Live");
    await user.click(within(panel).getByRole("button", { name: "Mask image" }));
    await within(panel).findByTestId("masked-image");
    const input = panel.querySelector<HTMLInputElement>("#image-upload")!;
    await user.upload(input, new File([new Uint8Array([0x89, 0x50])], "mine.png", { type: "image/png" }));
    await waitFor(() => expect(within(panel).queryByTestId("masked-image")).toBeNull());
    expect(within(panel).getByText("Nothing has been sent yet")).toBeInTheDocument();
    expect(maskImage).toHaveBeenCalledTimes(1);
  });
});
