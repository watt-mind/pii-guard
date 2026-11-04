import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { PlaygroundSection } from "../App";
import { createHttpChat, type ChatClient } from "../api/chat";
import { createRoutingClient, type EngineState } from "../api/engine";
import { ApiError, createHttpClient } from "../api/http";
import { createMockClient } from "../api/mock";
import { ButtonLink, Notice } from "../components/ui";
import type { EngineHandle } from "../hooks/useEngine";
import { usePlaygroundRunner } from "../hooks/usePlaygroundRunner";
import { HOSTED_CAPABILITIES } from "../lib/capabilities";
import { hashOf, parseHash, type PlaygroundTab } from "../lib/routes";
import type { ChatDraft } from "../screens/Chat";
import type { Account } from "./api";
import { loginFor } from "./consoleLink";
import { createGuestFetch, type GuestLimit } from "./guestFetch";
import { allowanceSpent, modelName, requestsLeft, resetsIn } from "./landing";
import { PublicHeader } from "./PublicHeader";
import { HostedSessionContext, useHash, type HostedSession } from "./session";

// The Playground for a visitor who isn't signed in (LAB-1812): Text and Chat run on the hosted
// guard's shared default policy and its included model, identified by the guest cookie the server
// sets itself. Only the routes in guestFetch are called: no status, projects, traffic, models or images.

const GUEST_ENGINE: EngineState = { preference: "api", status: { state: "online", version: "" }, endpointsMissing: false };
const noop = () => undefined;

/** The live engine on the guest routes, with no health checks. Known values always start a new session (`POST /v1/sessions`). */
function useGuestEngine(doFetch: typeof fetch) {
  return useMemo(() => {
    const http = createHttpClient({ fetch: doFetch });
    // Adding to a session is a sub-route a guest isn't offered: a not-found makes the run send every row to a new one.
    const api = { ...http, addKnownValues: () => Promise.reject(new ApiError(404, "not_found", "a guest starts a new session")) };
    const mock = createMockClient();
    const client = createRoutingClient({ api, mock, getState: () => GUEST_ENGINE, onEndpointsMissing: noop, onUnreachable: noop });
    const engine: EngineHandle = { state: GUEST_ENGINE, engine: "api", client, setPreference: noop, recheck: noop };
    return { engine, mock };
  }, [doFetch]);
}

/** Chat on the included model only: the model list is the server's `included_model`, not `GET /v1/models`. */
function useGuestChat(doFetch: typeof fetch, model: string | null): ChatClient {
  return useMemo(() => ({ ...createHttpChat({ fetch: doFetch }), listModels: async () => (model ? [model] : []) }), [doFetch, model]);
}

/** Copy for each limit, and for an allowance `/v1/account` already reports as spent. */
function limitCopy(limit: GuestLimit, account: Account) {
  const reset = resetsIn(account);
  if (limit === "abuse_throttled") return { title: "Requests are coming in too fast", body: "Wait a moment, then try again. Signing in with Google gives you your own allowance." };
  if (limit === "sign_in_required") return { title: "Sign in to keep going", body: "The guard needs a Google sign-in for more requests from this network right now." };
  return { title: "Today’s free requests are used up", body: `Guests on this network share the daily allowance${reset ? `; it resets ${reset}` : ""}. Sign in with Google to keep going with your own.` };
}

/** The Playground's tab from the hash (`#playground/chat`, the old `#chat` …); Text otherwise. */
function tabOf(hash: string): PlaygroundTab {
  const route = parseHash(hash)?.route;
  return route?.section === "playground" ? route.tab : "text";
}

