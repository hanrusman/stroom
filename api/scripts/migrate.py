"""Past nog-niet-uitgevoerde schema/migrations/*.sql toe, op volgorde (verbeterplan R4).

Gebruik (in de container, vóór uvicorn start):
    python -m scripts.migrate

Elke file draait in één transactie; toegepaste files worden bijgehouden in
schema_migrations. Voor een bestaande database die al bij is: seed de tabel
eenmalig met de al-toegepaste filenames via --baseline (markeert alles als
toegepast zonder SQL te draaien).
"""
import pathlib
import sys

from sqlalchemy import create_engine, text

from core.config import settings

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[2] / "schema" / "migrations"


def main() -> int:
    baseline = "--baseline" in sys.argv
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
        if baseline:
            print(f"migrate: baseline {path.name}")
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO schema_migrations (filename) VALUES (:f)"
                ).bindparams(f=path.name))
            continue
        print(f"migrate: {path.name} ...", end=" ", flush=True)
        with engine.begin() as conn:  # transactie per file
            conn.execute(text(path.read_text()))
            conn.execute(text(
                "INSERT INTO schema_migrations (filename) VALUES (:f)"
            ).bindparams(f=path.name))
        print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
