from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from ..dependencies import add_flash, current_user, require_admin, require_write
from ..models import Animal, Custo, MovimentacaoAnimal, RateioCusto, Receita
from ..security import verify_csrf_token
from ..services.audit import record_audit, snapshot
from ..services.finance import (
    ALLOCATION_METHODS,
    COST_CATEGORIES,
    COST_STATUSES,
    COST_TYPES,
    PAYMENT_METHODS,
    REVENUE_CATEGORIES,
    REVENUE_STATUSES,
    apply_allocations,
    calculate_allocations,
    money,
)
from ..utils.parsing import optional_int, parse_date, parse_decimal
from ..web import CSRFToken, DBSession, consume_form_token, issue_form_token, render

router = APIRouter(tags=["financeiro"])
COST_FIELDS = ["data_competencia", "data_pagamento", "categoria", "descricao", "tipo_apropriacao", "animal_id", "quantidade", "unidade_medida", "valor_unitario", "valor_total", "fornecedor", "documento", "situacao", "forma_pagamento", "observacoes"]
REVENUE_FIELDS = ["data_competencia", "data_recebimento", "categoria", "descricao", "animal_id", "quantidade", "unidade_medida", "valor_unitario", "valor_total", "comprador", "documento", "situacao", "forma_recebimento", "observacoes"]


def parse_manual_map(raw: str) -> dict[int, Decimal]:
    result: dict[int, Decimal] = {}
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.replace("=", ":").split(":", 1)]
        if len(parts) != 2:
            raise ValueError("Use uma linha por animal no formato ID:valor.")
        animal_id = optional_int(parts[0])
        if not animal_id:
            raise ValueError("Identificador de animal inválido no rateio manual.")
        result[animal_id] = parse_decimal(parts[1], "Valor do rateio", non_negative=True) or Decimal("0")
    return result


def cost_or_404(db, cost_id: int) -> Custo:
    item = db.scalar(select(Custo).options(joinedload(Custo.animal), selectinload(Custo.rateios).joinedload(RateioCusto.animal)).where(Custo.id == cost_id))
    if not item:
        raise HTTPException(status_code=404, detail="Custo não encontrado.")
    return item


def revenue_or_404(db, revenue_id: int) -> Receita:
    item = db.scalar(select(Receita).options(joinedload(Receita.animal)).where(Receita.id == revenue_id))
    if not item:
        raise HTTPException(status_code=404, detail="Receita não encontrada.")
    return item


def cost_form_page(request: Request, db, *, cost=None, form_data=None, errors=None, status_code=200):
    animals = db.scalars(select(Animal).where(Animal.status == "Ativo").order_by(Animal.codigo)).all()
    purpose = f"cost:{cost.id if cost else 'new'}"
    return render(request, "custos/formulario.html", status_code=status_code, custo=cost, form_data=form_data or {}, field_errors=errors or {}, erro="Revise os campos destacados." if errors else None, animais=animals, categorias=COST_CATEGORIES, tipos=COST_TYPES, situacoes=COST_STATUSES, formas=PAYMENT_METHODS, metodos_rateio=ALLOCATION_METHODS, form_token=issue_form_token(request, purpose))


