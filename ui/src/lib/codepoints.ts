// The API speaks in code-point offsets (Python str indices); JavaScript strings
// index UTF-16 units. They only differ for characters outside the BMP (emoji,
// some symbols), but a mismatch there would shift every highlight after it.

/** Maps code-point offset i (0..length) to the UTF-16 index where it starts. */
export function codePointIndex(text: string): number[] {
  const map: number[] = [];
  let unit = 0;
  for (const ch of text) {
    map.push(unit);
    unit += ch.length;
  }
  map.push(unit);
  return map;
}

/** Maps UTF-16 index i (0..length) to its code-point offset. */
export function utf16ToCodePoint(text: string): (index: number) => number {
  const lookup = new Map<number, number>();
  codePointIndex(text).forEach((unit, cp) => lookup.set(unit, cp));
  return (index: number) => {
    const cp = lookup.get(index);
    if (cp === undefined) throw new RangeError("index splits a surrogate pair");
    return cp;
  };
}
