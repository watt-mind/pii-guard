import { LABEL_FILL, LABEL_INK, labelCovers, type LabelledRegion } from "../lib/imageRegions";

/** The UI font (Geist) sets wider than the server's (Pillow's default), so labels print a little smaller to stay inside their box. */
const BROWSER_FONT_SCALE = 0.9;

/**
 * The covers of a `render: "labels"` response drawn over the image, the way the server paints
 * them (src/pii_guard/visual/render.py): a light grey box with a dark border and the session
 * placeholder printed in it at the server's size. Like the server, every box is filled first and
 * the labels go on top, so a nested box (the face inside its ID photo) never hides a label.
 * Needs an `@container` parent the width of the image (font sizes are in `cqw`). Decorative:
 * the figure's alt text says what is covered.
 */
export function LabelledCovers({ regions, width, height }: { regions: readonly LabelledRegion[]; width: number; height: number }) {
  const covers = labelCovers(regions, width, height);
  return (
    <>
      {covers.map((c, i) => (
        <span key={i} aria-hidden="true" data-cover={c.visual ? "visual" : "text"} data-label={c.lines.join(" ") || undefined} className="absolute" style={{ ...c.box, backgroundColor: LABEL_FILL, border: `1px solid ${LABEL_INK}` }} />
      ))}
      {covers.map((c, i) =>
        c.lines.length ? (
          <span
            key={`l${i}`}
            aria-hidden="true"
            className="absolute flex flex-col items-center justify-center overflow-hidden text-center font-sans leading-[1.05] whitespace-nowrap"
            style={{ ...c.box, color: LABEL_INK, fontSize: `${(c.fontCqw * BROWSER_FONT_SCALE).toFixed(3)}cqw` }}
          >
            {c.lines.map((line, j) => <span key={j}>{line}</span>)}
          </span>
        ) : null,
      )}
    </>
  );
}
