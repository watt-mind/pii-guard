export type PublicPage = "home" | "demo" | "trust" | "technical";
export function publicPageOf(hash: string): PublicPage {
  if (["#demo", "#images", "#run"].includes(hash)) return "demo";
  if (["#trust", "#data", "#privacy"].includes(hash)) return "trust";
  if (["#technical", "#why", "#meta", "#europe", "#for"].includes(hash)) return "technical";
  return "home";
}
