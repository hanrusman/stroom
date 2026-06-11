# Security policy

Stroom is a personal-use project. There is no security team. That said, I take
real bugs seriously and would rather hear about them privately than read about
them on the internet.

## Reporting a vulnerability

If you find a security issue, please report it by opening a **private security
advisory** on the GitHub repo:

> Repository → Security → Advisories → New draft security advisory

If you can't use that flow, open a regular issue titled `Security: <one-line>`
without including exploit details, and I'll switch it to a private channel.

Please include:

- A short description of the issue and the impact.
- A minimal reproduction (curl/HTTP request, code path, or PoC).
- The version / commit SHA you tested against.

I'll acknowledge within ~7 days and aim to ship a fix or mitigation within 30
days for issues rated medium or higher. Single-maintainer schedule applies —
slack is appreciated.

## Scope

In scope:

- The API service in `api/` (FastAPI + Postgres).
- The web client in `web/` (Vite/React).
- The database schema and migrations in `schema/`.
- Default configuration, env handling, and middleware.

Out of scope:

- Misconfiguration of your own deploy (missing TLS, public Postgres, etc.).
- Vulnerabilities in third-party dependencies — please report those upstream.
- Social engineering, physical access, or anything requiring access to the
  host outside the application.

## Defaults you should change before exposing this anywhere

- Set `STROOM_INTERNAL_TOKEN` to a random secret (`openssl rand -base64 32`).
- Set `STROOM_DB_PASSWORD` and `LITELLM_MASTER_KEY` to strong random values.
- Leave `STROOM_ENABLE_DOCS` unset in production so `/docs` and `/openapi.json`
  aren't exposed.
- Put the API behind a reverse proxy that terminates TLS.
- Set `STROOM_ALLOWED_ORIGINS` to your actual public hostname(s) only.

## Known limitations

- The login rate-limiter is in-memory per process. It works for a
  single-worker deployment; behind a multi-worker uvicorn it will be looser
  than the documented 5 attempts / 15 min.
- Server-side fetches of user/feed-supplied URLs (`/inbox/fetch`,
  `/inbox/submit` article extraction, og:image scraping, and feed polling)
  run through an SSRF guard (`api/core/url_guard.py`) that resolves the
  hostname and rejects private/loopback/link-local/reserved addresses,
  re-validating on every redirect hop. The guard is *not* applied to
  operator-configured internal integrations (Obsidian, Vikunja, LiteLLM),
  which intentionally point at private hosts — keep those URLs trusted.