def validate_cost_form(db, data: dict, cost: Custo | None = None):
    errors: dict[str, str] = {}
    parsed: dict = {}
    try:
        parsed["data_competencia"] = parse_date(data.get("data_competencia"), "Data de competência", required=True)
    except ValueError as exc:
        errors["data_competencia"] = str(exc)
    try:
        parsed["data_pagamento"] = parse_date(data.get("data_pagamento"), "Data de pagamento")
    except ValueError as exc:
        errors["data_pagamento"] = str(exc)
    category = data.get("categoria", "")
    if category not in COST_CATEGORIES:
        errors["categoria"] = "Selecione uma categoria válida."
    parsed["categoria"] = category
    description = data.get("descricao", "").strip()
    if not description:
        errors["descricao"] = "A descrição é obrigatória."
    parsed["descricao"] = description
    appropriation = data.get("tipo_apropriacao", "")
    if appropriation not in COST_TYPES:
        errors["tipo_apropriacao"] = "Selecione um tipo de apropriação válido."
    parsed["tipo_apropriacao"] = appropriation
    animal_id = optional_int(data.get("animal_id"))
    if appropriation == "Custo direto de animal":
        if not animal_id or not db.get(Animal, animal_id):
            errors["animal_id"] = "O custo direto exige um animal válido."
        parsed["animal_id"] = animal_id
    else:
        parsed["animal_id"] = None
    try:
        quantity = parse_decimal(data.get("quantidade"), "Quantidade", required=False, positive=True, places=3)
        unit_value = parse_decimal(data.get("valor_unitario"), "Valor unitário", required=False, positive=True, places=4)
        informed_total = parse_decimal(data.get("valor_total"), "Valor total", positive=True, places=2)
        calculated = money(quantity * unit_value) if quantity is not None and unit_value is not None else None
        if calculated is not None and data.get("ajuste_manual") != "1":
            total = calculated
        else:
            total = informed_total
        parsed.update({"quantidade": quantity, "valor_unitario": unit_value, "valor_total": total})
    except ValueError as exc:
        errors["valor_total"] = str(exc)
    parsed["unidade_medida"] = data.get("unidade_medida", "").strip() or None
    parsed["fornecedor"] = data.get("fornecedor", "").strip() or None
    parsed["documento"] = data.get("documento", "").strip() or None
    status_value = data.get("situacao", "Pendente")
    parsed["situacao"] = status_value if status_value in COST_STATUSES else "Pendente"
    parsed["forma_pagamento"] = data.get("forma_pagamento", "").strip() or "Não informado"
    parsed["observacoes"] = data.get("observacoes", "").strip() or None
    if parsed.get("situacao") == "Pago" and not parsed.get("data_pagamento"):
        errors["data_pagamento"] = "Informe a data de pagamento para um custo pago."
    allocations = []
    if appropriation == "Custo de grupo de animais" and not errors:
        ids = [item for raw in data.get("animal_ids", []) if (item := optional_int(raw))]
        method = data.get("metodo_rateio", "")
        if method not in ALLOCATION_METHODS:
            errors["metodo_rateio"] = "Selecione um método de rateio."
        else:
            try:
                percentages = parse_manual_map(data.get("percentuais_manuais", "")) if method == "Rateio percentual manual" else None
                values = parse_manual_map(data.get("valores_manuais", "")) if method == "Rateio por valor manual" else None
                allocations = calculate_allocations(db, total=parsed["valor_total"], method=method, animal_ids=ids, competence_date=parsed["data_competencia"], percentages=percentages, values=values)
            except ValueError as exc:
                errors["rateio"] = str(exc)
    return parsed, allocations, errors


