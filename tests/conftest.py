from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

TEST_DIR = Path(tempfile.mkdtemp(prefix="sga_v2_test_"))
DB_PATH = TEST_DIR / "test.db"
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{DB_PATH}",
    "SECRET_KEY": "test-secret-key-with-more-than-thirty-two-characters",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "test-password-123",
    "COOKIE_SECURE": "false",
    "RESET_ADMIN_PASSWORD": "false",
})

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app
from app.database import SessionLocal
from app.models import AuditLog, BackupRecord, Custo, EventoAnimal, MovimentacaoAnimal, Producao, RateioCusto, Receita, User, Animal
from app.security import hash_password


def hidden(html: str, name: str) -> str:
    patterns = [
        rf'name=["\']{re.escape(name)}["\'][^>]*value=["\']([^"\']*)',
        rf'value=["\']([^"\']*)["\'][^>]*name=["\']{re.escape(name)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    raise AssertionError(f"Campo oculto {name!r} não encontrado")


def reset_database() -> None:
    with SessionLocal() as db:
        for model in [RateioCusto, Custo, Receita, EventoAnimal, MovimentacaoAnimal, Producao, AuditLog, BackupRecord, Animal]:
            db.execute(delete(model))
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is None:
            admin = User(username="admin", name="Administrador", role="Administrador", password_hash=hash_password("test-password-123"), is_active=True, must_change_password=False, session_version=1)
            db.add(admin)
        else:
            db.execute(delete(User).where(User.id != admin.id))
            admin.name = "Administrador"
            admin.role = "Administrador"
            admin.password_hash = hash_password("test-password-123")
            admin.is_active = True
            admin.must_change_password = False
            admin.session_version = 1
        db.commit()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        reset_database()
        test_client.cookies.clear()
        yield test_client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def login(client: TestClient, username: str = "admin", password: str = "test-password-123"):
    page = client.get("/login")
    return client.post("/login", data={"username": username, "password": password, "csrf_token": hidden(page.text, "csrf_token"), "next": "/"}, follow_redirects=False)


def form_payload(client: TestClient, path: str, data: dict | None = None) -> dict:
    page = client.get(path)
    assert page.status_code == 200, page.text
    payload = dict(data or {})
    payload["csrf_token"] = hidden(page.text, "csrf_token")
    try:
        payload["form_token"] = hidden(page.text, "form_token")
    except AssertionError:
        pass
    return payload


def create_animal(client: TestClient, code: str, *, sex: str = "Fêmea", category: str = "Vaca", status: str = "Ativo", **extra) -> int:
    data = {
        "codigo": code,
        "sexo": sex,
        "categoria": category,
        "status": status,
        "origem": extra.pop("origem", "Compra"),
        "data_aquisicao": extra.pop("data_aquisicao", "2026-07-01"),
        **extra,
    }
    response = client.post("/animais/novo", data=form_payload(client, "/animais/novo", data), follow_redirects=False)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rstrip("/").split("/")[-1])


def create_production(client: TestClient, animal_id: int, *, quantity: str = "10,50", production_date: str = "2026-07-10", value: str = "2,40") -> int:
    data = {"animal_id": str(animal_id), "data_registro": production_date, "quantidade_litros": quantity, "valor_litro": value, "observacoes": "Teste"}
    response = client.post("/producao/nova", data=form_payload(client, f"/producao/nova?animal_id={animal_id}", data), follow_redirects=False)
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        return db.scalars(select(Producao).order_by(Producao.id.desc())).first().id


def create_cost(client: TestClient, data: dict) -> int:
    response = client.post("/custos/novo", data=form_payload(client, "/custos/novo", data), follow_redirects=False)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rstrip("/").split("/")[-1])


def create_revenue(client: TestClient, data: dict) -> int:
    response = client.post("/receitas/nova", data=form_payload(client, "/receitas/nova", data), follow_redirects=False)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rstrip("/").split("/")[-1])
