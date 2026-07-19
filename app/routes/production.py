from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..dependencies import add_flash, current_user, require_write
from ..models import Animal, Producao
from ..security import verify_csrf_token
from ..services.audit import record_audit, snapshot
from ..utils.parsing import optional_int, parse_date, parse_decimal
from ..web import CSRFToken, DBSession, consume_form_token, issue_form_token, render

router = APIRouter(prefix="/producao", tags=["produção"])
PRODUCTION_FIELDS = ["animal_id", "data_registro", "quantidade_litros", "valor_litro", "observacoes"]


def production_or_404(db, production_id: int) -> Producao:
    item = db.scalar(select(Producao).options(joinedload(Producao.animal)).where(Producao.id == production_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro de produção não encontrado.")
    return item


def validate_form(db, form_data: dict[str, str]) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    parsed: dict = {}
    animal_id = optional_int(form_data.get("animal_id"))
    animal = db.get(Animal, animal_id) if animal_id else None
    if not animal:
        errors["animal_id"] = "Selecione um animal válido."
    else:
        parsed["animal_id"] = animal.id
    try:
        production_date = parse_date(form_data.get("data_registro"), "Data", required=True)
        if production_date and production_date > date.today():
            errors["data_registro"] = "A data da produção não pode ser futura."
        parsed["data_registro"] = production_date
    except ValueError as exc:
        errors["data_registro"] = str(exc)
    try:
        parsed["quantidade_litros"] = parse_decimal(form_data.get("quantidade_litros"), "Quantidade", positive=True, places=2)
    except ValueError as exc:
        errors["quantidade_litros"] = str(exc)
    try:
        parsed["valor_litro"] = parse_decimal(form_data.get("valor_litro"), "Valor por litro", required=False, non_negative=True, places=4)
    except ValueError as exc:
        errors["valor_litro"] = str(exc)
    parsed["observacoes"] = form_data.get("observacoes", "").strip() or None
    return parsed, errors


def form_page(request: Request, db, *, production=None, form_data=None, errors=None, status_code=200):
    animals_stmt = select(Animal).where(Animal.status == "Ativo").order_by(Animal.codigo)
    animals = list(db.scalars(animals_stmt).all())
    if production and production.animal not in animals:
        animals.append(production.animal)
    purpose = f"production:{production.id if production else 'new'}"
    return render(
        request,
        "producao/formulario.html",
        status_code=status_code,
        producao=production,
        animais=animals,
        form_data=form_data or {},
        field_errors=errors or {},
        erro="Revise os campos destacados." if errors else None,
        form_token=issue_form_token(request, purpose),
    )


@router.get("", response_class=HTMLResponse)
def list_production(
    request: Request,
    db: DBSession,
    animal_id: str | None = None,
    data_inicio: str = "",
    data_fim: str = "",
    page: int = 1,
    per_page: int = 20,
):
    current_user(request, db)
    parsed_animal_id = optional_int(animal_id)
    page = max(page, 1)
    per_page = min(max(per_page, 10), 100)
    errors = []
    try:
        start = parse_date(data_inicio, "Data inicial")
        end = parse_date(data_fim, "Data final")
        if start and end and start > end:
            raise ValueError("A data inicial não pode ser posterior à data final.")
    except ValueError as exc:
        start = end = None
        errors.append(str(exc))
    conditions = []
    if parsed_animal_id:
        conditions.append(Producao.animal_id == parsed_animal_id)
    if start:
        conditions.append(Producao.data_registro >= start)
    if end:
        conditions.append(Producao.data_registro <= end)
    total = int(db.scalar(select(func.count(Producao.id)).where(*conditions)) or 0)
    rows = db.scalars(
        select(Producao).options(joinedload(Producao.animal)).where(*conditions)
        .order_by(Producao.data_registro.desc(), Producao.id.desc())
        .offset((page - 1) * per_page).limit(per_page)
    ).all()
    animals = db.scalars(select(Animal).order_by(Animal.codigo)).all()
    pages = max((total + per_page - 1) // per_page, 1)
    return render(request, "producao/lista.html", producoes=rows, animais=animals, animal_id=parsed_animal_id, animal_id_raw=animal_id or "", data_inicio=data_inicio, data_fim=data_fim, page=page, pages=pages, per_page=per_page, total=total, errors=errors)


@router.get("/nova", response_class=HTMLResponse)
def new_form(request: Request, db: DBSession, animal_id: str | None = None):
    user = current_user(request, db)
    require_write(user)
    return form_page(request, db, form_data={"animal_id": str(optional_int(animal_id) or ""), "data_registro": date.today().isoformat()})


@router.post("/nova")
def create_production(
    request: Request,
    db: DBSession,
    csrf_token: CSRFToken,
    form_token: Annotated[str, Form()] = "",
    animal_id: Annotated[str, Form()] = "",
    data_registro: Annotated[str, Form()] = "",
    quantidade_litros: Annotated[str, Form()] = "",
    valor_litro: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    form_data = {"animal_id": animal_id, "data_registro": data_registro, "quantidade_litros": quantidade_litros, "valor_litro": valor_litro, "observacoes": observacoes}
    if not consume_form_token(request, "production:new", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou. Confira a listagem antes de tentar novamente.", "warning")
        return RedirectResponse("/producao", status_code=303)
    parsed, errors = validate_form(db, form_data)
    if errors:
        return form_page(request, db, form_data=form_data, errors=errors, status_code=400)
    item = Producao(**parsed, criado_por_id=user.id, atualizado_por_id=user.id)
    db.add(item)
    db.flush()
    record_audit(db, user=user, operation="criação", entity="produção", record_id=item.id, summary="Lançamento de produção criado.", after=snapshot(item, PRODUCTION_FIELDS))
    db.commit()
    add_flash(request, "Produção registrada com sucesso.")
    return RedirectResponse("/producao", status_code=303)


@router.get("/{production_id}/editar", response_class=HTMLResponse)
def edit_form(request: Request, production_id: int, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return form_page(request, db, production=production_or_404(db, production_id))


@router.post("/{production_id}/editar")
def update_production(
    request: Request,
    production_id: int,
    db: DBSession,
    csrf_token: CSRFToken,
    form_token: Annotated[str, Form()] = "",
    animal_id: Annotated[str, Form()] = "",
    data_registro: Annotated[str, Form()] = "",
    quantidade_litros: Annotated[str, Form()] = "",
    valor_litro: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = production_or_404(db, production_id)
    form_data = {"animal_id": animal_id, "data_registro": data_registro, "quantidade_litros": quantidade_litros, "valor_litro": valor_litro, "observacoes": observacoes}
    if not consume_form_token(request, f"production:{production_id}", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse("/producao", status_code=303)
    parsed, errors = validate_form(db, form_data)
    if errors:
        return form_page(request, db, production=item, form_data=form_data, errors=errors, status_code=400)
    before = snapshot(item, PRODUCTION_FIELDS)
    for key, value in parsed.items():
        setattr(item, key, value)
    item.atualizado_por_id = user.id
    record_audit(db, user=user, operation="edição", entity="produção", record_id=item.id, summary="Lançamento de produção atualizado.", before=before, after=snapshot(item, PRODUCTION_FIELDS))
    db.commit()
    add_flash(request, "Produção atualizada com sucesso.")
    return RedirectResponse("/producao", status_code=303)


@router.post("/{production_id}/excluir")
def delete_production(request: Request, production_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = production_or_404(db, production_id)
    before = snapshot(item, PRODUCTION_FIELDS)
    db.delete(item)
    record_audit(db, user=user, operation="exclusão", entity="produção", record_id=production_id, summary="Lançamento de produção excluído.", before=before)
    db.commit()
    add_flash(request, "Produção excluída com sucesso.")
    return RedirectResponse("/producao", status_code=303)
