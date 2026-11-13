import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router";
import { clearSession, isPlayerEditor, mayBet, STAFF_ROLES } from "../auth/client";
import { useCurrentUser } from "../auth/useCurrentUser";
import { LangSwitch, useLang } from "../i18n";
import { CoffeeIcon } from "./CoffeeIcon";
import { NavSearch } from "./NavSearch";
import { SignOutIcon } from "./SignOutIcon";
import { fetchUnresolved } from "../unresolved/api";
import { visit } from "../bets/api";
import "../unresolved/unresolved.css";
import "./navbar.css";

// Single source of truth for the site navigation. Items without `to` have no
// page yet; give them a route here and every page picks it up.
// `also` lists other path prefixes that keep the item highlighted (a match page under Matches).
const links: { label: [string, string]; to?: string; also?: string[] }[] = [
  { label: ["Matches", "Матчи"], to: "/matches", also: ["/match/"] },
  { label: ["Players", "Игроки"], to: "/players", also: ["/player/"] },
  { label: ["Tournaments", "Турниры"], to: "/tournaments", also: ["/tournament/"] },
  { label: ["Characters", "Персонажи"], to: "/characters" },
  { label: ["Abyss", "Бездна"], to: "/abyss", also: ["/abyss/"] },
];

function NavItem({ label, to, also = [], className = "", badge }: { label: string; to?: string; also?: string[]; className?: string; badge?: number }) {
  const { pathname } = useLocation();
  const { t } = useLang();
  if (!to) {
    return <span className={`gitv-nav-link is-disabled ${className}`} aria-disabled="true" title={t("Coming soon", "Скоро")}>{label}</span>;
  }
  const alsoActive = also.some((prefix) => pathname.startsWith(prefix));
  return (
    <NavLink to={to} className={({ isActive }) => `gitv-nav-link ${isActive || alsoActive ? "is-active" : ""} ${className}`}>
      {label}{badge ? <span className="unresolved-count">{badge}</span> : null}
    </NavLink>
  );
}

export function Navbar() {
  const user = useCurrentUser();
  const { t, locale } = useLang();
  const { pathname } = useLocation();
  // On phones the sections and the search drop down from a button; on wider screens they stand in the bar (navbar.css).
  const [open, setOpen] = useState(false);
  const nav = useRef<HTMLElement>(null);
  // Organizers and admins: how many matches of their tournaments need a winner set by hand
  const editor = isPlayerEditor(user);
  const [unresolved, setUnresolved] = useState(0);
  useEffect(() => {
    if (!editor) return;
    fetchUnresolved().then((rows) => setUnresolved(rows.filter((m) => !m.waiting).length)).catch(() => setUnresolved(0));
  }, [editor, pathname]);

  // Bet testers: any page counts as the day's visit (it gives the daily points), and the menu shows the points
  const bettor = mayBet(user);
  const [points, setPoints] = useState<number | null>(null);
  useEffect(() => {
    if (!bettor) return;
    visit().then((wallet) => setPoints(wallet.balance)).catch(() => setPoints(null));
  }, [bettor, pathname]);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => { if (!nav.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <nav className="gitv-nav" ref={nav} aria-label={t("Site navigation", "Навигация по сайту")}>
      <div className="gitv-nav-content">
        <button type="button" className="gitv-nav-link gitv-nav-button gitv-nav-toggle" aria-expanded={open} aria-controls="gitv-nav-menu" onClick={() => setOpen((v) => !v)}>
          <span aria-hidden="true">{open ? "✕" : "☰"}</span> {t("Menu", "Меню")}
        </button>
        <div id="gitv-nav-menu" className={`gitv-nav-menu${open ? " is-open" : ""}`}>
          {links.map(({ label, ...link }) => <NavItem key={label[0]} label={t(...label)} {...link} />)}
          {user && STAFF_ROLES.includes(user.role) && <NavItem label={t("Analytics", "Аналитика")} to="/analytics" />}
          {user?.role === "super_admin" && <NavItem label={t("Bundles", "Связки")} to="/bundles" />}
          {bettor && <NavItem label={points == null ? t("Bets", "Ставки") : `${t("Bets", "Ставки")} · ${points.toLocaleString(locale)}`} to="/bets" />}
          {editor && <NavItem label={t("Unresolved", "Неразрешённые")} to="/unresolved" badge={unresolved} />}
          <NavSearch />
        </div>
        {/* Supporting the site; on phones only the icon fits. */}
        <a className="gitv-nav-link gitv-nav-kofi" href="https://ko-fi.com/abyssgitv" target="_blank" rel="noopener noreferrer"
          aria-label={t("Support GITV on Ko-fi", "Поддержать GITV на Ko-fi")} title={t("Support GITV on Ko-fi", "Поддержать GITV на Ko-fi")}>
          <CoffeeIcon /><span className="gitv-nav-kofi-label">{t("Support", "Поддержать")}</span>
        </a>
        {user ? (
          <>
            <NavItem label={user.nickname} to="/profile" className="gitv-nav-user" />
            {/* Icon only: a text label would change width with the language. */}
            <button type="button" className="gitv-nav-link gitv-nav-button" onClick={() => clearSession()}
              aria-label={t("Sign out", "Выйти")} title={t("Sign out", "Выйти")}><SignOutIcon /></button>
          </>
        ) : (
          <NavItem label={t("Sign in", "Войти")} to="/login" className="gitv-nav-signin" />
        )}
        {/* Last, at the far right: nothing after it can push it around when the language or the session changes. */}
        <LangSwitch />
      </div>
    </nav>
  );
}
