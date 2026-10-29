/** "1 region", "3 regions": a count with its noun in the right number. */
export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
