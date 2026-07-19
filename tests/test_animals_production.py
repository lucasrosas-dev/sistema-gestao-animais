from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Animal, AuditLog, EventoAnimal, MovimentacaoAnimal, Producao
from conftest import create_animal, create_production, form_payload, hidden, login


def test_animal_create_and_initial_movement(client):
    login(client)
    animal_id = create_animal(client, "A-001", nome="Aurora", raca="Girolando")
    with SessionLocal() as db:
        animal = db.get(Animal, animal_id)
        assert animal.nome == "Aurora"
        assert animal.categoria == "Vaca"
        movement = db.scalar(select(MovimentacaoAnimal).where(MovimentacaoAnimal.animal_id == animal_id))
        assert movement.tipo == "Entrada por compra"
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entidade == "animal")) == 1


def test_animal_duplicate_code_is_rejected_preserving_values(client):
    login(client)
    create_animal(client, "DUP-01")
    data = {"codigo": " DUP-01 ", "nome": "Preservado", "sexo": "Fêmea", "categoria": "Vaca", "status": "Ativo", "origem": "Compra", "data_aquisicao": "2026-07-01"}
    response = client.post("/animais/novo", data=form_payload(client, "/animais/novo", data))
    assert response.status_code == 400
    assert "já cadastrado" in response.text
    assert "Preservado" in response.text


def test_animal_empty_code_future_birth_and_date_order(client):
    login(client)
    base = {"codigo": "", "sexo": "Fêmea", "categoria": "Vaca", "status": "Ativo", "origem": "Compra", "data_aquisicao": "2026-07-01"}
    empty = client.post("/animais/novo", data=form_payload(client, "/animais/novo", base))
    assert empty.status_code == 400 and "obrigatório" in empty.text
    future = {**base, "codigo": "FUT-01", "data_nascimento": "2099-01-01"}
    response = client.post("/animais/novo", data=form_payload(client, "/animais/novo", future))
    assert response.status_code == 400 and "futura" in response.text
    order = {**base, "codigo": "ORD-01", "data_nascimento": "2026-07-15", "data_aquisicao": "2026-07-01"}
    response = client.post("/animais/novo", data=form_payload(client, "/animais/novo", order))
    assert response.status_code == 400 and "posterior" in response.text


def test_animal_filters_and_case_insensitive_search(client):
    login(client)
    create_animal(client, "BX-01", nome="Estrela", category="Bezerra")
    create_animal(client, "VC-01", nome="Lua", category="Vaca", status="Inativo")
    response = client.get("/animais?busca=estrela&categoria=Bezerra&mostrar_todos=1")
    assert response.status_code == 200
    assert "BX-01" in response.text and "VC-01" not in response.text
    default = client.get("/animais")
    assert "VC-01" not in default.text


def test_genealogy_and_self_relationship_validation(client):
    login(client)
    mother = create_animal(client, "MAE-01", sex="Fêmea")
    father = create_animal(client, "PAI-01", sex="Macho", category="Touro")
    child = create_animal(client, "FILHO-01", sex="Macho", category="Bezerro", mae_id=str(mother), pai_id=str(father), origem="Nascimento")
    detail = client.get(f"/animais/{child}")
    assert "MAE-01" in detail.text and "PAI-01" in detail.text
    page = client.get(f"/animais/{child}/editar")
    payload = {
        "csrf_token": hidden(page.text, "csrf_token"), "form_token": hidden(page.text, "form_token"),
        "codigo": "FILHO-01", "sexo": "Macho", "categoria": "Bezerro", "status": "Ativo", "origem": "Nascimento",
        "data_aquisicao": "2026-07-01", "mae_id": str(child),
    }
    response = client.post(f"/animais/{child}/editar", data=payload)
    assert response.status_code == 400
    assert "não pode ser pai ou mãe de si próprio" in response.text