export default function GuestPlayground({ session }: { session: HostedSession }) {
  const { account, refresh } = session;
  const hash = useHash();
  const tab = tabOf(hash);
  const login = loginFor(account.login_url, hash);
  const [limit, setLimit] = useState<GuestLimit | null>(null);

  // `/v1/account` again shortly after the last answer, so the allowance line follows the runs.
  const [answers, setAnswers] = useState(0);
  const doFetch = useMemo(() => createGuestFetch((next) => { setLimit(next); setAnswers((n) => n + 1); }), []);
  useEffect(() => {
    if (answers === 0) return;
    const t = setTimeout(() => void refresh(), 300);
    return () => clearTimeout(t);
  }, [answers, refresh]);

  const { engine, mock } = useGuestEngine(doFetch);
  const sponsored = account.limits.sponsored_enabled !== false && Boolean(account.included_model);
  const model = sponsored ? account.included_model! : null;
  const chatClient = useGuestChat(doFetch, model);
  const playground = usePlaygroundRunner(engine);
  const [chatDraft, setChatDraft] = useState<ChatDraft | null>(null);

  // Mount each tab on its first visit, then keep its drafts, as the console does.
  const key = `playground/${tab}`;
  const [visited, setVisited] = useState(() => new Set([key]));
  if (!visited.has(key)) setVisited(new Set([...visited, key]));
  const openTab = useCallback((next: PlaygroundTab) => { globalThis.location.hash = hashOf({ section: "playground", tab: next }); }, []);

  const shown = limit ?? (allowanceSpent(account) ? "quota_exceeded" : null);
  const left = requestsLeft(account);
  const reset = resetsIn(account);

  const intro = (
    <div className="space-y-3">
      <Notice title="Guest session · shared default policy" action={<ButtonLink variant="primary" href={login}>Sign in with Google</ButtonLink>}>
        You’re trying PII Guard without an account. Text is masked with the hosted guard’s shared default policy{model ? <>, and Chat answers with {modelName(model)}</> : null}. Use fictional data only: the hosted guard receives your input in full.
        {left && <> <span className="tabular-nums">{left}</span>{reset ? `, resets ${reset}` : ""}.</>} Sign in for your own endpoint, policy, images and logs.
      </Notice>
      {shown && (() => {
        const copy = limitCopy(shown, account);
        return <Notice tone="danger" live title={copy.title} action={<ButtonLink variant="primary" href={login}>Sign in with Google</ButtonLink>}>{copy.body}</Notice>;
      })()}
    </div>
  );

  const panels = {
    images: (
      <GuestPrompt title="Sign in to mask your own images" href={loginFor(account.login_url, "#playground/images")} site={{ href: "#images", label: "See the recorded image example" }}>
        Images go to SAM 3.1 on the Meta Model API to find faces, ID photos and signatures, so uploading one needs a Google sign-in. Signed in, your project policy decides what is masked.
      </GuestPrompt>
    ),
    ...(sponsored ? {} : {
      chat: (
        <GuestPrompt title="Chat is paused for guests" href={loginFor(account.login_url, "#playground/chat")} site={{ href: "#playground/text", label: "Mask a document instead" }}>
          Free answers from the included model are off right now. Sign in with Google to chat through your own model connection; masking a document on the Text tab still works without an account.
        </GuestPrompt>
      ),
    }),
  };

  return (
    // Playground and Chat word their hosted copy from this context; a guest is the hosted guard too.
    <HostedSessionContext.Provider value={session}>
      <div className="public-teal-theme flex min-h-dvh flex-col bg-canvas text-ink">
        <PublicHeader accountHref={login} />
        <main id="main" tabIndex={-1} aria-label="Playground" className="mx-auto w-full max-w-[1280px] flex-1 space-y-6 px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
          <PlaygroundSection
            tab={tab}
            openTab={openTab}
            caps={{ ...HOSTED_CAPABILITIES, images: true }}
            opened={(k) => visited.has(k)}
            playground={playground}
            engine={engine}
            mockClient={mock}
            chatClient={chatClient}
            chatDraft={chatDraft}
            setChatDraft={setChatDraft}
            server={null}
            intro={intro}
            panels={panels}
          />
        </main>
      </div>
    </HostedSessionContext.Provider>
  );
}

/** A tab a guest can't use yet: what it needs, the sign-in back to it, and where the public page shows it. */
function GuestPrompt({ title, href, site, children }: { title: string; href: string; site: { href: string; label: string }; children: string }) {
  const heading = useId();
  return (
    <section aria-labelledby={heading} className="mt-6 max-w-xl rounded-xl border border-line bg-surface p-6 sm:p-8">
      <h2 id={heading} className="text-xl font-medium text-balance text-ink">{title}</h2>
      <p className="mt-3 text-pretty text-muted">{children}</p>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <ButtonLink variant="primary" href={href}>Sign in with Google</ButtonLink>
        <ButtonLink href={site.href}>{site.label}</ButtonLink>
      </div>
    </section>
  );
}
