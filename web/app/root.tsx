import {
  isRouteErrorResponse,
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useLoaderData,
  useLocation,
  useRouteLoaderData,
} from "react-router";
import { useContext, useEffect, useRef } from "react";

import type { Route } from "./+types/root";
import "./app.css";
// Shared by every page; each page imports only its own stylesheet besides these.
import "./styles/layout.css";
import "./styles/stats.css";
import "./styles/matches.css";
import "./styles/forms.css";
import { LangProvider, requestLang, type Lang } from "./i18n";
import { NotFoundPage } from "./not-found/NotFoundPage";
import { useTooltipPlacement } from "./components/useTooltipPlacement";
import { NonceContext } from "./nonce";

// Page views for the site's own analytics (api/app/services/analytics.py): only the path and, on the first page,
// the referring site; no cookies; nothing at all for browsers asking not to be tracked. Kept here rather than in a
// module of its own: content blockers block files named like analytics, and the root must always load.
function countPageView(path: string, referrer: string | null) {
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  if (nav.doNotTrack === "1" || nav.globalPrivacyControl === true) return;
  fetch("/api/v1/analytics/view", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, referrer }),
    keepalive: true,
  }).catch(() => {
    // A blocked or failed count never gets in the way of the page.
  });
}

// The language comes with the request, so the first render on the server is already in it.
export function loader({ request }: Route.LoaderArgs) {
  return { lang: requestLang(request) };
}

export const links: Route.LinksFunction = () => [
  // Tab icon: small copies of public/Logo.jpeg (the full image is ~750 KB).
  { rel: "icon", type: "image/png", sizes: "64x64", href: "/favicon.png" },
  { rel: "apple-touch-icon", sizes: "180x180", href: "/apple-touch-icon.png" },
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
  {
    rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&family=Inter:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap",
  },
];


export function Layout({ children }: { children: React.ReactNode }) {
  const nonce = useContext(NonceContext);
  return (
    <html lang={useRouteLoaderData<{ lang: Lang }>("root")?.lang ?? "en"}>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body>
        {children}
        <ScrollRestoration nonce={nonce} />
        <Scripts nonce={nonce} />
      </body>
    </html>
  );
}

export default function App() {
  const { lang } = useLoaderData<typeof loader>();
  // One page view per page opened; the referring site only counts for the first one.
  const { pathname } = useLocation();
  const first = useRef(true);
  useEffect(() => {
    countPageView(pathname, first.current ? document.referrer || null : null);
    first.current = false;
  }, [pathname]);
  useTooltipPlacement();
  return <LangProvider initial={lang}><Outlet /></LangProvider>;
}

// A page that failed (or a 404 thrown by a loader) shows the site's own error page instead of React Router's
// bare one. The App above, and so its language provider, isn't rendered here, hence the provider again.
export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  const lang = useRouteLoaderData<{ lang: Lang }>("root")?.lang ?? "en";
  const status = isRouteErrorResponse(error) ? error.status : 500;
  if (import.meta.env.DEV && !isRouteErrorResponse(error)) console.error(error);
  return <LangProvider initial={lang}><NotFoundPage status={status} /></LangProvider>;
}
