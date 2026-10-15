import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useLoaderData,
  useRouteLoaderData,
} from "react-router";

import type { Route } from "./+types/root";
import "./app.css";
import { LangProvider, langFromCookie, type Lang } from "./i18n";

// The language comes from the cookie, so the first render on the server is already in it.
export function loader({ request }: Route.LoaderArgs) {
  return { lang: langFromCookie(request.headers.get("Cookie")) };
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
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  const { lang } = useLoaderData<typeof loader>();
  return <LangProvider initial={lang}><Outlet /></LangProvider>;
}
