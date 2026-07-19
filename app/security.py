from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock
from urllib.parse import quote

from fastapi import Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

PBKDF2_ITERATIONS = 600_000
PUBLIC_PATHS = {"/login", "/health", "/ready"}
PUBLIC_PREFIXES = ("/static/",)
PASSWORD_CHANGE_PATHS = {"/conta/senha", "/logout", "/health", "/ready"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf_token(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not submitted or not hmac.compare_digest(expected, submitted):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token de segurança inválido. Atualize a página e tente novamente.")


def safe_next_url(value: str | None, default: str = "/") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    return value


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
        if not is_public and not request.session.get("user_id"):
            if request.method == "GET":
                destination = path
                if request.url.query:
                    destination += "?" + request.url.query
                return RedirectResponse(f"/login?next={quote(destination, safe='')}", status_code=303)
            return RedirectResponse("/login", status_code=303)

        if (
            request.session.get("user_id")
            and request.session.get("must_change_password")
            and path not in PASSWORD_CHANGE_PATHS
            and not any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
        ):
            return RedirectResponse("/conta/senha", status_code=303)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, production: bool = False):
        super().__init__(app)
        self.production = production

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if self.production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class LoginAttemptLimiter:
    """Limitador simples por processo para reduzir tentativas automatizadas."""

    def __init__(self, max_attempts: int = 5, window_minutes: int = 15):
        self.max_attempts = max_attempts
        self.window = timedelta(minutes=window_minutes)
        self._attempts: dict[str, list[datetime]] = {}
        self._lock = Lock()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _active_attempts(self, key: str) -> list[datetime]:
        cutoff = self._now() - self.window
        return [item for item in self._attempts.get(key, []) if item >= cutoff]

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            active = self._active_attempts(key)
            self._attempts[key] = active
            return len(active) >= self.max_attempts

    def register_failure(self, key: str) -> None:
        with self._lock:
            active = self._active_attempts(key)
            active.append(self._now())
            self._attempts[key] = active

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