def test_status_change_creates_movement(client):
    login(client)
    animal_id = create_animal(client, "STATUS-01")
    detail = client.get(f"/animais/{animal_id}")
    response = client.post(f"/animais/{animal_id}/situacao", data={"csrf_token": hidden(detail.text, "csrf_token"), "situacao": "Vendido", "data_movimentacao": "2026-07-10", "motivo": "Venda confirmada"}, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(Animal, animal_id).status == "Vendido"
        assert db.scalar(select(MovimentacaoAnimal).where(MovimentacaoAnimal.animal_id == animal_id, MovimentacaoAnimal.tipo == "Venda"))


def test_event_and_parto_create_descendant_without_duplication(client):
    login(client)
    mother = create_animal(client, "PARTO-MAE")
    father = create_animal(client, "PARTO-PAI", sex="Macho", category="Touro")
    data = {"data": "2026-07-10", "grupo": "Reprodutivo", "tipo": "Parto", "titulo": "Parto normal", "pai_id": str(father), "descendentes": "B-001;Estrela;Fêmea\nB-002;Trovão;Macho"}
    response = client.post(f"/animais/{mother}/eventos/novo", data=form_payload(client, f"/animais/{mother}/eventos/novo", data), follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        children = db.scalars(select(Animal).where(Animal.mae_id == mother).order_by(Animal.codigo)).all()
        assert [item.codigo for item in children] == ["B-001", "B-002"]
        assert all(db.scalar(select(MovimentacaoAnimal.id).where(MovimentacaoAnimal.animal_id == item.id)) for item in children)
        assert db.scalar(select(func.count(EventoAnimal.id)).where(EventoAnimal.animal_id == mother)) == 1


def test_delete_with_history_inactivates_and_without_related_is_safely_handled(client):
    login(client)
    animal_id = create_animal(client, "DEL-HIST")
    create_production(client, animal_id)
    page = client.get(f"/animais/{animal_id}")
    response = client.post(f"/animais/{animal_id}/excluir", data={"csrf_token": hidden(page.text, "csrf_token")}, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(Animal, animal_id).status == "Inativo"
        assert db.scalar(select(func.count(Producao.id)).where(Producao.animal_id == animal_id)) == 1


def test_production_query_parameter_variations(client):
    login(client)
    animal = create_animal(client, "P-FILTER")
    other = create_animal(client, "P-OTHER")
    create_production(client, animal, quantity="11")
    create_production(client, other, quantity="22")
    for path in ["/producao", "/producao?animal_id=", "/producao?animal_id=abc"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "Dados inválidos" not in response.text
    filtered = client.get(f"/producao?animal_id={animal}")
    assert filtered.status_code == 200
    assert "11,00 L" in filtered.text and "22,00 L" not in filtered.text
    assert "1 registro(s) encontrado(s)" in filtered.text


def test_production_create_edit_delete(client):
    login(client)
    animal = create_animal(client, "P-CRUD")
    production = create_production(client, animal)
    edit_data = {"animal_id": str(animal), "data_registro": "2026-07-11", "quantidade_litros": "15,75", "valor_litro": "2,50", "observacoes": "Editado"}
    response = client.post(f"/producao/{production}/editar", data=form_payload(client, f"/producao/{production}/editar", edit_data), follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert str(db.get(Producao, production).quantidade_litros) == "15.75"
    page = client.get("/producao")
    response = client.post(f"/producao/{production}/excluir", data={"csrf_token": hidden(page.text, "csrf_token")}, follow_redirects=False)
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(Producao, production) is None


def test_negative_zero_future_production_preserves_form(client):
    login(client)
    animal = create_animal(client, "P-INVALID")
    for quantity in ["-5", "0"]:
        data = {"animal_id": str(animal), "data_registro": "2026-07-10", "quantidade_litros": quantity, "valor_litro": "2,30", "observacoes": "Manter texto"}
        response = client.post("/producao/nova", data=form_payload(client, f"/producao/nova?animal_id={animal}", data))
        assert response.status_code == 400
        assert "Manter texto" in response.text
    future = {"animal_id": str(animal), "data_registro": "2099-01-01", "quantidade_litros": "5", "valor_litro": "2"}
    response = client.post("/producao/nova", data=form_payload(client, f"/producao/nova?animal_id={animal}", future))
    assert response.status_code == 400 and "futura" in response.text


def test_duplicate_submission_token_prevents_second_insert(client):
    login(client)
    animal = create_animal(client, "P-DUP")
    page = client.get(f"/producao/nova?animal_id={animal}")
    payload = {"animal_id": str(animal), "data_registro": "2026-07-10", "quantidade_litros": "5", "valor_litro": "2", "csrf_token": hidden(page.text, "csrf_token"), "form_token": hidden(page.text, "form_token")}
    first = client.post("/producao/nova", data=payload, follow_redirects=False)
    second = client.post("/producao/nova", data=payload, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Producao.id))) == 1
