# Stroom — Verbeterplan (juli 2026)

Review van `hanrusman/stroom` @ `main` (`f2b7fac`). Scope: architectuur, refactoring, security, testing/CI. De stack-kant (`vps-stacks`: compose, samenvat-agent, litellm) stond niet in deze omgeving — bevindingen die daar landen staan expliciet gemarkeerd met **[vps-stacks]**.

## Samenvatting

Het fundament is beter dan de gemiddelde hobby-app: scrypt-auth met timing-equalisatie, `hmac.compare_digest` overal, een serieuze SSRF-guard (`core/url_guard.py`) die élke redirect-hop valideert, DOMPurify op alle markdown-rendering, `FOR UPDATE SKIP LOCKED` queue-claims, en een non-root Docker-image. De security-audit heeft zichtbaar gewerkt.

De hoofdproblemen zijn structureel, niet incidenteel:

| # | Bevinding | Categorie | Ernst |
|---|---|---|---|
| 1 | `api/main.py` is 3706 regels: 60+ endpoints, workers, cron, feed-parsing, mem-gate en scoring in één module | Architectuur | Hoog |
| 2 | Geen CI: geen tests, lint of audit bij push/PR | Kwaliteit | Hoog |
| 3 | Sessietokens staan plaintext in de database | Security | Middel |
| 4 | Dubbele sessie-lookup per request (middleware + `require_user`) | Performance | Middel |
| 5 | 40 tests op ~8400 regels Python; routers vrijwel ongetest | Kwaliteit | Middel |
| 6 | `web/App.tsx` 2895 regels, `AdminPage.tsx` 1590 | Architectuur | Middel |
| 7 | Dode code: `csrf_guard()` ongebruikt, `kokoro-onnx`+`soundfile`+`espeak-ng` (Kokoro nooit gebouwd), `web/prototype/` | Hygiëne | Middel |
| 8 | 48× `print()` als logging in main.py; geen levels, geen structuur | Observability | Middel |
| 9 | Login-ratelimit keyed op `request.client.host` — achter nginx is dat de proxy-IP | Security | Middel |
| 10 | Config versnipperd: `core/config.py` Settings + 26 losse `os.environ.get` in main.py | Architectuur | Laag |
| 11 | SQL-migraties (schema/migrations/*.sql) worden handmatig toegepast, geen tracking | Operations | Laag |
| 12 | Eén globale `_worker_heartbeat_at` voor alle workers — één levende worker maskeert een vastgelopen andere | Reliability | Laag |
| 13 | Dependency-pins verouderd (fastapi 0.115, httpx 0.27), geen pip-audit/dependabot | Security | Laag |
| 14 | **[vps-stacks]** `stroom-api` bindt `0.0.0.0:8100` waar de rest 127.0.0.1-only is | Security | Verifiëren |
| 15 | **[vps-stacks]** `stroom-web` is een compose-orphan | Operations | Verifiëren |

---

## Deel 1 — Architectuur & refactoring

### R1. `main.py` opsplitsen (het grote werk)

`main.py` bevat nu zeven verantwoordelijkheden die elkaar niets te zeggen hebben: app-setup, auth-middleware, mem-gate, queue-workers, cron-orkestratie, feed-parsing/backfill, en tientallen endpoint-groepen. Elke wijziging raakt hetzelfde bestand, merge-conflicten zijn gegarandeerd, en niets ervan is los testbaar.

Er ligt al een goed patroon: `routers/` en `services/` bestaan en zeven routers zijn al geëxtraheerd. Het plan is dat patroon afmaken — geen nieuwe architectuur, alleen de bestaande consequent doorvoeren.

**Doelstructuur:**

```
api/
├── main.py               # ~80 regels: app factory + include_routers, meer niet
├── core/
│   ├── config.py         # ALLE env-config (zie R2)
│   ├── memory.py         # _cgroup_v2_available_mb, _mem_gate_blocks, ...
│   └── middleware.py     # AuthMiddleware
├── routers/
│   ├── auth.py           # /auth/login, /auth/logout, /auth/me
│   ├── huygens.py        # /huygens/* (items, status, schedule, topics)
│   ├── digests.py        # /huygens/{slug}/digest*
│   ├── search.py         # /search
│   ├── admin_sources.py  # /admin/sources*, backfill
│   ├── admin_queue.py    # /admin/queue*, /admin/cron/*
│   └── admin_quality.py  # /admin/quality-*
├── schemas/              # Pydantic-modellen uit main.py (HuygensItem, AdminSource, ...)
│   └── huygens.py, admin.py, ...
├── workers/
│   ├── queue.py          # _claim_next_*, met SKIP LOCKED (verhuist as-is)
│   ├── summarize.py      # _summarize_worker + _summarize_single_item
│   ├── transcribe.py     # _transcribe_worker + trigger-retry-state
│   └── monitor.py        # _queue_depth_logger, heartbeats (zie R5)
└── pipeline/             # bestaat al: digest, articles — feed-parsing hierheen
    └── feeds.py          # _feed_first_text, _feed_media_url, _refresh_one, backfill
```

**Voorbeeldcode — de nieuwe `main.py` (app factory):**

```python
# api/main.py
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.middleware import AuthMiddleware
from workers.registry import start_workers, stop_workers
from routers import (
    auth, huygens, digests, search,
    admin_sources, admin_queue, admin_quality,
    legacy, lessons, settings as settings_router,
    admin_topics, ask, inbox, transcripts,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=30.0, limits=httpx.Limits(max_connections=10))
    app.state.llm_client = httpx.AsyncClient(
        timeout=settings.LLM_HTTP_TIMEOUT_SEC,
        limits=httpx.Limits(max_connections=settings.LLM_MAX_CONCURRENT))
    app.state.worker_tasks = await start_workers(app)
    yield
    await stop_workers(app.state.worker_tasks)
    await app.state.http_client.aclose()
    await app.state.llm_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stroom API", lifespan=lifespan, root_path="/api",
        docs_url="/docs" if settings.ENABLE_DOCS else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)
    for r in (auth, huygens, digests, search, admin_sources, admin_queue,
              admin_quality, legacy, lessons, settings_router, admin_topics,
              ask, inbox, transcripts):
        app.include_router(r.router)
    return app


app = create_app()
```

**Voorbeeldcode — één geëxtraheerde router (patroon voor alle):**

```python
# api/routers/search.py
from fastapi import APIRouter, Depends, Query

from core.db import get_async_session
from schemas.huygens import SearchHit
from services.search_service import search_items_fts

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchHit])
async def search_items(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=50),
    session=Depends(get_async_session),
):
    return await search_items_fts(session, q=q, limit=limit)
```

De router blijft dun; de SQL verhuist naar een service-functie die je zonder HTTP-laag kunt testen (zie T1).

**Aanpak** (verlaagd risico, geen big-bang):
1. Eerst `schemas/` en `core/memory.py` — pure verplaatsingen, geen gedrag.
2. Dan per endpoint-groep een router, één PR per groep. `main.py` importeert en included; oude code verwijderen in dezelfde PR.
3. Workers als laatste (raken lifespan).
4. Vuistregel klaar-criterium: `main.py` < 100 regels, geen `@app.` decorators meer.

### R2. Config centraliseren

`core/config.py` heeft een nette pydantic-settings `Settings`, maar main.py doet daarnaast 26 losse `os.environ.get`-calls (`SUMMARIZE_WORKERS`, `QUALITY_EMBEDDING_ENABLED`, `STROOM_ENABLE_DOCS`, `STROOM_ALLOWED_ORIGINS`, mem-gate-drempels...). Twee configuratiesystemen betekent: geen enkele plek waar je alle knoppen ziet, en env-parsing (int-conversie, bool-strings) telkens opnieuw.

**Voorbeeldcode:**

```python
# api/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    DATABASE_URL: str
    ASYNC_DATABASE_URL: str
    SQL_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- LLM ---
    LITELLM_URL: str = "http://litellm:4000/v1/chat/completions"
    LITELLM_MASTER_KEY: str
    LLM_HTTP_TIMEOUT_SEC: float = 300.0
    LLM_MAX_CONCURRENT: int = 4

    # --- Workers & mem-gate ---
    SUMMARIZE_WORKERS: int = 2
    WORKER_IDLE_POLL_SEC: float = 5.0
    SUMMARIZE_MIN_FREE_MB: int = 400
    TRANSCRIBE_MIN_FREE_MB: int = 700
    TRANSCRIBE_AGENT_URL: str = "http://samenvat-agent:8000"

    # --- Features & security ---
    ENABLE_DOCS: bool = False              # was STROOM_ENABLE_DOCS
    QUALITY_EMBEDDING_ENABLED: bool = False
    STROOM_ALLOWED_ORIGINS: str = ""
    STROOM_INTERNAL_TOKEN: str = ""
    STROOM_INBOX_TOKEN: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        defaults = ["http://localhost:3000", "http://localhost:8101"]
        extra = [o.strip() for o in self.STROOM_ALLOWED_ORIGINS.split(",") if o.strip()]
        return list(dict.fromkeys(defaults + extra))


settings = Settings()
```

Bijvangst: `.env.example` wordt automatisch de complete referentie, en pydantic valideert types bij boot (fail-fast bij typo's).

### R3. Logging: van `print()` naar `logging`

48 `print(..., flush=True)`-calls in main.py alleen al. Geen levels, dus `docker logs` filtert niet; geen logger-namen, dus je ziet niet welke worker sprak; de security-relevante regels (`[SECURITY] Invalid internal token...`) zijn niet te onderscheiden van debug-ruis.

**Voorbeeldcode:**

```python
# api/core/logging.py
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    # httpx is spraakzaam op INFO
    logging.getLogger("httpx").setLevel(logging.WARNING)
```

```python
# gebruik, bv. workers/transcribe.py
import logging
log = logging.getLogger("stroom.worker.transcribe")

log.info("started")
log.warning("transient trigger fail voor %s (poging %d/%d): %s — requeued",
            item_id, attempts, max_tries, exc)
# security-events op eigen logger zodat je erop kunt alerten:
logging.getLogger("stroom.security").warning(
    "invalid internal token from %s to %s", request.client.host, path)
```

Mechanische refactor (search/replace per module tijdens R1), geen extra dependency. Als je later gestructureerde logs wilt: `structlog` is een drop-in bovenop dit fundament.

### R4. Migratie-runner

`schema/migrations/` heeft genummerde SQL-files (002–011+), maar niets houdt bij wat is toegepast — dat is nu tribal knowledge bij deploys. Alembic is overkill voor een raw-SQL-project; een runner van 40 regels volstaat en past bij het bestaande patroon.

**Voorbeeldcode:**

```python
# api/scripts/migrate.py
"""Past nog-niet-uitgevoerde schema/migrations/*.sql toe, op volgorde.

Gebruik:  python -m scripts.migrate          (in de container)
Elke file draait in één transactie; bijgehouden in schema_migrations.
"""
import pathlib
import sys

from sqlalchemy import create_engine, text

from core.config import settings

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[2] / "schema" / "migrations"


def main() -> int:
    engine = create_engine(settings.DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """))
        done = {r[0] for r in conn.execute(text("SELECT filename FROM schema_migrations"))}

    pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in done)
    if not pending:
        print("migrate: niets te doen")
        return 0

    for path in pending:
        print(f"migrate: {path.name} ...", end=" ")
        with engine.begin() as conn:          # transactie per file
            conn.execute(text(path.read_text()))
            conn.execute(text(
                "INSERT INTO schema_migrations (filename) VALUES (:f)"
            ).bindparams(f=path.name))
        print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Draai 'm bij deploy vóór `uvicorn` start (compose `command: sh -c "python -m scripts.migrate && uvicorn ..."`), of als eerste stap in lifespan. Bestaande databases: seed `schema_migrations` eenmalig met de al-toegepaste filenames.

### R5. Per-worker heartbeat

`_worker_heartbeat_at` is één global die door álle workers wordt geüpdatet. De watchdog ziet dus "iemand leeft" — een vastgelopen transcribe-worker is onzichtbaar zolang een summarize-worker tikt.

**Voorbeeldcode:**

```python
# api/workers/monitor.py
import time

_heartbeats: dict[str, float] = {}


def beat(worker: str) -> None:
    _heartbeats[worker] = time.time()


def stalled(max_age_sec: float = 300.0) -> list[str]:
    """Namen van workers die te lang niets van zich lieten horen."""
    now = time.time()
    return [name for name, ts in _heartbeats.items() if now - ts > max_age_sec]
```

Workers roepen `beat("sum-worker-0")` aan in hun loop; de watchdog in de nightly-cron rapporteert `stalled()` per naam. Zelfde patroon lost ook de unbounded `_TRANSCRIBE_TRIGGER_ATTEMPTS`-dict op: geef die een max-grootte of ruim entries op bij success/fail (gebeurt al) én bij item-verwijdering.

### R6. Frontend: `App.tsx` opsplitsen

2895 regels met ~20 componenten, de audio-player-context, markdown-sanitizing, en alle views in één file; `AdminPage.tsx` nog eens 1590. Zelfde recept als de API: verplaatsen, niet herschrijven.

```
web/src/
├── App.tsx               # routing + shell, < 200 regels
├── lib/
│   ├── sanitize.ts       # sanitizeMarkdown + DOMPurify-config (één plek!)
│   └── api.ts            # bestaat al
├── components/
│   ├── TopicChip.tsx, Meta.tsx, QualityScoreEditor.tsx, ArticleBody.tsx, ...
│   └── player/           # StickyPlayer + GlobalAudioContext (bestaan al los)
└── views/
    ├── InboxView.tsx, ItemDetail.tsx, DigestView.tsx, SearchView.tsx
    └── admin/            # AdminPage opknippen per tab
```

`sanitizeMarkdown` verdient z'n eigen module omdat het security-kritisch is: nu staan er twee sanitize-paden in App.tsx (de strikte `sanitizeMarkdown` met allowlist, en een kale `DOMPurify.sanitize(item.description ?? '')` op regel 844). Eén module = één beleid (zie ook S4).

Overweeg TanStack Query voor de data-fetching (er is veel handmatige loading/error-state), maar dat is een aparte, latere exercitie — niet combineren met het opknippen.

### R7. Dode code en bagage opruimen

| Wat | Waarom weg |
|---|---|
| `csrf_guard()` in `core/auth.py` | Wordt nergens aangeroepen; de middleware doet de échte origin-check. Twee CSRF-implementaties waarvan één dood is verwart elke toekomstige audit. |
| `kokoro-onnx`, `soundfile`, `numpy` in requirements.txt + `espeak-ng` in het Dockerfile | Kokoro-TTS is nooit gebouwd (TTS zit in samenvat-agent/XTTS). Dit is ~200 MB image-bloat en attack surface. `numpy` alleen behouden als iets anders het echt importeert. |
| `web/prototype/` | Demo-html in de productie-repo. |
| `psycopg2-binary` óf `asyncpg` | Er zijn twee Postgres-drivers; sync engine wordt alleen voor scripts gebruikt. Kan naar `psycopg[binary]` (één driver, sync+async) — of laat het bewust zo en documenteer waarom. |
| `routers/legacy.py` (214 regels) | Naam zegt het al. Check met access-logs of de web-UI het nog aanroept; zo nee → verwijderen, zo ja → migreren en dan verwijderen. |
| `browser-extension/` | Geen token-opslag gevonden (goed), maar check of hij nog werkt tegen de huidige API of ook legacy is. |

---

## Deel 2 — Security

Het bestaande niveau is goed; dit zijn verdiepingsslagen, geen brandjes.

### S1. Sessietokens hashen in de database (belangrijkste vinding)

`sessions.token` bevat het ruwe bearer-token. Wie de database leest (backup-lek, SQL-injectie elders, een `pg_dump` op een verkeerde plek) kan elke actieve sessie overnemen. De fix is goedkoop: sla alleen een SHA-256-digest op. Geen salt/scrypt nodig — tokens hebben al 256 bits entropie, het gaat puur om onomkeerbaarheid.

**Voorbeeldcode (`core/auth.py`):**

```python
import hashlib


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(session, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    await session.exec(sa_text(
        "INSERT INTO sessions (token, user_id, expires_at) "
        "VALUES (:t, CAST(:u AS uuid), :e)"
    ).bindparams(t=_token_digest(token), u=user_id, e=expires_at))
    await session.commit()
    return token, expires_at          # het ruwe token gaat alléén de cookie in


async def get_session_user(session, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    r = await session.exec(sa_text(
        "SELECT u.id::text, u.email, s.expires_at "
        "FROM sessions s JOIN users u ON s.user_id = u.id "
        "WHERE s.token = :t"
    ).bindparams(t=_token_digest(token)))
    ...
```

**Migratie** (`schema/migrations/0XX-hash-session-tokens.sql`):

```sql
-- Bestaande plaintext-tokens hashen. encode(digest(...)) vereist pgcrypto.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE sessions SET token = encode(digest(token, 'sha256'), 'hex')
WHERE length(token) <> 64;   -- idempotent: sha256-hex is altijd 64 tekens
```

Bestaande cookies blijven werken (zelfde token, nu vergeleken via digest). Dit patroon geldt ook voor **weekmenu** — zelfde auth-code, zelfde vinding.

### S2. Dubbele sessie-lookup per request weghalen

`AuthMiddleware` valideert de sessie (DB-query) en zet `request.state.user` — maar niets leest dat: elke endpoint met `Depends(require_user)` doet een tweede identieke query. Elke authenticated request kost dus 2× een sessions-JOIN.

**Voorbeeldcode:**

```python
# core/auth.py
async def require_user(request: Request,
                       session=Depends(get_async_session)) -> dict:
    # AuthMiddleware heeft de sessie al gevalideerd en gecachet op request.state.
    user = getattr(request.state, "user", None)
    if user:
        return user
    # Fallback voor paden die niet door de middleware kwamen (tests, interne callers)
    token = request.cookies.get(SESSION_COOKIE)
    user = await get_session_user(session, token)
    if not user:
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    return user
```

### S3. Login-ratelimit proxy-bewust en begrensd maken

Twee problemen in `check_login_rate_limit`:
1. De key is `request.client.host`. Achter de nginx van `stroom-web` is dat het interne proxy-IP → alle bezoekers delen één bucket (DoS op jezelf), of — als je ooit `X-Forwarded-For` blind zou vertrouwen — is de key spoofbaar.
2. `_LOGIN_ATTEMPTS` wordt nooit geschoond → onbegrensde groei (traag, maar principieel).

**Voorbeeldcode:**

```python
# core/auth.py
TRUSTED_PROXIES = {ip.strip() for ip in
                   os.environ.get("STROOM_TRUSTED_PROXIES", "").split(",") if ip.strip()}
_MAX_TRACKED_KEYS = 10_000


def client_ip(request: Request) -> str:
    """Echte client-IP: alleen X-Forwarded-For vertrouwen als de directe
    peer een geconfigureerde proxy is."""
    peer = request.client.host if request.client else "?"
    if peer in TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def check_login_rate_limit(key: str) -> bool:
    now = time.time()
    # Opportunistische cleanup houdt de dict begrensd zonder achtergrondtaak
    if len(_LOGIN_ATTEMPTS) > _MAX_TRACKED_KEYS:
        cutoff = now - LOGIN_WINDOW_S
        for k in [k for k, ts in _LOGIN_ATTEMPTS.items() if not ts or ts[-1] < cutoff]:
            del _LOGIN_ATTEMPTS[k]
    recent = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < LOGIN_WINDOW_S]
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        _LOGIN_ATTEMPTS[key] = recent
        return False
    recent.append(now)
    _LOGIN_ATTEMPTS[key] = recent
    return True
```

En in de login-route: `check_login_rate_limit(client_ip(request))`. **[vps-stacks]**: zet `STROOM_TRUSTED_PROXIES` op het interne IP van de nginx-container.

### S4. Eén sanitize-beleid + reverse-tabnabbing dichtzetten

- Regel 844 in App.tsx gebruikt `DOMPurify.sanitize(item.description ?? '')` met de default-allowlist (veel ruimer dan de strikte `sanitizeMarkdown`-config). Feeds zijn untrusted input; gebruik overal dezelfde strikte helper.
- `ALLOWED_ATTR` bevat `target`, maar niets voegt `rel="noopener noreferrer"` toe → links met `target="_blank"` uit feed-content geven de doelpagina `window.opener`.

**Voorbeeldcode (`web/src/lib/sanitize.ts`):**

```ts
import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = ['p','br','strong','em','ul','ol','li','h1','h2','h3','h4','h5','h6','a','blockquote','code','pre','span','img'];
const ALLOWED_ATTR = ['href','target','class','src','alt'];

// Reverse-tabnabbing: forceer rel=noopener op elke externe link.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('rel', 'noopener noreferrer');
    if (!node.getAttribute('target')) node.setAttribute('target', '_blank');
  }
  // Alleen http(s)-afbeeldingen; geen data:-URI's uit feeds.
  if (node.tagName === 'IMG') {
    const src = node.getAttribute('src') ?? '';
    if (!/^https?:\/\//i.test(src)) node.removeAttribute('src');
  }
});

export const sanitizeHtml = (html: string): string =>
  DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });

export const sanitizeMarkdown = (content: string | null | undefined,
                                 opts?: { breaks?: boolean }): string => {
  if (!content) return '';
  const html = marked.parse(content, { async: false, breaks: opts?.breaks ?? true }) as string;
  return sanitizeHtml(html);
};
```

Alle `dangerouslySetInnerHTML`-plekken importeren voortaan uit deze ene module.

### S5. Internal token opsplitsen per doel

`STROOM_INTERNAL_TOKEN` wordt gedeeld door: de transcribe-callback van samenvat-agent, de cron-caller, én machine-to-machine readers van `/transcripts`. Het inbox-token is al bewust apart gezet ("kan alléén items insturen") — trek die lijn door. Als één consumer lekt (bijv. het token staat in een cron-script in een andere repo), wil je alleen dát token roteren, en wil je dat een gelekt cron-token geen transcripten kan lezen.

**Voorbeeldcode (middleware-fragment):**

```python
# core/middleware.py
_TOKEN_SCOPES = {
    # header-token → set van path-scopes
    os.environ.get("STROOM_AGENT_TOKEN", ""):  {"callback"},   # samenvat-agent
    os.environ.get("STROOM_CRON_TOKEN", ""):   {"cron"},       # nightly-cron caller
    os.environ.get("STROOM_READER_TOKEN", ""): {"transcripts"},# m2m-readers
    # Overgangsperiode: het oude token mag alles; verwijderen na rotatie.
    os.environ.get("STROOM_INTERNAL_TOKEN", ""): {"callback", "cron", "transcripts"},
}
_TOKEN_SCOPES.pop("", None)   # lege env-vars niet als geldig token registreren


def _scope_for_path(path: str) -> str | None:
    if path.endswith(("/transcribe-callback", "/heartbeat")):
        return "callback"
    if "/admin/cron/" in path or path.endswith(("/admin/sources/backfill-stale",
                                                "/admin/quality-backfill")):
        return "cron"
    if path.startswith(("/transcripts", "/internal/")):
        return "transcripts"
    return None


def token_allows(request, path: str) -> bool:
    scope = _scope_for_path(path)
    if scope is None:
        return False
    tok = request.headers.get("x-stroom-internal-token", "")
    for known, scopes in _TOKEN_SCOPES.items():
        if hmac.compare_digest(tok, known) and scope in scopes:
            return True
    return False
```

Rollout zonder downtime: nieuwe tokens uitdelen aan de consumers, daarna het overgangstoken uit de env halen.

### S6. Security-headers op de web-laag **[vps-stacks]**

De API zet geen security-headers en de nginx van `stroom-web` waarschijnlijk ook niet (kon ik hier niet verifiëren). Voor een app die third-party feed-content rendert is een CSP het verschil tussen "DOMPurify-bypass = game over" en "DOMPurify-bypass = geblokkeerd door CSP".

**Voorbeeldconfig (nginx, stroom-web):**

```nginx
# vps-stacks/stroom/web-nginx.conf — in het server-block
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
```

Let op: `img-src https:` is nodig voor feed-thumbnails; `media-src https:` voor de audio-player. Test de player en externe thumbnails na activering.

### S7. Verifiëren: `0.0.0.0:8100` binding **[vps-stacks]**

Alle andere services binden `127.0.0.1` (Tailscale-only); `stroom-api` bindt `0.0.0.0:8100`. Als Strongbad's firewall poort 8100 niet dichtzet, staat de API — inclusief login-endpoint — op het publieke internet. Actie: `ss -tlnp | grep 8100` + firewallregels checken; als publiek niet de bedoeling is → `127.0.0.1:8100:8000` zoals de rest. De auth houdt stand, maar exposure zonder reden is exposure zonder reden.

### S8. Dependencies en supply chain

- Pins zijn ~een jaar oud (fastapi 0.115.0, httpx 0.27.0, sqlmodel 0.0.22). Niet acuut, maar zonder CI merk je een CVE nooit.
- Voeg `pip-audit` en `npm audit` toe aan CI (zie T2) en zet Dependabot/Renovate aan met een maandelijkse cadans — bij een one-maintainer-project wil je geen wekelijkse PR-ruis.

---

## Deel 3 — Testing & CI

### T1. Router-tests zonder database-gedoe

40 testfuncties, vooral pure functies en queue-logica. De routers (waar de bugs van #60–#64 zaten: cron-locks, watchdog, timeouts) zijn ongetest. Met `dependency_overrides` + een fake-session test je routers zonder Postgres; voor de SQL-zware services is een wekelijkse integratietest tegen echte Postgres (in CI via service-container) waardevoller dan mocks.

**Voorbeeldcode:**

```python
# api/tests/test_search_router.py
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from core.db import get_async_session
from core.auth import require_user


class FakeResult:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows
    def first(self): return self._rows[0] if self._rows else None


class FakeSession:
    def __init__(self, rows): self.rows = rows
    async def exec(self, *_a, **_k): return FakeResult(self.rows)
    async def commit(self): pass


@pytest.fixture
def client_factory():
    def make(rows):
        app.dependency_overrides[get_async_session] = lambda: FakeSession(rows)
        app.dependency_overrides[require_user] = lambda: {"id": "t", "email": "t@t"}
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")
    yield make
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_search_requires_min_length(client_factory):
    async with client_factory([]) as c:
        r = await c.get("/search", params={"q": "x"})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_search_returns_hits(client_factory):
    rows = [("id-1", "Titel", "snippet...", 0.42)]
    async with client_factory(rows) as c:
        r = await c.get("/search", params={"q": "kimi"})
    assert r.status_code == 200
    assert r.json()[0]["title"] == "Titel"
```

(Vereist dat de AuthMiddleware in testmodus een sessie-cookie fakeert of dat tests de middleware-check via een testtoken passeren — het schoonste is een `STROOM_TEST_MODE` die in `create_app()` de middleware overslaat, alleen instelbaar via env in de testrunner.)

**Prioriteit van testdoelen** (waar de regressies daadwerkelijk zaten, zie git-log): cron-nightly-orkestratie, run-lock, mem-gate-drempels, queue-claims, transcribe-callback-flow, feed-refresh-timeouts.

### T2. CI vanaf nul

Er is geen `.github/workflows/`. Minimale pipeline die alles uit dit plan bewaakt:

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push: { branches: [main] }
  pull_request:

jobs:
  api:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: api } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11", cache: pip }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: python -m pytest -q
      - run: pip install ruff && ruff check .
      - run: pip install pip-audit && pip-audit -r requirements.txt --strict
        continue-on-error: true   # eerst signaal opbouwen, later hard maken

  web:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: web } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: web/package-lock.json }
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npm run build
```

Plus `ruff.toml` met een mild profiel (`E, F, I` om te beginnen) zodat de eerste run niet in 400 findings verdrinkt.

---

## Deel 4 — Volgorde en omvang

| Fase | Wat | Omvang | Waarom eerst |
|---|---|---|---|
| 1. Quick wins | S1 (token-hashing), S2 (dubbele lookup), R7 (dode code: csrf_guard, kokoro, prototype), S7-check **[vps-stacks]** | ~1 dag | Hoogste security-opbrengst per regel; geen structuurwijziging |
| 2. Vangnet | T2 (CI) + ruff + bestaande tests erin | ~½ dag | Zonder vangnet is fase 3 onverantwoord |
| 3. Refactor | R1 (main.py opknippen, PR per endpoint-groep), R2 (config), R3 (logging) — in die volgorde, R2/R3 liften mee per verplaatste module | 1–2 weken doorlooptijd, verspreid | Het grote werk; alles hierna wordt goedkoper |
| 4. Verdieping | S3 (ratelimit), S4 (sanitize-module), S5 (token-scopes), S6 **[vps-stacks]** (CSP), R4 (migraties), R5 (heartbeats), T1 (router-tests) | ~1 week verspreid | Bouwt op de nieuwe structuur |
| 5. Frontend | R6 (App.tsx/AdminPage opknippen) | ~3 dagen | Kan parallel aan 4; los deploybaar |

**Niet doen** (bewust): microservices-split (de monoliet-met-workers past bij één gebruiker op één VPS), Alembic (SQL-runner volstaat), Redis voor rate-limiting/queue (Postgres SKIP LOCKED werkt bewezen goed), en een frontend-rewrite (opknippen ja, herschrijven nee).

## Wat ik niet heb kunnen zien

- `vps-stacks` (compose-definities, nginx-config, .env-hygiëne, netwerk-topologie) en `samenvat-agent` (yt-dlp/WhisperX/XTTS-code — juist daar zit veel untrusted-input-verwerking: mediabestanden, subprocess-aanroepen). Een vervolg-review daarvan is de logische tweede helft; met name samenvat-agent verdient dezelfde SSRF/subprocess-blik als de API nu heeft gehad.
- Runtime-gedrag (geheugen, query-plans, feitelijke poort-exposure) — de S7-check moet op Strongbad zelf.
