import { NavLink, useLocation } from "react-router";
import { clearSession } from "../auth/client";
import { useCurrentUser } from "../auth/useCurrentUser";
import { LangSwitch, useLang } from "../i18n";
import { NavSearch } from "./NavSearch";
import { SignOutIcon } from "./SignOutIcon";
import "./navbar.css";

// Single source of truth for the site navigation. Items without `to` have no
// page yet; give them a route here and every page picks it up.
// `also` lists other path prefixes that keep the item highlighted (a match page under Matches).
const links: { label: [string, string]; to?: string; also?: string[]; hideOnMobile?: boolean }[] = [
  { label: ["Matches", "Матчи"], to: "/matches", also: ["/match/"] },
  { label: ["Players", "Игроки"], to: "/players", also: ["/player/"] },
  { label: ["Tournaments", "Турниры"] },
  { label: ["Abyss", "Бездна"], hideOnMobile: true },
];

function NavItem({ label, to, also = [], className = "" }: { label: string; to?: string; also?: string[]; className?: string }) {
  const { pathname } = useLocation();
  const { t } = useLang();
  if (!to) {
    return <span className={`gitv-nav-link is-disabled ${className}`} aria-disabled="true" title={t("Coming soon", "Скоро")}>{label}</span>;
  }
  const alsoActive = also.some((prefix) => pathname.startsWith(prefix));
  return <NavLink to={to} className={({ isActive }) => `gitv-nav-link ${isActive || alsoActive ? "is-active" : ""} ${className}`}>{label}</NavLink>;
}

export function Navbar() {
  const user = useCurrentUser();
  const { t } = useLang();

  return (
    <nav className="gitv-nav" aria-label={t("Site navigation", "Навигация по сайту")}>
      <div className="gitv-nav-content">
        {links.map(({ hideOnMobile, label, ...link }) => <NavItem key={label[0]} label={t(...label)} {...link} className={hideOnMobile ? "hide-mobile" : ""} />)}
        <NavSearch className="hide-mobile" />
        <LangSwitch />
        {user ? (
          <>
            <NavItem label={user.nickname} to="/profile" className="gitv-nav-user" />
            <button type="button" className="gitv-nav-link gitv-nav-button" onClick={() => clearSession()}><SignOutIcon />{t("Sign out", "Выйти")}</button>
          </>
        ) : (
          <NavItem label={t("Sign in", "Войти")} to="/login" />
        )}
      </div>
    </nav>
  );
}
