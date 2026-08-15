"""Migration runner.

v1 uses a pragmatic two-layer approach documented in IMPLEMENTATION_PLAN.md:
1. `migrations/*.sql` — human-readable, ordered SQL files that document schema history
   and are the source of truth for a future Alembic migration to Postgres.
2. `Base.metadata.create_all()` — actually creates/updates the SQLite schema at runtime
   for v1, since SQLite's ALTER TABLE support is limited and the schema is still evolving.

This keeps the documented migration trail (section 28: "Utilizar migrations") without
taking on Alembic's overhead before the schema stabilizes.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from eci.config import PROJECT_ROOT
from eci.database.engine import get_engine, init_db

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def list_migrations() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_migrations() -> list[str]:
    """Runs schema creation (create_all) then applies any raw SQL migrations that are
    additive/idempotent (e.g. seed data, indices not expressible in the ORM). Returns the
    list of migration filenames applied."""
    init_db()
    applied = []
    engine = get_engine()
    with engine.begin() as conn:
        for path in list_migrations():
            sql = path.read_text(encoding="utf-8")
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))
            applied.append(path.name)
    return applied
