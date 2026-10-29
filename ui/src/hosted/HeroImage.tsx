import { IMAGE_LABELS } from "../content/imageLabels";
import { DEFAULT_IMAGE_SAMPLE } from "../content/imageSamples";
import { LabelledCovers } from "./LabelledCovers";

/*
 * The hero's image strip (LAB-1478, labels render LAB-1484): the same fictional specimen and
 * labels recording as the image showcase, small, before and after: the photo covered, each ID
 * detail covered by its placeholder. Loaded on demand with the showcase's chunk. Decorative: the
 * hero's figure caption says what it shows.
 */

const sample = DEFAULT_IMAGE_SAMPLE;
const { image } = IMAGE_LABELS;

function Thumb({ mask }: { mask: boolean }) {
  return <div className="@container relative min-w-0 flex-1 overflow-hidden rounded-md ring-1 ring-line">
    <img src={sample.src} alt="" width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full" />
    {mask && <LabelledCovers regions={image.regions} width={image.width} height={image.height} />}
  </div>;
}

export default function HeroImage() {
  return <div className="flex items-center gap-3"><Thumb mask={false} /><span className="font-mono text-2xs text-guard">→</span><Thumb mask /></div>;
}
