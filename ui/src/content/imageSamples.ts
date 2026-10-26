// Fictional sample images for the Images screen (ADR 0005). Drawn with Pillow by
// ui/scripts/render_samples.py: the faces are ellipses, the signatures are pen
// scribbles, every name and number is made up (the IDs pass their checksums but
// belong to no one). The demo engine replays regions recorded for exactly these files.

export interface ImageSample {
  id: string;
  title: string;
  subtitle: string;
  src: string;
  alt: string;
}

export const IMAGE_SAMPLES: ImageSample[] = [
  {
    id: "id-card",
    title: "ID card",
    subtitle: "Face, signature, TAJ and tax ID",
    src: "/samples/id-card.png",
    alt: "Fictional ID card: a drawn face, the name Minta Mária, a birth date, a TAJ number, a tax ID and a signature scribble.",
  },
  {
    id: "signed-letter",
    title: "Signed letter",
    subtitle: "Signature, company stamp, email, phone",
    src: "/samples/signed-letter.png",
    alt: "Fictional Hungarian letter from a company to Kovács Bence, with an email address, a phone number, a tax ID, a signature scribble and a round company stamp.",
  },
  {
    id: "visitor-badge",
    title: "Visitor badge",
    subtitle: "Face, name, email, phone",
    src: "/samples/visitor-badge.png",
    alt: "Fictional visitor badge: a drawn face, the name Jane Placeholder, an email address and a UK phone number.",
  },
];

export const DEFAULT_IMAGE_SAMPLE = IMAGE_SAMPLES[0]!;

/** Same limit as the API's default (`DEFAULT_MAX_IMAGE_BYTES`). */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const UPLOAD_TYPES = ["image/png", "image/jpeg"] as const;
