import { useState } from "react";
import { getOwnerToken, setOwnerToken, useOwnerRevision } from "../api/localOwner";
import { Button, Field, Input, Notice } from "../components/ui";

export default function OwnerAccess() {
  useOwnerRevision();
  const configured = Boolean(getOwnerToken());
  const [token, setToken] = useState("");
  return (
    <details className="group rounded-xl border border-line bg-surface">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 sm:p-5 [&::-webkit-details-marker]:hidden">
        <span className="text-lg font-normal text-ink">
          Local guard access{configured && <span className="text-sm text-muted"> · owner token set</span>}
        </span>
        <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </summary>
      <div className="space-y-4 border-t border-line p-4 sm:p-5">
        <p className="text-sm text-muted">
          For a guard protected by <code className="font-mono text-xs">PII_GUARD_API_TOKEN</code>, enter its owner API token here. It stays in this tab’s memory and is cleared on reload. Provider credentials and endpoint keys are configured separately.
        </p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); const value = token; setToken(""); setOwnerToken(value); }}>
          <Field label="Owner API token" required className="min-w-40 flex-1">
            <Input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
          </Field>
          <Button variant="primary" type="submit" disabled={!token.trim()}>Use owner token</Button>
          {configured && <Button variant="ghost" onClick={() => { setToken(""); setOwnerToken(null); }}>Clear owner token</Button>}
        </form>
        {configured && <Notice tone="success" live>Owner token set for same-origin local guard requests.</Notice>}
      </div>
    </details>
  );
}
