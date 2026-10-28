import { useEffect, useSyncExternalStore } from "react";
import { ButtonLink } from "../components/ui";
import type { Account, Requester } from "./api";
import { SETUP_STEPS, getLastRead, loadSetup, publish, subscribe, type SetupState } from "./setup";

/** One ordered setup list with ticks and one primary action: the next step not yet done. */
export function SetupChecklist({ call, account, active, calls }: { call: Requester; account: Account; active: boolean; calls: number }) {
  const state = useSyncExternalStore(subscribe, getLastRead, () => null);
  useEffect(() => {
    if (!active) return;
    let live = true;
    loadSetup(call, account).then(
      (s) => live && publish(s),
      // Keep the last good read on a failed refresh; the first failure shows nothing.
      () => live && publish(getLastRead()),
    );
    return () => {
      live = false;
    };
  }, [call, account, active]);
  if (!state) return null;
  const done: SetupState = { ...state, call: state.call || calls > 0 };
  const next = SETUP_STEPS.find((s) => !done[s.id]);
  if (!next) return null;
  const count = SETUP_STEPS.filter((s) => done[s.id]).length;
  return (
    <section aria-labelledby="setup-title" className="mt-5 border-t border-line pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="setup-title" className="text-lg font-normal text-ink">
          Set up your gateway
        </h3>
        <span className="text-xs text-muted tabular-nums">
          {count} of {SETUP_STEPS.length} done
        </span>
      </div>
      <ol className="mt-3 space-y-2.5">
        {SETUP_STEPS.map((s, i) => {
          const ok = done[s.id];
          const current = s.id === next.id;
          return (
            <li key={s.id} className="flex items-start gap-3" aria-current={current ? "step" : undefined}>
              <span
                aria-hidden="true"
                className={[
                  "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border text-2xs tabular-nums",
                  ok ? "border-guard bg-guard-soft text-guard-ink" : current ? "border-ink text-ink" : "border-line-strong text-muted",
                ].join(" ")}
              >
                {ok ? (
                  <svg viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m3.5 8.5 3 3 6-7" />
                  </svg>
                ) : (
                  i + 1
                )}
              </span>
              <div className="min-w-0">
                <p className={["text-sm", ok ? "text-muted" : "font-medium text-ink"].join(" ")}>
                  {s.title}
                  <span className="sr-only">{ok ? " (done)" : current ? " (next)" : ""}</span>
                </p>
                {!ok && <p className="text-xs text-muted">{s.hint}</p>}
              </div>
            </li>
          );
        })}
      </ol>
      <ButtonLink variant="primary" href={next.href} className="mt-4">
        {next.cta} <span aria-hidden="true">→</span>
      </ButtonLink>
    </section>
  );
}
