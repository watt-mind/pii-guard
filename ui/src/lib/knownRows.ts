import type { TextEntityType } from "../api/types";

/** One row of the Known values panel. */
export interface KnownRow {
  id: number;
  value: string;
  entity_type: TextEntityType;
}

let nextId = 1;
export const newKnownRow = (value = "", entity_type: TextEntityType = "PERSON"): KnownRow => ({ id: nextId++, value, entity_type });
