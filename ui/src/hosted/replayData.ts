import recording from "../content/agentReplayRecording.json";
import { alignLoose } from "../lib/placeholders";

/* The agent-turn replay's data helpers (LAB-1499); the card is AgentReplay.tsx. */

/** The fictional CRM record the agent's read_file returns. Keep in step with RECORD in the script. */
export const RECORD = '{"customer": "Robin Example", "email": "robin.example@example.com", "iban": "DE89 3704 0044 0532 0130 00"}';

/** Placeholder → fictional value, from the masked record the model saw and the record itself. */
export function replayValues(): Map<string, string> {
  const values = new Map<string, string>();
  for (const s of alignLoose(recording.masked_record, RECORD) ?? []) if (s.kind === "restored") values.set(s.placeholder, s.text);
  return values;
}

/**
 * What the agent has received once the model has streamed `upstream[0..k)`: the longest run of
 * the recorded agent chunks that the gateway could release, and the tail it is holding back
 * because a placeholder may still be open.
 */
export function streamAt(upstream: readonly string[], agent: readonly string[], k: number): { model: string; agent: string; held: string } {
  const model = upstream.slice(0, k).join("");
  let released = "";
  for (const piece of agent) {
    if (!model.startsWith(released + piece)) break;
    released += piece;
  }
  // A chunk the gateway released early is still bounded by what the model has sent.
  return { model, agent: released, held: model.slice(released.length) };
}

