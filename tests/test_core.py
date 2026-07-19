from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog, User
from app.security import hash_password, verify_password
from conftest import hidden, login


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok", "version": "1.0.0"}
    assert client.get("/ready").json()["database"] == "ok"


def test_protected_route_redirects_to_login(client):
    response = client.get("/animais", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_logout_and_generic_failure(client):
    bad_page = client.get("/login")
    bad = client.post("/login", data={"username": "naoexiste", "password": "errada", "csrf_token": hidden(bad_page.text, "csrf_token")})
    assert bad.status_code == 401
    assert "Usuário ou senha inválidos" in bad.text
    assert "não existe" not in bad.text
    assert login(client).status_code == 303
    home = client.get("/")
    token = hidden(home.text, "csrf_token")
    out = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert out.status_code == 303
    assert client.get("/animais", follow_redirects=False).status_code == 303


def test_invalid_and_missing_csrf_are_friendly(client):
    login(client)
    response = client.post("/animais/novo", data={"codigo": "X", "sexo": "Fêmea"})
    assert response.status_code == 403
    assert "Acesso negado" in response.text
    assert "traceback" not in response.text.lower()


def test_error_pages_do_not_expose_internal_details(client):
    login(client)
    not_found = client.get("/rota-inexistente")
    assert not_found.status_code == 404
    assert "Página não encontrada" in not_found.text
    invalid_method = client.put("/animais")
    assert invalid_method.status_code == 405
    for response in (not_found, invalid_method):
        text = response.text.lower()
        assert "traceback" not in text
        assert "sqlalchemy" not in text


def test_password_hash_and_comparison():
    encoded = hash_password("Senha forte 123")
    assert encoded != "Senha forte 123"
    assert verify_password("Senha forte 123", encoded)
    assert not verify_password("outra", encoded)


def test_change_password_invalidates_session(client):
    login(client)
    page = client.get("/conta/senha")
    response = client.post("/conta/senha", data={"current_password": "test-password-123", "new_password": "nova-senha-123", "confirm_password": "nova-senha-123", "csrf_token": hidden(page.text, "csrf_token")}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/painel"
    assert client.get("/", follow_redirects=False).status_code == 303
    assert login(client, password="nova-senha-123").status_code == 303


def test_operator_is_redirected_to_dashboard_after_forced_password_change(client):
    with SessionLocal() as db:
        user = User(
            username="operador",
            name="Operador",
            role="Operador",
            password_hash=hash_password("senha-temporaria-123"),
            is_active=True,
            must_change_password=True,
            session_version=1,
        )
        db.add(user)
        db.commit()

    login_page = client.get("/login?next=/admin/usuarios")
    first_login = client.post(
        "/login",
        data={
            "username": "operador",
            "password": "senha-temporaria-123",
            "csrf_token": hidden(login_page.text, "csrf_token"),
            "next": "/admin/usuarios",
        },
        follow_redirects=False,
    )
    assert first_login.status_code == 303
    assert first_login.headers["location"] == "/conta/senha"

    password_page = client.get("/conta/senha")
    changed = client.post(
        "/conta/senha",
        data={
            "current_password": "senha-temporaria-123",
            "new_password": "senha-definitiva-123",
            "confirm_password": "senha-definitiva-123",
            "csrf_token": hidden(password_page.text, "csrf_token"),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == "/login?next=/painel"

    relogin_page = client.get("/login?next=/admin/usuarios")
    relogin = client.post(
        "/login",
        data={
            "username": "operador",
            "password": "senha-definitiva-123",
            "csrf_token": hidden(relogin_page.text, "csrf_token"),
            "next": "/admin/usuarios",
        },
        follow_redirects=False,
    )
    assert relogin.status_code == 303
    assert relogin.headers["location"] == "/painel"
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == "/painel"
    dashboard = client.get("/painel")
    assert dashboard.status_code == 200
    assert "Acesso negado" not in dashboard.text


def test_password_policy_rejects_login_as_password(client):
    login(client)
    page = client.get("/conta/senha")
    response = client.post("/conta/senha", data={"current_password": "test-password-123", "new_password": "admin", "confirm_password": "admin", "csrf_token": hidden(page.text, "csrf_token")})
    assert response.status_code == 400
    assert "pelo menos oito" in response.text or "igual ao login" in response.text


def test_inactive_user_cannot_login(client):
    with SessionLocal() as db:
        db.add(User(username="inativo", name="Inativo", role="Consulta", password_hash=hash_password("senha-inativo-123"), is_active=False, must_change_password=False, session_version=1))
        db.commit()
    response = login(client, "inativo", "senha-inativo-123")
    assert response.status_code == 401


def test_security_headers(client):
    response = client.get("/login")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors" in response.headers["content-security-policy"]


def test_admin_can_reset_user_password_from_form(client):
    with SessionLocal() as db:
        user = User(
            username="taty",
            name="Taty",
            role="Operador",
            password_hash=hash_password("senha-antiga-123"),
            is_active=True,
            must_change_password=False,
            session_version=1,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    assert login(client).status_code == 303
    listing = client.get("/admin/usuarios")
    reset_path = f"/admin/usuarios/{user_id}/redefinir-senha"
    assert listing.status_code == 200
    assert f'href="{reset_path}"' in listing.text

    page = client.get(reset_path)
    assert page.status_code == 200
    assert 'name="new_password"' in page.text
    assert 'name="confirm_password"' in page.text

    response = client.post(
        reset_path,
        data={
            "new_password": "nova-senha-123",
            "confirm_password": "nova-senha-123",
            "csrf_token": hidden(page.text, "csrf_token"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/usuarios"

    with SessionLocal() as db:
        updated = db.get(User, user_id)
        assert verify_password("nova-senha-123", updated.password_hash)
        assert updated.must_change_password is True
        assert updated.session_version == 2
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entidade == "usuário",
                AuditLog.registro_id == str(user_id),
                AuditLog.operacao == "redefinição de senha",
            )
        )
        assert audit is not None


def test_reset_password_form_shows_validation_error(client):
    with SessionLocal() as db:
        user = User(
            username="operador",
            name="Operador",
            role="Operador",
            password_hash=hash_password("senha-antiga-123"),
            is_active=True,
            must_change_password=False,
            session_version=1,
        )
        db.add(user)
        db.commit()
        user_id = user.id

    login(client)
    reset_path = f"/admin/usuarios/{user_id}/redefinir-senha"
    page = client.get(reset_path)
    response = client.post(
        reset_path,
        data={
            "new_password": "nova-senha-123",
            "confirm_password": "senha-diferente-123",
            "csrf_token": hidden(page.text, "csrf_token"),
        },
    )
    assert response.status_code == 400
    assert "confirmação da senha não corresponde" in response.text

    with SessionLocal() as db:
        unchanged = db.get(User, user_id)
        assert verify_password("senha-antiga-123", unchanged.password_hash)
        assert unchanged.session_version == 1
