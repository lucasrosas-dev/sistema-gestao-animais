from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.schema import upgrade_database  # noqa: E402


def main() -> None:
    settings = get_settings()
    settings.validate()
    upgrade_database(engine)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    database_kind = "PostgreSQL" if "postgresql" in settings.database_url else "SQLite"
    print(f"Configuração e migrações válidas. Ambiente: {settings.app_env}. Banco: {database_kind}.")


if __name__ == "__main__":
    main()
