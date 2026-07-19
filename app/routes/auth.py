from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from ..dependencies import add_flash, current_user
from ..models import User
from ..security import LoginAttemptLimiter, hash_password, safe_next_url, verify_csrf_token, verify_password
from ..web import CSRFToken, DBSession, render

router = APIRouter()
login_limiter = LoginAttemptLimiter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "auth/login.html", erro=None, next_url=safe_next_url(next))


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: DBSession,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: CSRFToken,
    next: Annotated[str, Form()] = "/",
):
    verify_csrf_token(request, csrf_token)
    client_key = request.client.host if request.client else "desconhecido"
    if login_limiter.is_blocked(client_key):
        return render(request, "auth/login.html", status_code=429, erro="Muitas tentativas inválidas. Aguarde 15 minutos e tente novamente.", next_url=safe_next_url(next))
    normalized = username.strip().lower()
    user = db.scalar(select(User).where(User.username == normalized))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        login_limiter.register_failure(client_key)
        return render(request, "auth/login.html", status_code=401, erro="Usuário ou senha inválidos.", next_url=safe_next_url(next))
    login_limiter.clear(client_key)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    request.session.clear()
    request.session.update({
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "session_version": user.session_version,
        "must_change_password": bool(user.must_change_password),
    })
    destination = "/conta/senha" if user.must_change_password else safe_next_url(next)
    return RedirectResponse(destination, status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/conta/senha", response_class=HTMLResponse)
def change_password_form(request: Request):
    return render(request, "conta/senha.html", erro=None)


@router.post("/conta/senha", response_class=HTMLResponse)
def change_password(
    request: Request,
    db: DBSession,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    csrf_token: CSRFToken,
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    error = None
    if not verify_password(current_password, user.password_hash):
        error = "A senha atual está incorreta."
    elif len(new_password) < 8:
        error = "A nova senha deve ter pelo menos oito caracteres."
    elif not new_password.strip():
        error = "A senha não pode ser composta apenas por espaços."
    elif new_password.lower() == user.username.lower():
        error = "A senha não pode ser igual ao login."
    elif new_password != confirm_password:
        error = "A confirmação não corresponde à nova senha."
    elif verify_password(new_password, user.password_hash):
        error = "A nova senha deve ser diferente da senha atual."
    if error:
        return render(request, "conta/senha.html", status_code=400, erro=error)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.session_version += 1
    db.commit()
    request.session.clear()
    add_flash(request, "Senha alterada. Entre novamente com a nova senha.", "success")
    return RedirectResponse("/login", status_code=303)
