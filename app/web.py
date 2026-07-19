from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .dependencies import pop_flashes
from .security import get_csrf_token
from .utils.formatting import age_label, br_currency, br_date, br_datetime, br_liters, br_number, br_percent

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update({
    "decimal_br": br_number,
    "currency_br": br_currency,
    "liters_br": br_liters,
    "percent_br": br_percent,
    "date_br": br_date,
    "datetime_br": br_datetime,
    "age_label": age_label,
})

DBSession = Annotated[Session, Depends(get_db)]
CSRFToken = Annotated[str, Form()]


def template_context(request: Request, **extra):
    context = {
        "request": request,
        "csrf_token": get_csrf_token(request),
        "current_username": request.session.get("username"),
        "current_user_name": request.session.get("display_name") or request.session.get("username"),
        "current_role": request.session.get("role"),
        "must_change_password": bool(request.session.get("must_change_password")),
        "is_production": settings.is_production,
        "flashes": pop_flashes(request),
        "current_path": request.url.path,
    }
    context.update(extra)
    return context


def render(request: Request, template_name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=template_context(request, **context),
        status_code=status_code,
    )


def issue_form_token(request: Request, purpose: str) -> str:
    token = secrets.token_urlsafe(24)
    tokens = dict(request.session.get("form_tokens", {}))
    tokens[purpose] = token
    request.session["form_tokens"] = tokens
    return token


def consume_form_token(request: Request, purpose: str, submitted: str | None) -> bool:
    tokens = dict(request.session.get("form_tokens", {}))
    expected = tokens.pop(purpose, None)
    request.session["form_tokens"] = tokens
    return bool(expected and submitted and secrets.compare_digest(expected, submitted))
