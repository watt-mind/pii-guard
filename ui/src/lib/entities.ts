import type { EntityType } from "../api/types";

export type Policy = "mask" | "keep" | "block";

export interface EntityMeta {
  label: string;
  /** Short code shown inside chips so type never relies on colour alone. */
  short: string;
  policy: Policy;
  /** Tailwind classes. Written out in full so the compiler can see them. */
  mark: string;
  chip: string;
  swatch: string;
}

// docs/entities.md, default policies.
export const ENTITY_META: Record<EntityType, EntityMeta> = {
  PERSON: {
    label: "Person",
    short: "PER",
    policy: "mask",
    mark: "bg-violet-200/70 text-violet-950 ring-violet-500/50 dark:bg-violet-500/25 dark:text-violet-100 dark:ring-violet-400/50",
    chip: "bg-violet-100 text-violet-900 ring-violet-400/60 dark:bg-violet-500/20 dark:text-violet-100 dark:ring-violet-400/50",
    swatch: "bg-violet-500",
  },
  ADDRESS: {
    label: "Address",
    short: "ADR",
    policy: "mask",
    mark: "bg-amber-200/80 text-amber-950 ring-amber-500/50 dark:bg-amber-400/20 dark:text-amber-100 dark:ring-amber-300/50",
    chip: "bg-amber-100 text-amber-900 ring-amber-400/70 dark:bg-amber-400/15 dark:text-amber-100 dark:ring-amber-300/50",
    swatch: "bg-amber-500",
  },
  EMAIL: {
    label: "Email",
    short: "EML",
    policy: "mask",
    mark: "bg-sky-200/80 text-sky-950 ring-sky-500/50 dark:bg-sky-400/20 dark:text-sky-100 dark:ring-sky-300/50",
    chip: "bg-sky-100 text-sky-900 ring-sky-400/70 dark:bg-sky-400/15 dark:text-sky-100 dark:ring-sky-300/50",
    swatch: "bg-sky-500",
  },
  PHONE: {
    label: "Phone",
    short: "TEL",
    policy: "mask",
    mark: "bg-teal-200/80 text-teal-950 ring-teal-500/50 dark:bg-teal-400/20 dark:text-teal-100 dark:ring-teal-300/50",
    chip: "bg-teal-100 text-teal-900 ring-teal-400/70 dark:bg-teal-400/15 dark:text-teal-100 dark:ring-teal-300/50",
    swatch: "bg-teal-500",
  },
  DATE_OF_BIRTH: {
    label: "Date of birth",
    short: "DOB",
    policy: "mask",
    mark: "bg-rose-200/80 text-rose-950 ring-rose-500/50 dark:bg-rose-400/20 dark:text-rose-100 dark:ring-rose-300/50",
    chip: "bg-rose-100 text-rose-900 ring-rose-400/70 dark:bg-rose-400/15 dark:text-rose-100 dark:ring-rose-300/50",
    swatch: "bg-rose-500",
  },
  NATIONAL_ID_HU_TAX: {
    label: "Tax ID (HU)",
    short: "TAX",
    policy: "mask",
    mark: "bg-indigo-200/80 text-indigo-950 ring-indigo-500/50 dark:bg-indigo-400/20 dark:text-indigo-100 dark:ring-indigo-300/50",
    chip: "bg-indigo-100 text-indigo-900 ring-indigo-400/70 dark:bg-indigo-400/15 dark:text-indigo-100 dark:ring-indigo-300/50",
    swatch: "bg-indigo-500",
  },
  NATIONAL_ID_HU_TAJ: {
    label: "TAJ number (HU)",
    short: "TAJ",
    policy: "mask",
    mark: "bg-fuchsia-200/80 text-fuchsia-950 ring-fuchsia-500/50 dark:bg-fuchsia-400/20 dark:text-fuchsia-100 dark:ring-fuchsia-300/50",
    chip: "bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-400/70 dark:bg-fuchsia-400/15 dark:text-fuchsia-100 dark:ring-fuchsia-300/50",
    swatch: "bg-fuchsia-500",
  },
  ID_DOCUMENT: {
    label: "ID document",
    short: "IDD",
    policy: "mask",
    mark: "bg-orange-200/80 text-orange-950 ring-orange-500/50 dark:bg-orange-400/20 dark:text-orange-100 dark:ring-orange-300/50",
    chip: "bg-orange-100 text-orange-900 ring-orange-400/70 dark:bg-orange-400/15 dark:text-orange-100 dark:ring-orange-300/50",
    swatch: "bg-orange-500",
  },
  BANK_ACCOUNT: {
    label: "Bank account",
    short: "IBN",
    policy: "mask",
    mark: "bg-emerald-200/80 text-emerald-950 ring-emerald-500/50 dark:bg-emerald-400/20 dark:text-emerald-100 dark:ring-emerald-300/50",
    chip: "bg-emerald-100 text-emerald-900 ring-emerald-400/70 dark:bg-emerald-400/15 dark:text-emerald-100 dark:ring-emerald-300/50",
    swatch: "bg-emerald-500",
  },
  COMPANY_ID_HU: {
    label: "Company ID (HU)",
    short: "CÉG",
    policy: "keep",
    mark: "bg-slate-200/70 text-slate-900 ring-slate-400/60 dark:bg-slate-400/15 dark:text-slate-100 dark:ring-slate-400/40",
    chip: "bg-slate-100 text-slate-800 ring-slate-300 dark:bg-slate-400/15 dark:text-slate-100 dark:ring-slate-400/40",
    swatch: "bg-slate-400",
  },
  ORGANIZATION: {
    label: "Organization",
    short: "ORG",
    policy: "keep",
    mark: "bg-stone-200/70 text-stone-900 ring-stone-400/60 dark:bg-stone-400/15 dark:text-stone-100 dark:ring-stone-400/40",
    chip: "bg-stone-100 text-stone-800 ring-stone-300 dark:bg-stone-400/15 dark:text-stone-100 dark:ring-stone-400/40",
    swatch: "bg-stone-400",
  },
  PARCEL_NUMBER_HU: {
    label: "Parcel number (HU)",
    short: "HRS",
    policy: "mask",
    mark: "bg-lime-200/80 text-lime-950 ring-lime-600/50 dark:bg-lime-400/20 dark:text-lime-100 dark:ring-lime-300/50",
    chip: "bg-lime-100 text-lime-900 ring-lime-500/70 dark:bg-lime-400/15 dark:text-lime-100 dark:ring-lime-300/50",
    swatch: "bg-lime-500",
  },
  VEHICLE_PLATE: {
    label: "Vehicle plate",
    short: "RSZ",
    policy: "mask",
    mark: "bg-cyan-200/80 text-cyan-950 ring-cyan-500/50 dark:bg-cyan-400/20 dark:text-cyan-100 dark:ring-cyan-300/50",
    chip: "bg-cyan-100 text-cyan-900 ring-cyan-400/70 dark:bg-cyan-400/15 dark:text-cyan-100 dark:ring-cyan-300/50",
    swatch: "bg-cyan-500",
  },
  FACE: {
    label: "Face",
    short: "FCE",
    policy: "mask",
    mark: "bg-pink-200/80 text-pink-950 ring-pink-500/50 dark:bg-pink-400/20 dark:text-pink-100 dark:ring-pink-300/50",
    chip: "bg-pink-100 text-pink-900 ring-pink-400/70 dark:bg-pink-400/15 dark:text-pink-100 dark:ring-pink-300/50",
    swatch: "bg-pink-500",
  },
  SIGNATURE: {
    label: "Signature",
    short: "SIG",
    policy: "mask",
    mark: "bg-purple-200/80 text-purple-950 ring-purple-500/50 dark:bg-purple-400/20 dark:text-purple-100 dark:ring-purple-300/50",
    chip: "bg-purple-100 text-purple-900 ring-purple-400/70 dark:bg-purple-400/15 dark:text-purple-100 dark:ring-purple-300/50",
    swatch: "bg-purple-500",
  },
  ID_PHOTO: {
    label: "ID photo",
    short: "PHO",
    policy: "mask",
    mark: "bg-red-200/80 text-red-950 ring-red-500/50 dark:bg-red-400/20 dark:text-red-100 dark:ring-red-300/50",
    chip: "bg-red-100 text-red-900 ring-red-400/70 dark:bg-red-400/15 dark:text-red-100 dark:ring-red-300/50",
    swatch: "bg-red-500",
  },
  STAMP: {
    label: "Stamp",
    short: "STM",
    policy: "keep",
    mark: "bg-zinc-200/70 text-zinc-900 ring-zinc-400/60 dark:bg-zinc-400/15 dark:text-zinc-100 dark:ring-zinc-400/40",
    chip: "bg-zinc-100 text-zinc-800 ring-zinc-300 dark:bg-zinc-400/15 dark:text-zinc-100 dark:ring-zinc-400/40",
    swatch: "bg-zinc-400",
  },
};

