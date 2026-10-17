# GITV web

Server-rendered React Router 8 frontend for the GITV stats site. It reads everything from the API in `../api`;
in development Vite proxies `/api` to `http://127.0.0.1:8000`.

```bash
npm install
npm run dev        # http://localhost:5173
npm run typecheck
npm run build && npm run start   # production build and server
```

## Layout

```text
app/
├── root.tsx, routes.ts   # app shell and route table
├── routes/               # route modules: page title and meta, render the page component
├── api.ts                # fetch helper and API errors, shared by every page
├── i18n.tsx              # English / Russian: t("English", "Русский") pairs, language from a cookie
├── styles/               # styles shared by every page
├── home/ player/ match/ tournament/ character/ schedule/ profile/ suggestions/ login/ auth/
│                         # one folder per feature: its page components, API client and stylesheet
└── components/           # navbar, search, brand
```

Colours are CSS variables defined once in `app/app.css`.