@router.get("/custos", response_class=HTMLResponse)
def list_costs(request: Request, db: DBSession, busca: str = "", categoria: str = "", animal_id: str = "", tipo: str = "", situacao: str = "", data_inicio: str = "", data_fim: str = "", page: int = 1, per_page: int = 20):
    current_user(request, db)
    conditions = []
    if busca.strip():
        term = f"%{busca.strip()}%"
        conditions.append(or_(Custo.descricao.ilike(term), Custo.fornecedor.ilike(term), Custo.documento.ilike(term)))
    if categoria in COST_CATEGORIES:
        conditions.append(Custo.categoria == categoria)
    parsed_animal = optional_int(animal_id)
    if parsed_animal:
        conditions.append(or_(Custo.animal_id == parsed_animal, Custo.rateios.any(RateioCusto.animal_id == parsed_animal)))
    if tipo in COST_TYPES:
        conditions.append(Custo.tipo_apropriacao == tipo)
    if situacao in COST_STATUSES:
        conditions.append(Custo.situacao == situacao)
    errors = []
    try:
        start = parse_date(data_inicio, "Data inicial")
        end = parse_date(data_fim, "Data final")
        if start and end and start > end:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        if start:
            conditions.append(Custo.data_competencia >= start)
        if end:
            conditions.append(Custo.data_competencia <= end)
    except ValueError as exc:
        errors.append(str(exc))
    page, per_page = max(page, 1), min(max(per_page, 10), 100)
    total = int(db.scalar(select(func.count(Custo.id)).where(*conditions)) or 0)
    rows = db.scalars(select(Custo).options(joinedload(Custo.animal), selectinload(Custo.rateios).joinedload(RateioCusto.animal)).where(*conditions).order_by(Custo.data_competencia.desc(), Custo.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    pages = max((total + per_page - 1) // per_page, 1)
    animals = db.scalars(select(Animal).order_by(Animal.codigo)).all()
    return render(request, "custos/lista.html", custos=rows, categorias=COST_CATEGORIES, tipos=COST_TYPES, situacoes=COST_STATUSES, animais=animals, busca=busca, categoria=categoria, animal_id=parsed_animal, tipo=tipo, situacao=situacao, data_inicio=data_inicio, data_fim=data_fim, page=page, pages=pages, per_page=per_page, total=total, errors=errors)


@router.get("/custos/novo", response_class=HTMLResponse)
def new_cost_form(request: Request, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return cost_form_page(request, db, form_data={"data_competencia": date.today().isoformat(), "situacao": "Pendente", "tipo_apropriacao": "Custo direto de animal"})


@router.post("/custos/novo")
def create_cost(request: Request, db: DBSession, csrf_token: CSRFToken, form_token: Annotated[str, Form()] = "", data_competencia: Annotated[str, Form()] = "", data_pagamento: Annotated[str, Form()] = "", categoria: Annotated[str, Form()] = "", descricao: Annotated[str, Form()] = "", tipo_apropriacao: Annotated[str, Form()] = "", animal_id: Annotated[str, Form()] = "", animal_ids: list[str] = Form(default=[]), quantidade: Annotated[str, Form()] = "", unidade_medida: Annotated[str, Form()] = "", valor_unitario: Annotated[str, Form()] = "", valor_total: Annotated[str, Form()] = "", ajuste_manual: Annotated[str, Form()] = "", fornecedor: Annotated[str, Form()] = "", documento: Annotated[str, Form()] = "", situacao: Annotated[str, Form()] = "Pendente", forma_pagamento: Annotated[str, Form()] = "", observacoes: Annotated[str, Form()] = "", metodo_rateio: Annotated[str, Form()] = "", percentuais_manuais: Annotated[str, Form()] = "", valores_manuais: Annotated[str, Form()] = ""):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    data = locals().copy()
    if not consume_form_token(request, "cost:new", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse("/custos", status_code=303)
    parsed, allocations, errors = validate_cost_form(db, data)
    if errors:
        return cost_form_page(request, db, form_data=data, errors=errors, status_code=400)
    item = Custo(**parsed, criado_por_id=user.id, atualizado_por_id=user.id)
    db.add(item)
    db.flush()
    if allocations:
        apply_allocations(item, allocations)
    record_audit(db, user=user, operation="criação", entity="custo", record_id=item.id, summary=f"Custo criado: {item.descricao}.", after=snapshot(item, COST_FIELDS))
    db.commit()
    add_flash(request, "Custo registrado com sucesso.")
    return RedirectResponse(f"/custos/{item.id}", status_code=303)


@router.get("/custos/{cost_id}", response_class=HTMLResponse)
def cost_detail(request: Request, cost_id: int, db: DBSession):
    current_user(request, db)
    return render(request, "custos/detalhe.html", custo=cost_or_404(db, cost_id))


@router.get("/custos/{cost_id}/editar", response_class=HTMLResponse)
def edit_cost_form(request: Request, cost_id: int, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return cost_form_page(request, db, cost=cost_or_404(db, cost_id))


@router.post("/custos/{cost_id}/editar")
def update_cost(request: Request, cost_id: int, db: DBSession, csrf_token: CSRFToken, form_token: Annotated[str, Form()] = "", data_competencia: Annotated[str, Form()] = "", data_pagamento: Annotated[str, Form()] = "", categoria: Annotated[str, Form()] = "", descricao: Annotated[str, Form()] = "", tipo_apropriacao: Annotated[str, Form()] = "", animal_id: Annotated[str, Form()] = "", animal_ids: list[str] = Form(default=[]), quantidade: Annotated[str, Form()] = "", unidade_medida: Annotated[str, Form()] = "", valor_unitario: Annotated[str, Form()] = "", valor_total: Annotated[str, Form()] = "", ajuste_manual: Annotated[str, Form()] = "", fornecedor: Annotated[str, Form()] = "", documento: Annotated[str, Form()] = "", situacao: Annotated[str, Form()] = "Pendente", forma_pagamento: Annotated[str, Form()] = "", observacoes: Annotated[str, Form()] = "", metodo_rateio: Annotated[str, Form()] = "", percentuais_manuais: Annotated[str, Form()] = "", valores_manuais: Annotated[str, Form()] = ""):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = cost_or_404(db, cost_id)
    if item.situacao == "Cancelado":
        raise HTTPException(status_code=400, detail="Custos cancelados não podem ser alterados.")
    data = locals().copy()
    if not consume_form_token(request, f"cost:{cost_id}", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse(f"/custos/{cost_id}", status_code=303)
    parsed, allocations, errors = validate_cost_form(db, data, item)
    if errors:
        return cost_form_page(request, db, cost=item, form_data=data, errors=errors, status_code=400)
    before = snapshot(item, COST_FIELDS)
    for key, value in parsed.items():
        setattr(item, key, value)
    item.atualizado_por_id = user.id
    if item.tipo_apropriacao == "Custo de grupo de animais":
        apply_allocations(item, allocations)
    else:
        item.rateios.clear()
    record_audit(db, user=user, operation="edição", entity="custo", record_id=item.id, summary=f"Custo atualizado: {item.descricao}.", before=before, after=snapshot(item, COST_FIELDS))
    db.commit()
    add_flash(request, "Custo atualizado com sucesso.")
    return RedirectResponse(f"/custos/{item.id}", status_code=303)


@router.post("/custos/{cost_id}/cancelar")
def cancel_cost(request: Request, cost_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = cost_or_404(db, cost_id)
    if item.situacao != "Cancelado":
        old = item.situacao
        item.situacao = "Cancelado"
        item.cancelado_em = datetime.now(timezone.utc).replace(tzinfo=None)
        item.cancelado_por_id = user.id
        record_audit(db, user=user, operation="cancelamento", entity="custo", record_id=item.id, summary=f"Custo cancelado: {item.descricao}.", before={"situacao": old}, after={"situacao": "Cancelado"})
        db.commit()
    add_flash(request, "Custo cancelado. O histórico foi preservado.", "warning")
    return RedirectResponse(f"/custos/{item.id}", status_code=303)


@router.post("/custos/{cost_id}/excluir")
def delete_cost(request: Request, cost_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_admin(user)
    item = cost_or_404(db, cost_id)
    if item.rateios or item.situacao != "Pendente":
        raise HTTPException(status_code=400, detail="Este custo possui rateios ou histórico financeiro e não pode ser excluído. Utilize o cancelamento.")
    before = snapshot(item, COST_FIELDS)
    db.delete(item)
    record_audit(db, user=user, operation="exclusão", entity="custo", record_id=cost_id, summary="Custo pendente sem dependências excluído.", before=before)
    db.commit()
    add_flash(request, "Custo excluído com sucesso.")
    return RedirectResponse("/custos", status_code=303)


def revenue_form_page(request: Request, db, *, revenue=None, form_data=None, errors=None, status_code=200):
    animals = db.scalars(select(Animal).where(Animal.status == "Ativo").order_by(Animal.codigo)).all()
    purpose = f"revenue:{revenue.id if revenue else 'new'}"
    return render(request, "receitas/formulario.html", status_code=status_code, receita=revenue, form_data=form_data or {}, field_errors=errors or {}, erro="Revise os campos destacados." if errors else None, animais=animals, categorias=REVENUE_CATEGORIES, situacoes=REVENUE_STATUSES, formas=PAYMENT_METHODS, form_token=issue_form_token(request, purpose))


def validate_revenue_form(db, data: dict, revenue: Receita | None = None):
    errors: dict[str, str] = {}
    parsed: dict = {}
    try:
        parsed["data_competencia"] = parse_date(data.get("data_competencia"), "Data de competência", required=True)
    except ValueError as exc:
        errors["data_competencia"] = str(exc)
    try:
        parsed["data_recebimento"] = parse_date(data.get("data_recebimento"), "Data de recebimento")
    except ValueError as exc:
        errors["data_recebimento"] = str(exc)
    category = data.get("categoria", "")
    if category not in REVENUE_CATEGORIES:
        errors["categoria"] = "Selecione uma categoria válida."
    parsed["categoria"] = category
    description = data.get("descricao", "").strip()
    if not description:
        errors["descricao"] = "A descrição é obrigatória."
    parsed["descricao"] = description
    animal_id = optional_int(data.get("animal_id"))
    if category == "Venda de animal":
        animal = db.get(Animal, animal_id) if animal_id else None
        if not animal:
            errors["animal_id"] = "A venda de animal exige um animal válido."
        elif animal.status == "Vendido" and (not revenue or revenue.animal_id != animal.id):
            errors["animal_id"] = "Este animal já está marcado como vendido."
        existing_sale = db.scalar(select(Receita.id).where(Receita.categoria == "Venda de animal", Receita.animal_id == animal_id, Receita.situacao != "Cancelado", Receita.id != (revenue.id if revenue else -1))) if animal_id else None
        if existing_sale:
            errors["animal_id"] = "Já existe uma venda não cancelada para este animal."
    elif animal_id and not db.get(Animal, animal_id):
        errors["animal_id"] = "Animal não encontrado."
    parsed["animal_id"] = animal_id
    try:
        quantity = parse_decimal(data.get("quantidade"), "Quantidade", required=False, positive=True, places=3)
        unit_value = parse_decimal(data.get("valor_unitario"), "Valor unitário", required=False, positive=True, places=4)
        informed_total = parse_decimal(data.get("valor_total"), "Valor total", positive=True, places=2)
        total = money(quantity * unit_value) if quantity is not None and unit_value is not None and data.get("ajuste_manual") != "1" else informed_total
        parsed.update({"quantidade": quantity, "valor_unitario": unit_value, "valor_total": total})
    except ValueError as exc:
        errors["valor_total"] = str(exc)
    parsed["unidade_medida"] = data.get("unidade_medida", "").strip() or ("L" if category == "Venda de leite" else None)
    parsed["comprador"] = data.get("comprador", "").strip() or None
    parsed["documento"] = data.get("documento", "").strip() or None
    status_value = data.get("situacao", "Pendente")
    parsed["situacao"] = status_value if status_value in REVENUE_STATUSES else "Pendente"
    parsed["forma_recebimento"] = data.get("forma_recebimento", "").strip() or "Não informado"
    parsed["observacoes"] = data.get("observacoes", "").strip() or None
    if parsed.get("situacao") == "Recebido" and not parsed.get("data_recebimento"):
        errors["data_recebimento"] = "Informe a data de recebimento para uma receita recebida."
    return parsed, errors


@router.get("/receitas", response_class=HTMLResponse)
def list_revenues(request: Request, db: DBSession, busca: str = "", categoria: str = "", animal_id: str = "", situacao: str = "", data_inicio: str = "", data_fim: str = "", page: int = 1, per_page: int = 20):
    current_user(request, db)
    conditions = []
    if busca.strip():
        term = f"%{busca.strip()}%"
        conditions.append(or_(Receita.descricao.ilike(term), Receita.comprador.ilike(term), Receita.documento.ilike(term)))
    if categoria in REVENUE_CATEGORIES:
        conditions.append(Receita.categoria == categoria)
    parsed_animal = optional_int(animal_id)
    if parsed_animal:
        conditions.append(Receita.animal_id == parsed_animal)
    if situacao in REVENUE_STATUSES:
        conditions.append(Receita.situacao == situacao)
    errors = []
    try:
        start = parse_date(data_inicio, "Data inicial")
        end = parse_date(data_fim, "Data final")
        if start and end and start > end:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        if start:
            conditions.append(Receita.data_competencia >= start)
        if end:
            conditions.append(Receita.data_competencia <= end)
    except ValueError as exc:
        errors.append(str(exc))
    page, per_page = max(page, 1), min(max(per_page, 10), 100)
    total = int(db.scalar(select(func.count(Receita.id)).where(*conditions)) or 0)
    rows = db.scalars(select(Receita).options(joinedload(Receita.animal)).where(*conditions).order_by(Receita.data_competencia.desc(), Receita.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    pages = max((total + per_page - 1) // per_page, 1)
    animals = db.scalars(select(Animal).order_by(Animal.codigo)).all()
    return render(request, "receitas/lista.html", receitas=rows, categorias=REVENUE_CATEGORIES, situacoes=REVENUE_STATUSES, animais=animals, busca=busca, categoria=categoria, animal_id=parsed_animal, situacao=situacao, data_inicio=data_inicio, data_fim=data_fim, page=page, pages=pages, per_page=per_page, total=total, errors=errors)


@router.get("/receitas/nova", response_class=HTMLResponse)
def new_revenue_form(request: Request, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return revenue_form_page(request, db, form_data={"data_competencia": date.today().isoformat(), "situacao": "Pendente", "categoria": "Venda de leite", "unidade_medida": "L"})


@router.post("/receitas/nova")
def create_revenue(request: Request, db: DBSession, csrf_token: CSRFToken, form_token: Annotated[str, Form()] = "", data_competencia: Annotated[str, Form()] = "", data_recebimento: Annotated[str, Form()] = "", categoria: Annotated[str, Form()] = "", descricao: Annotated[str, Form()] = "", animal_id: Annotated[str, Form()] = "", quantidade: Annotated[str, Form()] = "", unidade_medida: Annotated[str, Form()] = "", valor_unitario: Annotated[str, Form()] = "", valor_total: Annotated[str, Form()] = "", ajuste_manual: Annotated[str, Form()] = "", comprador: Annotated[str, Form()] = "", documento: Annotated[str, Form()] = "", situacao: Annotated[str, Form()] = "Pendente", forma_recebimento: Annotated[str, Form()] = "", observacoes: Annotated[str, Form()] = ""):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    data = locals().copy()
    if not consume_form_token(request, "revenue:new", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse("/receitas", status_code=303)
    parsed, errors = validate_revenue_form(db, data)
    if errors:
        return revenue_form_page(request, db, form_data=data, errors=errors, status_code=400)
    item = Receita(**parsed, criado_por_id=user.id, atualizado_por_id=user.id)
    db.add(item)
    db.flush()
    if item.categoria == "Venda de animal":
        animal = db.get(Animal, item.animal_id)
        old_status = animal.status
        animal.status = "Vendido"
        animal.atualizado_por_id = user.id
        db.add(MovimentacaoAnimal(animal_id=animal.id, data=item.data_competencia, tipo="Venda", situacao_anterior=old_status, situacao_posterior="Vendido", motivo=f"Venda registrada na receita {item.id}.", observacoes=item.observacoes, usuario_id=user.id))
    record_audit(db, user=user, operation="criação", entity="receita", record_id=item.id, summary=f"Receita criada: {item.descricao}.", after=snapshot(item, REVENUE_FIELDS))
    db.commit()
    add_flash(request, "Receita registrada com sucesso.")
    return RedirectResponse(f"/receitas/{item.id}", status_code=303)


@router.get("/receitas/{revenue_id}", response_class=HTMLResponse)
def revenue_detail(request: Request, revenue_id: int, db: DBSession):
    current_user(request, db)
    return render(request, "receitas/detalhe.html", receita=revenue_or_404(db, revenue_id))


@router.get("/receitas/{revenue_id}/editar", response_class=HTMLResponse)
def edit_revenue_form(request: Request, revenue_id: int, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return revenue_form_page(request, db, revenue=revenue_or_404(db, revenue_id))


@router.post("/receitas/{revenue_id}/editar")
def update_revenue(request: Request, revenue_id: int, db: DBSession, csrf_token: CSRFToken, form_token: Annotated[str, Form()] = "", data_competencia: Annotated[str, Form()] = "", data_recebimento: Annotated[str, Form()] = "", categoria: Annotated[str, Form()] = "", descricao: Annotated[str, Form()] = "", animal_id: Annotated[str, Form()] = "", quantidade: Annotated[str, Form()] = "", unidade_medida: Annotated[str, Form()] = "", valor_unitario: Annotated[str, Form()] = "", valor_total: Annotated[str, Form()] = "", ajuste_manual: Annotated[str, Form()] = "", comprador: Annotated[str, Form()] = "", documento: Annotated[str, Form()] = "", situacao: Annotated[str, Form()] = "Pendente", forma_recebimento: Annotated[str, Form()] = "", observacoes: Annotated[str, Form()] = ""):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = revenue_or_404(db, revenue_id)
    if item.situacao == "Cancelado":
        raise HTTPException(status_code=400, detail="Receitas canceladas não podem ser alteradas.")
    data = locals().copy()
    if not consume_form_token(request, f"revenue:{revenue_id}", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse(f"/receitas/{revenue_id}", status_code=303)
    parsed, errors = validate_revenue_form(db, data, item)
    if errors:
        return revenue_form_page(request, db, revenue=item, form_data=data, errors=errors, status_code=400)
    if item.categoria == "Venda de animal" and parsed["animal_id"] != item.animal_id:
        raise HTTPException(status_code=400, detail="O animal de uma venda confirmada não pode ser trocado. Cancele e registre uma nova venda.")
    before = snapshot(item, REVENUE_FIELDS)
    for key, value in parsed.items():
        setattr(item, key, value)
    item.atualizado_por_id = user.id
    record_audit(db, user=user, operation="edição", entity="receita", record_id=item.id, summary=f"Receita atualizada: {item.descricao}.", before=before, after=snapshot(item, REVENUE_FIELDS))
    db.commit()
    add_flash(request, "Receita atualizada com sucesso.")
    return RedirectResponse(f"/receitas/{item.id}", status_code=303)


@router.post("/receitas/{revenue_id}/cancelar")
def cancel_revenue(request: Request, revenue_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    item = revenue_or_404(db, revenue_id)
    if item.situacao != "Cancelado":
        old = item.situacao
        item.situacao = "Cancelado"
        item.cancelado_em = datetime.now(timezone.utc).replace(tzinfo=None)
        item.cancelado_por_id = user.id
        if item.categoria == "Venda de animal" and item.animal and item.animal.status == "Vendido":
            item.animal.status = "Ativo"
            db.add(MovimentacaoAnimal(animal_id=item.animal.id, data=date.today(), tipo="Reativação", situacao_anterior="Vendido", situacao_posterior="Ativo", motivo=f"Cancelamento administrativo da receita de venda {item.id}.", usuario_id=user.id))
        record_audit(db, user=user, operation="cancelamento", entity="receita", record_id=item.id, summary=f"Receita cancelada: {item.descricao}.", before={"situacao": old}, after={"situacao": "Cancelado"})
        db.commit()
    add_flash(request, "Receita cancelada. O histórico foi preservado.", "warning")
    return RedirectResponse(f"/receitas/{item.id}", status_code=303)


@router.post("/receitas/{revenue_id}/excluir")
def delete_revenue(request: Request, revenue_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_admin(user)
    item = revenue_or_404(db, revenue_id)
    if item.categoria == "Venda de animal" or item.situacao != "Pendente":
        raise HTTPException(status_code=400, detail="Esta receita possui histórico e não pode ser excluída. Utilize o cancelamento.")
    before = snapshot(item, REVENUE_FIELDS)
    db.delete(item)
    record_audit(db, user=user, operation="exclusão", entity="receita", record_id=revenue_id, summary="Receita pendente sem dependências excluída.", before=before)
    db.commit()
    add_flash(request, "Receita excluída com sucesso.")
    return RedirectResponse("/receitas", status_code=303)