export const UNKNOWN_META: EntityMeta = {
  label: "Unknown type",
  short: "???",
  policy: "mask",
  mark: "bg-zinc-200 text-zinc-900 ring-zinc-400 dark:bg-zinc-700 dark:text-zinc-100 dark:ring-zinc-500",
  chip: "bg-zinc-100 text-zinc-800 ring-zinc-400 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-500",
  swatch: "bg-zinc-500",
};

export function metaFor(type: EntityType | null | undefined): EntityMeta {
  return type ? ENTITY_META[type] : UNKNOWN_META;
}

/** Rule detections of these types are validated by a checksum; other rule hits are patterns. */
export const CHECKSUM_TYPES: ReadonlySet<EntityType> = new Set<EntityType>([
  "NATIONAL_ID_HU_TAX",
  "NATIONAL_ID_HU_TAJ",
  "BANK_ACCOUNT",
  "COMPANY_ID_HU",
]);

const TEXT_TYPES = Object.keys(ENTITY_META).filter((t) => !["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"].includes(t)) as EntityType[];

/**
 * Which text types each built-in detector looks for (src/pii_guard/detect). `partly`: only some
 * forms (rules find postcodes and street patterns, not every address).
 */
export const DETECTOR_TYPES: Record<string, { types: readonly EntityType[]; partly?: readonly EntityType[] }> = {
  rules: {
    types: ["EMAIL", "PHONE", "NATIONAL_ID_HU_TAX", "NATIONAL_ID_HU_TAJ", "BANK_ACCOUNT", "COMPANY_ID_HU", "ID_DOCUMENT", "VEHICLE_PLATE"],
    partly: ["ADDRESS"],
  },
  ner: { types: ["PERSON", "ORGANIZATION", "ADDRESS"] },
  llm: { types: TEXT_TYPES },
};

