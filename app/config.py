from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEV_SECRET = "desenvolvimento-local-troque-esta-chave-antes-de-publicar"
DEV_ADMIN_PASSWORD = "admin12345"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    secret_key: str
    admin_username: str
    admin_password: str
    reset_admin_password: bool
    session_max_age: int
    cookie_secure: bool

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def uses_development_credentials(self) -> bool:
        return (
            self.admin_username == "admin"
            and self.admin_password == DEV_ADMIN_PASSWORD
        )

    def validate(self) -> None:
        errors: list[str] = []
        if self.session_max_age < 900:
            errors.append("SESSION_MAX_AGE deve ser de pelo menos 900 segundos.")

        if self.is_production:
            if not self.database_url.lower().startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
                errors.append("Em produção, DATABASE_URL deve apontar para PostgreSQL.")
            if not self.secret_key or self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                errors.append("SECRET_KEY deve ser exclusiva e ter pelo menos 32 caracteres.")
            if not self.admin_username.strip():
                errors.append("ADMIN_USERNAME é obrigatório em produção.")
            if len(self.admin_password) < 10 or self.admin_password == DEV_ADMIN_PASSWORD:
                errors.append("ADMIN_PASSWORD deve ter pelo menos 10 caracteres e não pode ser a senha local padrão.")

        if errors:
            raise RuntimeError("Configuração inválida:\n- " + "\n- ".join(errors))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    local_db = BASE_DIR / "data" / "sistema_animais.db"
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    session_max_age_raw = os.getenv("SESSION_MAX_AGE", "28800")
    try:
        session_max_age = int(session_max_age_raw)
    except ValueError as exc:
        raise RuntimeError("SESSION_MAX_AGE deve ser um número inteiro.") from exc

    return Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{local_db}").strip(),
        secret_key=os.getenv("SECRET_KEY", DEV_SECRET),
        admin_username=os.getenv("ADMIN_USERNAME", "admin").strip().lower(),
        admin_password=os.getenv("ADMIN_PASSWORD", DEV_ADMIN_PASSWORD),
        reset_admin_password=_as_bool(os.getenv("RESET_ADMIN_PASSWORD"), False),
        session_max_age=session_max_age,
        cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), app_env == "production"),
    )
