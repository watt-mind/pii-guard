import { IMAGE_LABELS_EN } from "../content/imageLabels";
import { ButtonLink } from "../components/ui";
import { LabelledCovers } from "./LabelledCovers";

const { image } = IMAGE_LABELS_EN;

/** A compact view of the annotated synthetic sample, using the full demo's annotated cover geometry. */
export function ImageMaskingPreview() {
  return <section id="image-preview" aria-labelledby="image-preview-heading" className="grid items-center gap-6 rounded-xl border border-line bg-surface p-4 sm:p-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-8">
    <div className="min-w-0 space-y-4">
      <p className="font-mono text-xs text-accent-ink">Image masking</p>
      <h2 id="image-preview-heading" tabIndex={-1} className="text-2xl font-medium text-ink focus:outline-none sm:text-3xl">Personal data hides in images, too.</h2>
      <p className="text-sm text-muted">Mask personal details in scans and screenshots, with consistent placeholders across text and images.</p>
      <ButtonLink href="#images">See image masking <span aria-hidden="true">→</span></ButtonLink>
    </div>
    <div className="min-w-0 space-y-3">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {[false, true].map((masked) => <figure key={String(masked)} className="min-w-0 space-y-2">
          <figcaption className="text-xs font-medium text-ink">{masked ? "After · personal details covered" : "Before · fictional specimen"}</figcaption>
          <div className="@container relative mx-auto w-full max-w-[20rem] overflow-hidden rounded-md border border-line bg-surface-2">
            <img src="/samples/id-card-en.png" width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full" alt={masked ? "Annotated masking illustration of the same fictional ID card: portrait, signature and personal text covered." : "AI-generated English specimen ID card with a fictional portrait and invented personal details, marked SPECIMEN."} />
            {masked && <LabelledCovers regions={image.regions} width={image.width} height={image.height} />}
          </div>
        </figure>)}
      </div>
      <p className="text-xs text-muted">Annotated synthetic illustration: portrait and signature boxes come from fixture annotations, not detector output. Live detection can miss information. <a href="#privacy" className="underline underline-offset-4 hover:text-ink">See the limits</a>.</p>
    </div>
  </section>;
}
