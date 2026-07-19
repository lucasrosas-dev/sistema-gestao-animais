from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from .models import User


def current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    if request.session.get("session_version") != user.session_version:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada. Entre novamente.")
    return user


def require_roles(user: User, roles: Iterable[str]) -> None:
    allowed = set(roles)
    if user.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil não possui permissão para esta operação.")


def require_write(user: User) -> None:
    require_roles(user, {"Administrador", "Operador"})


def require_admin(user: User) -> None:
    require_roles(user, {"Administrador"})


def add_flash(request: Request, message: str, category: str = "success") -> None:
    flashes = list(request.session.get("flashes", []))
    flashes.append({"message": message, "category": category})
    request.session["flashes"] = flashes[-5:]


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flashes", [])
