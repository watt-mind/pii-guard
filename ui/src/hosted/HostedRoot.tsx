import { lazy, Suspense } from "react";
import { HostedApp } from "./HostedApp";

// The console is only for a signed-in owner: the public landing doesn't download it (LAB-1450).
const SignedInConsole = lazy(() => import("../App").then((m) => ({ default: m.SignedInConsole })));
// A guest's Playground (LAB-1812) shares the console's screens: loaded only when a guest opens it.
const GuestPlayground = lazy(() => import("./GuestPlayground"));

/** The hosted build's entry: the public page, with the console loaded on demand. */
export function HostedRoot() {
  return (
    <HostedApp
      console={(session) => (
        <Suspense fallback={<p role="status" className="p-6 text-sm text-muted">Opening your console…</p>}>
          <SignedInConsole session={session} />
        </Suspense>
      )}
      guest={(session) => (
        <Suspense fallback={<p role="status" className="p-6 text-sm text-muted">Opening the playground…</p>}>
          <GuestPlayground session={session} />
        </Suspense>
      )}
    />
  );
}
