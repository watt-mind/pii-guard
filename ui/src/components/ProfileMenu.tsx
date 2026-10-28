import { useId } from "react";
import { SOURCE, type HostedSession } from "../hosted/session";
import { MenuPanel, MenuSeparator } from "./Menu";
import { MENU_ITEM, useMenu } from "../hooks/useMenu";

export const DOCS_URL = `${SOURCE}/tree/develop/docs`;

const LOGOUT_FALLBACK = "/.auth/logout?post_logout_redirect_uri=%2F";

/**
 * The hosted owner's avatar and profile menu: who is signed in, their account, the public
 * site, docs and source, and sign-out. The server sends an opaque Google subject, never a name
 * or email (`hosted/identity.py` reads the subject only), so the avatar shows an initial only when it is given a display name or
 * email, and a person glyph otherwise.
 */
export function ProfileMenu({ session }: { session: HostedSession }) {
  const { open, close, triggerProps, menuProps } = useMenu();
  const identityId = useId();
  const principal = session.account.principal;
  const shown = principal?.name?.trim() || principal?.email?.trim() || "";
  const provider = principal?.provider === "google" || !principal?.provider ? "Google" : principal.provider;
  const initial = shown ? [...shown][0]!.toLocaleUpperCase() : "";

  return (
    <div data-header-item className="relative shrink-0">
      <button
        {...triggerProps}
        aria-label={shown ? `Account menu for ${shown}` : "Account menu"}
        className="grid size-11 place-items-center rounded-full lg:size-9 border border-accent/25 bg-accent-soft text-sm font-medium text-accent-ink transition-shadow hover:shadow-[0_0_0_3px_var(--accent-soft)] aria-expanded:shadow-[0_0_0_3px_var(--accent-soft)]"
      >
        {initial ? (
          <span aria-hidden="true">{initial}</span>
        ) : (
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 8a2.75 2.75 0 1 0 0-5.5A2.75 2.75 0 0 0 8 8ZM3 13.5c.6-2.4 2.6-3.75 5-3.75s4.4 1.35 5 3.75" />
          </svg>
        )}
      </button>
      {open && (
        <MenuPanel menuProps={menuProps} label="Account">
          <div role="group" aria-labelledby={identityId}>
            <div id={identityId} role="presentation" className="px-3.5 pt-2 pb-2">
              <p className="truncate text-sm font-medium text-ink">{shown || "Signed in"}</p>
              <p className="text-xs text-muted">
                with {provider} · {session.account.tier} tier
              </p>
            </div>
            <MenuSeparator />
            <Item href="#overview" icon="M8 8a2.75 2.75 0 1 0 0-5.5A2.75 2.75 0 0 0 8 8ZM3 13.5c.6-2.4 2.6-3.75 5-3.75s4.4 1.35 5 3.75" onSelect={() => close(false)}>
              Account
            </Item>
          </div>
          <MenuSeparator />
          <Item href="#site" icon="M2.5 8h11M8 2.5c1.6 1.5 2.4 3.3 2.4 5.5S9.6 12 8 13.5M8 2.5C6.4 4 5.6 5.8 5.6 8s.8 4 2.4 5.5M13.5 8a5.5 5.5 0 1 1-11 0 5.5 5.5 0 0 1 11 0Z" onSelect={() => close(false)}>
            Visit site
          </Item>
          <ResourceItems onSelect={() => close(false)} />
          <MenuSeparator />
          <Item href={session.account.logout_url || LOGOUT_FALLBACK} icon="M6 13.5H3.5v-11H6M10.5 11 13.5 8l-3-3M13.5 8H6.5">
            Sign out
          </Item>
        </MenuPanel>
      )}
    </div>
  );
}

/** Docs and GitHub, opened in a new tab: they leave the console. */
function ResourceItems({ onSelect }: { onSelect: () => void }) {
  return (
    <>
      <Item href={DOCS_URL} external icon="M3.5 2.5h6l3 3v8h-9zM9.5 2.5v3h3M5.5 8.5h5M5.5 11h5" onSelect={onSelect}>
        Docs
      </Item>
      <Item href={SOURCE} external icon="M6 12.5c-2.5.8-2.5-1.3-3.5-1.5m7 3v-2.1c0-.6.1-1-.3-1.4 1.8-.2 3.6-.9 3.6-4a3.1 3.1 0 0 0-.8-2.1 2.9 2.9 0 0 0-.1-2.1s-.7-.2-2.2.8a7.6 7.6 0 0 0-4 0C4.2 2.1 3.5 2.3 3.5 2.3a2.9 2.9 0 0 0-.1 2.1 3.1 3.1 0 0 0-.8 2.1c0 3.1 1.8 3.8 3.6 4-.4.4-.4.8-.3 1.4v2.1" onSelect={onSelect}>
        GitHub
      </Item>
    </>
  );
}

function Item({ href, icon, external, onSelect, children }: { href: string; icon: string; external?: boolean; onSelect?: () => void; children: string }) {
  return (
    <a role="menuitem" tabIndex={-1} href={href} onClick={onSelect} className={MENU_ITEM} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}>
      <svg aria-hidden="true" viewBox="0 0 16 16" className="size-4 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d={icon} />
      </svg>
      <span className="flex-1">{children}</span>
      {external && (
        <>
          <svg aria-hidden="true" viewBox="0 0 16 16" className="size-3 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 3.5h6.5V10M12.5 3.5 4 12" />
          </svg>
          <span className="sr-only">(opens in a new tab)</span>
        </>
      )}
    </a>
  );
}
