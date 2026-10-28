import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

/** Where focus lands when a menu opens: its first item, its last (ArrowUp), or the checked one. */
type Start = "first" | "last" | "checked";

const ITEMS = '[role="menuitem"],[role="menuitemradio"],[role="menuitemcheckbox"]';

/**
 * The menu-button pattern (WAI-ARIA APG): a button with aria-haspopup and aria-expanded opens
 * a role="menu" list. Arrow keys, Home and End move between items; Escape closes and returns
 * focus to the button; Tab or a click outside closes without taking focus back.
 */
export function useMenu() {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState<Start>("first");
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const items = () => Array.from(menu.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);
  const show = (from: Start) => {
    setStart(from);
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const list = items();
    const checked = list.find((el) => el.getAttribute("aria-checked") === "true");
    (start === "last" ? list.at(-1) : start === "checked" ? (checked ?? list[0]) : list[0])?.focus();
    const outside = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!menu.current?.contains(target) && !trigger.current?.contains(target)) close(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, start, close]);

  const triggerProps = {
    ref: trigger,
    type: "button" as const,
    "aria-haspopup": "menu" as const,
    "aria-expanded": open,
    "aria-controls": open ? menuId : undefined,
    onClick: () => (open ? close(false) : show("checked")),
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        show(e.key === "ArrowUp" ? "last" : "first");
      }
    },
  };

  const menuProps = {
    ref: menu,
    id: menuId,
    role: "menu" as const,
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      const list = items();
      const at = list.indexOf(document.activeElement as HTMLElement);
      const move = (i: number) => {
        e.preventDefault();
        list[(i + list.length) % list.length]?.focus();
      };
      if (e.key === "ArrowDown") move(at + 1);
      else if (e.key === "ArrowUp") move(at < 0 ? -1 : at - 1);
      else if (e.key === "Home") move(0);
      else if (e.key === "End") move(-1);
      else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
      } else if (e.key === "Tab") close(false);
    },
  };

  return { open, close, triggerProps, menuProps };
}

/** Shared look of menu rows: 44 px tall on a phone, 36 px from 1024 px. */
export const MENU_ITEM =
  "flex min-h-11 w-full items-center gap-2.5 px-3.5 text-left text-sm text-ink outline-none hover:bg-surface-2 focus-visible:bg-surface-2 focus:bg-surface-2 lg:min-h-9";
