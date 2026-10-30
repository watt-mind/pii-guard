import type { EntityType } from "../api/types";

export type Policy = "mask" | "keep" | "block";

/** Coarse families for charts: five fixed categorical slots instead of one hue per type. */
export type EntityGroup = "name" | "contact" | "identifier" | "image" | "organization";

/** Names must not wear masked blue (LAB-1263): blue (series-1) sits on Organizations,
which are `keep` and rarely render here, so routinely drawn groups stay off the status hues. */
export const ENTITY_GROUPS: readonly { id: EntityGroup; label: string; color: string }[] = [
  { id: "name", label: "Names", color: "var(--series-4)" },
  { id: "contact", label: "Contact", color: "var(--series-2)" },
  { id: "identifier", label: "Identifiers", color: "var(--series-3)" },
  { id: "image", label: "Image regions", color: "var(--series-5)" },
  { id: "organization", label: "Organizations", color: "var(--series-1)" },
];

interface EntityDef {
  label: string;
  /** Short code shown inside chips so type never relies on colour alone. */
  short: string;
  policy: Policy;
  group: EntityGroup;
}

export interface EntityMeta extends EntityDef {
  /**
   * Tailwind classes, from the semantic tokens in index.css. Colour says what happened to a
   * value (masked or kept), never which type it is: the type is always written out.
   */
  mark: string;
  chip: string;
  swatch: string;
}

const POLICY_CLASSES: Record<Policy, Pick<EntityMeta, "mark" | "chip" | "swatch">> = {
  mask: {
    mark: "bg-masked-soft text-ink ring-masked/45",
    chip: "bg-masked-soft text-masked ring-masked/35",
    swatch: "bg-masked",
  },
  block: {
    mark: "bg-blocked-soft text-ink ring-blocked/50",
    chip: "bg-blocked-soft text-blocked ring-blocked/40",
    swatch: "bg-blocked",
  },
  keep: {
    mark: "bg-transparent text-ink ring-kept/60",
    chip: "bg-surface-2 text-kept-ink ring-kept/50",
    swatch: "bg-kept",
  },
};

const withClasses = (d: EntityDef): EntityMeta => ({ ...d, ...POLICY_CLASSES[d.policy] });

// docs/entities.md, default policies.
const ENTITY_DEFS: Record<EntityType, EntityDef> = {
  PERSON: {
    label: "Person",
    short: "PER",
    policy: "mask",
    group: "name",
  },
  ADDRESS: {
    label: "Address",
    short: "ADR",
    policy: "mask",
    group: "contact",
  },
  EMAIL: {
    label: "Email",
    short: "EML",
    policy: "mask",
    group: "contact",
  },
  PHONE: {
    label: "Phone",
    short: "TEL",
    policy: "mask",
    group: "contact",
  },
  DATE_OF_BIRTH: {
    label: "Date of birth",
    short: "DOB",
    policy: "mask",
    group: "identifier",
  },
  NATIONAL_ID_HU_TAX: {
    label: "Tax ID (HU)",
    short: "TAX",
    policy: "mask",
    group: "identifier",
  },
  NATIONAL_ID_HU_TAJ: {
    label: "TAJ number (HU)",
    short: "TAJ",
    policy: "mask",
    group: "identifier",
  },
  ID_DOCUMENT: {
    label: "ID document",
    short: "IDD",
    policy: "mask",
    group: "identifier",
  },
  BANK_ACCOUNT: {
    // Covers IBANs and payment cards (docs/entities.md): never read as IBAN-only (LAB-1187).
    label: "Bank account / card",
    short: "BNK",
    policy: "mask",
    group: "identifier",
  },
  COMPANY_ID_HU: {
    label: "Company ID (HU)",
    short: "CÉG",
    policy: "keep",
    group: "organization",
  },
  ORGANIZATION: {
    label: "Organization",
    short: "ORG",
    policy: "keep",
    group: "organization",
  },
  PARCEL_NUMBER_HU: {
    label: "Parcel number (HU)",
    short: "HRS",
    policy: "mask",
    group: "identifier",
  },
  VEHICLE_PLATE: {
    label: "Vehicle plate",
    short: "RSZ",
    policy: "mask",
    group: "identifier",
  },
  SECRET: {
    label: "Secret",
    short: "KEY",
    policy: "mask",
    group: "identifier",
  },
  FACE: {
    label: "Face",
    short: "FCE",
    policy: "mask",
    group: "image",
  },
  SIGNATURE: {
    label: "Signature",
    short: "SIG",
    policy: "mask",
    group: "image",
  },
  ID_PHOTO: {
    label: "ID photo",
    short: "PHO",
    policy: "mask",
    group: "image",
  },
  STAMP: {
    label: "Stamp",
    short: "STM",
    policy: "keep",
    group: "image",
  },
};

export const ENTITY_META = Object.fromEntries(
  Object.entries(ENTITY_DEFS).map(([type, def]) => [type, withClasses(def)]),
) as Record<EntityType, EntityMeta>;

export const UNKNOWN_META: EntityMeta = withClasses({
  label: "Unknown type",
  short: "???",
  policy: "mask",
  group: "identifier",
});

export function groupOf(type: EntityType | null | undefined) {
  const id = metaFor(type).group;
  return ENTITY_GROUPS.find((g) => g.id === id)!;
}

/** `Span.subtype` of a SECRET span as a person reads it ("github_token" -> "GitHub token"). */
const SUBTYPE_LABEL: Record<string, string> = {
  aws_access_key_id: "AWS access key id",
  github_token: "GitHub token",
  slack_token: "Slack token",
  stripe_key: "Stripe key",
  api_key: "API key",
  google_api_key: "Google API key",
  jwt: "JWT",
  private_key: "Private key",
  url_password: "Password in a URL",
  url_user: "User name in a URL",
  bearer_token: "Bearer token",
  assignment: "Value of a secret setting",
};

export function subtypeLabel(subtype: string | null | undefined): string | null {
  if (!subtype) return null;
  return SUBTYPE_LABEL[subtype] ?? subtype.replace(/_/g, " ");
}

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

const TEXT_TYPES = Object.keys(ENTITY_DEFS).filter((t) => !["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"].includes(t)) as EntityType[];

/**
 * Which text types each built-in detector looks for (src/pii_guard/detect). `partly`: only some
 * forms (rules find postcodes and street patterns, not every address).
 */
export const DETECTOR_TYPES: Record<string, { types: readonly EntityType[]; partly?: readonly EntityType[] }> = {
  rules: {
    types: ["EMAIL", "PHONE", "NATIONAL_ID_HU_TAX", "NATIONAL_ID_HU_TAJ", "BANK_ACCOUNT", "COMPANY_ID_HU", "ID_DOCUMENT", "VEHICLE_PLATE", "SECRET"],
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
  if (detector === "demo") return "Demo rules (in browser)";
  return detector;
}
