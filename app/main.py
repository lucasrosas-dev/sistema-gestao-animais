from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import SessionLocal, engine
from .models import User
from .routes import admin, animals, auth, dashboard, finance, production, reports
from .schema import upgrade_database
from .security import AuthGateMiddleware, SecurityHeadersMiddleware, hash_password
from .web import BASE_DIR, render

settings = get_settings()
logger = logging.getLogger("sga")
logging.basicConfig(level=logging.INFO if settings.is_production else logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def ensure_admin_user() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            db.add(User(
                username=settings.admin_username,
                name="Administrador",
                role="Administrador",
                password_hash=hash_password(settings.admin_password),
                is_active=True,
                must_change_password=settings.uses_development_credentials,
                session_version=1,
            ))
            db.commit()
            return
        changed = False
        if not user.role:
            user.role = "Administrador"
            changed = True
        if settings.reset_admin_password:
            user.password_hash = hash_password(settings.admin_password)
            user.is_active = True
            user.must_change_password = False
            user.session_version = (user.session_version or 1) + 1
            changed = True
        if changed:
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()
    logger.info("Aplicando migrations")
    upgrade_database(engine)
    ensure_admin_user()
    logger.info("Aplicação pronta")
    yield


middleware = [
    Middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="sga_session",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.cookie_secure,
    ),
    Middleware(AuthGateMiddleware),
    Middleware(SecurityHeadersMiddleware, production=settings.is_production),
]

APP_VERSION = "1.0.0"

app = FastAPI(title="Sistema de Gestão de Animais", version=APP_VERSION, lifespan=lifespan, middleware=middleware, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
for router in [auth.router, dashboard.router, animals.router, production.router, finance.router, reports.router, admin.router]:
    app.include_router(router)


def render_error(request: Request, code: int, title: str, message: str):
    return render(request, "errors/error.html", status_code=code, status_code_value=code, error_title=title, error_message=message)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    logger.warning("Validação recusada em %s %s", request.method, request.url.path)
    missing_csrf = any(
        error.get("type") == "missing" and "csrf_token" in tuple(error.get("loc", ()))
        for error in exc.errors()
    )
    if missing_csrf:
        return render_error(request, 403, "Acesso negado", "A validação de segurança do formulário falhou. Atualize a página e tente novamente.")
    return render_error(request, 422, "Dados inválidos", "Não foi possível processar os dados enviados. Revise os campos e tente novamente.")


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path in {"/health", "/ready"}:
        return JSONResponse(status_code=exc.status_code, content={"status": "error"})
    logger.warning(
        "HTTP %s em %s %s (usuario=%s, perfil=%s, detalhe=%s)",
        exc.status_code,
        request.method,
        request.url.path,
        request.session.get("username"),
        request.session.get("role"),
        exc.detail,
    )
    titles = {400: "Operação inválida", 401: "Sessão inválida", 403: "Acesso negado", 404: "Página não encontrada", 405: "Operação não permitida", 422: "Dados inválidos", 429: "Muitas tentativas"}
    messages = {
        400: "A solicitação não pôde ser concluída.", 401: "Sua sessão expirou. Entre novamente.",
        403: "Seu perfil não possui permissão para esta operação.", 404: "O endereço ou registro solicitado não foi encontrado.",
        405: "O método utilizado não é permitido nesta página.", 422: "Revise os dados informados e tente novamente.",
        429: "O limite de tentativas foi atingido. Aguarde antes de tentar novamente.",
    }
    message = messages.get(exc.status_code, "Não foi possível concluir a solicitação.")
    if exc.status_code == 403 and isinstance(exc.detail, str):
        message = exc.detail
    return render_error(request, exc.status_code, titles.get(exc.status_code, "Erro"), message)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    logger.exception("Falha de banco em %s %s", request.method, request.url.path)
    return render_error(request, 500, "Falha temporária", "O banco de dados está temporariamente indisponível. Tente novamente em instantes.")


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception):
    logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return render_error(request, 500, "Erro interno", "Ocorreu uma falha inesperada. Nenhum detalhe técnico foi exibido.")


@app.get("/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "version": APP_VERSION}
    except SQLAlchemyError:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "error", "database": "unavailable", "version": APP_VERSION})


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "version": APP_VERSION}
    except SQLAlchemyError:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "error", "database": "unavailable"})
