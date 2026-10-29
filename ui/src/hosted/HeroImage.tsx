import { IMAGE_RECORDINGS } from "../api/imageMock";
import { DEFAULT_IMAGE_SAMPLE } from "../content/imageSamples";
import { MASK_PADDING, percentBox } from "../lib/imageRegions";

/*
 * The hero's image strip (LAB-1478): the same fictional specimen and recorded regions as the
 * image showcase, small, before and after. Loaded on demand with the showcase's chunk. Decorative:
 * the hero's figure caption says what it shows.
 */

const sample = DEFAULT_IMAGE_SAMPLE;
const recording = IMAGE_RECORDINGS.samples[sample.id]!;
const KEPT_ON_HOSTED = new Set(["SIGNATURE", "STAMP"]);
const masked = recording.regions.filter((r) => r.policy === "mask" && !KEPT_ON_HOSTED.has(r.entity_type));

function Thumb({ mask }: { mask: boolean }) {
  return <div className="relative min-w-0 flex-1 overflow-hidden rounded-md ring-1 ring-line">
    <img src={sample.src} alt="" width={recording.width} height={recording.height} loading="lazy" decoding="async" className="block h-auto w-full" />
    {mask && masked.map((r, i) => <span key={i} className="absolute" style={{ ...percentBox(r.box, recording.width, recording.height, MASK_PADDING), backgroundColor: "var(--image-mask-fill, #000)" }} />)}
  </div>;
}

export default function HeroImage() {
  return <div className="flex items-center gap-3"><Thumb mask={false} /><span className="font-mono text-2xs text-guard">→</span><Thumb mask /></div>;
}
