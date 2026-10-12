# API backend

Minimal FastAPI backend structure for the React Router app. FastAPI is the only
application library; configuration and the starter modules use the Python
standard library.

## Structure

```text
api/
├── app/
│   ├── core/       # Application settings
│   ├── routes/     # HTTP route modules and API router
│   ├── services/   # Business logic modules
│   └── main.py     # FastAPI application factory and ASGI entry point
└── requirements.txt
```

Install the dependency with `python -m pip install -r api/requirements.txt`.
Run with an ASGI server, for example `uvicorn app.main:app --reload` from
inside `api/` (install Uvicorn separately if it is not already available).

The starter health endpoint is `/api/v1/health`. Add route modules in
`app/routes/` and include their routers from `app/routes/router.py`.