const KNOWN_MODELS: { prefix: string; label: (version: string) => string }[] = [
  { prefix: "muse-spark-open", label: () => "Muse Spark Open" },
  { prefix: "muse-spark-", label: (v) => `Muse Spark ${v} (Meta API)` },
];

/** A model id as a person reads it: "muse-spark-1.3" -> "Muse Spark 1.3 (Meta API)". */
export function modelLabel(model: string): string {
  const id = model.split("/").pop() ?? model;
  for (const known of KNOWN_MODELS) if (id.startsWith(known.prefix)) return known.label(id.slice(known.prefix.length));
  return id;
}

export interface DetectorLabelOptions {
  /** The types this detector found here: rules get "+ checksum" only for checksum-validated types. */
  types?: Iterable<EntityType>;
  /** The model behind a model-backed detector, when the API reports it. */
  model?: string;
}

/** Label a detector by what actually ran, never by what it might be. */
export function detectorLabel(detector: string, options: DetectorLabelOptions = {}): string {
  if (detector === "rules") {
    const types = [...(options.types ?? [])];
    return types.some((t) => CHECKSUM_TYPES.has(t)) ? "Rules + checksum" : "Rules";
  }
  if (detector === "llm") return options.model ? modelLabel(options.model) : "LLM detector";
  if (detector === "ner") return "Multilingual NER";
  if (detector === "known") return "Known value (pre-loaded)";
  return detector;
}
