import { useState } from "react";
import { getOwnerToken, setOwnerToken, useOwnerRevision } from "../api/localOwner";

export default function OwnerAccess() {
  useOwnerRevision();
  const configured = Boolean(getOwnerToken());
  const [token, setToken] = useState("");
  return <details className="pw-panel pw-stack"><summary>Local guard access{configured ? " · owner token set" : ""}</summary>
    <p>For a guard protected by PII_GUARD_API_TOKEN, enter its owner API token here. It stays in this tab’s memory and is cleared on reload. Provider credentials and endpoint keys are configured separately.</p>
    <form className="pw-inline" onSubmit={(e) => { e.preventDefault(); const value = token; setToken(""); setOwnerToken(value); }}>
      <label>Owner API token<input type="password" autoComplete="off" required value={token} onChange={(e) => setToken(e.target.value)} /></label>
      <button type="submit" disabled={!token.trim()}>Use owner token</button>
      {configured && <button type="button" onClick={() => { setToken(""); setOwnerToken(null); }}>Clear owner token</button>}
    </form>
    {configured && <p role="status">Owner token set for same-origin local guard requests.</p>}
  </details>;
}
