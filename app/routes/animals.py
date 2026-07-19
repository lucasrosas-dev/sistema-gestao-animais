from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from ..dependencies import add_flash, current_user, require_write
from ..models import Animal, Custo, EventoAnimal, MovimentacaoAnimal, Producao, RateioCusto, Receita
from ..security import verify_csrf_token
from ..services.audit import record_audit, snapshot
from ..utils.parsing import optional_int, parse_date
from ..web import CSRFToken, DBSession, consume_form_token, issue_form_token, render

router = APIRouter(prefix="/animais", tags=["animais"])
SEXES = ["Fêmea", "Macho", "Não informado"]
ORIGINS = ["Nascimento", "Compra", "Transferência", "Outro", "Não informado"]
CATEGORIES = ["Bezerro", "Bezerra", "Novilha", "Vaca", "Touro", "Garrote", "Outro", "Não informado"]
STATUSES = ["Ativo", "Vendido", "Falecido", "Transferido", "Inativo"]
EVENT_GROUPS = {
    "Produtivo": ["Início de lactação", "Encerramento de lactação", "Secagem", "Alteração de categoria produtiva", "Outro evento produtivo"],
    "Reprodutivo": ["Cobertura", "Inseminação", "Diagnóstico de gestação", "Parto", "Aborto", "Outro evento reprodutivo"],
    "Sanitário": ["Vacinação", "Aplicação de medicamento", "Consulta veterinária", "Tratamento", "Doença", "Procedimento", "Outro evento sanitário"],
    "Geral": ["Pesagem", "Identificação", "Observação", "Outro"],
}
ANIMAL_FIELDS = ["codigo", "brinco", "nome", "sexo", "raca", "data_nascimento", "data_aquisicao", "origem", "categoria", "status", "mae_id", "pai_id", "observacoes"]


def animal_or_404(db, animal_id: int) -> Animal:
    animal = db.get(Animal, animal_id)
    if not animal:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")
    return animal


def parent_options(db, exclude_id: int | None = None):
    stmt = select(Animal).order_by(Animal.codigo)
    if exclude_id:
        stmt = stmt.where(Animal.id != exclude_id)
    animals = db.scalars(stmt).all()
    mothers = [item for item in animals if item.sexo in {"Fêmea", "Não informado"}]
    fathers = [item for item in animals if item.sexo in {"Macho", "Não informado"}]
    return mothers, fathers


def form_page(request: Request, db, *, animal=None, form_data=None, errors=None, status_code=200):
    mothers, fathers = parent_options(db, animal.id if animal else None)
    purpose = f"animal:{animal.id if animal else 'new'}"
    return render(
        request,
        "animais/formulario.html",
        status_code=status_code,
        animal=animal,
        form_data=form_data or {},
        field_errors=errors or {},
        erro=("Revise os campos destacados: " + " ".join(errors.values())) if errors else None,
        sexos=SEXES,
        origens=ORIGINS,
        categorias=CATEGORIES,
        situacoes=STATUSES,
        maes=mothers,
        pais=fathers,
        form_token=issue_form_token(request, purpose),
    )


def validate_animal_form(db, data: dict[str, str], existing: Animal | None = None):
    errors: dict[str, str] = {}
    parsed: dict = {}
    code = data.get("codigo", "").strip()
    if not code:
        errors["codigo"] = "O código ou número do brinco é obrigatório."
    else:
        duplicate = db.scalar(select(Animal.id).where(Animal.codigo == code, Animal.id != (existing.id if existing else -1)))
        if duplicate:
            errors["codigo"] = "Código já cadastrado."
        parsed["codigo"] = code
    brinco = data.get("brinco", "").strip() or None
    if brinco:
        duplicate = db.scalar(select(Animal.id).where(Animal.brinco == brinco, Animal.id != (existing.id if existing else -1)))
        if duplicate:
            errors["brinco"] = "Número de brinco já cadastrado."
    parsed["brinco"] = brinco
    parsed["nome"] = data.get("nome", "").strip() or None
    sex = data.get("sexo", "Não informado")
    parsed["sexo"] = sex if sex in SEXES else "Não informado"
    parsed["raca"] = data.get("raca", "").strip() or None
    try:
        birth = parse_date(data.get("data_nascimento"), "Data de nascimento")
        if birth and birth > date.today():
            errors["data_nascimento"] = "A data de nascimento não pode ser futura."
        parsed["data_nascimento"] = birth
    except ValueError as exc:
        errors["data_nascimento"] = str(exc)
        birth = None
    try:
        entry = parse_date(data.get("data_aquisicao"), "Data de entrada", required=existing is None)
        if entry and entry > date.today():
            errors["data_aquisicao"] = "A data de entrada não pode ser futura."
        parsed["data_aquisicao"] = entry
    except ValueError as exc:
        errors["data_aquisicao"] = str(exc)
        entry = None
    if birth and entry and birth > entry and "data_nascimento" not in errors:
        errors["data_nascimento"] = "A data de nascimento não pode ser posterior à data de entrada."
    origin = data.get("origem", "Não informado")
    parsed["origem"] = origin if origin in ORIGINS else "Não informado"
    category = data.get("categoria", "Não informado")
    parsed["categoria"] = category if category in CATEGORIES else "Não informado"
    status_value = data.get("status", "Ativo")
    parsed["status"] = status_value if status_value in STATUSES else "Ativo"
    mother_id = optional_int(data.get("mae_id"))
    father_id = optional_int(data.get("pai_id"))
    if existing and mother_id == existing.id:
        errors["mae_id"] = "O animal não pode ser pai ou mãe de si próprio."
    if existing and father_id == existing.id:
        errors["pai_id"] = "O animal não pode ser pai ou mãe de si próprio."
    mother = db.get(Animal, mother_id) if mother_id else None
    father = db.get(Animal, father_id) if father_id else None
    if "mae_id" not in errors:
        if mother_id and not mother:
            errors["mae_id"] = "Mãe não encontrada."
        elif mother and mother.sexo == "Macho":
            errors["mae_id"] = "O animal selecionado como mãe está cadastrado como macho."
    if "pai_id" not in errors:
        if father_id and not father:
            errors["pai_id"] = "Pai não encontrado."
        elif father and father.sexo == "Fêmea":
            errors["pai_id"] = "O animal selecionado como pai está cadastrado como fêmea."
    parsed["mae_id"] = mother_id
    parsed["pai_id"] = father_id
    observations = data.get("observacoes", "").strip()
    if len(observations) > 5000:
        errors["observacoes"] = "As observações devem possuir no máximo 5.000 caracteres."
    parsed["observacoes"] = observations or None
    return parsed, errors


def initial_movement_type(origin: str) -> str:
    return {"Nascimento": "Entrada por nascimento", "Compra": "Entrada por compra", "Transferência": "Entrada por transferência"}.get(origin, "Outro")


def status_movement_type(status_value: str) -> str:
    return {"Vendido": "Venda", "Falecido": "Falecimento", "Transferido": "Transferência de saída", "Inativo": "Inativação", "Ativo": "Reativação"}.get(status_value, "Alteração cadastral relevante")


@router.get("", response_class=HTMLResponse)
def list_animals(
    request: Request,
    db: DBSession,
    busca: str = "",
    sexo: str = "",
    categoria: str = "",
    situacao: str = "Ativo",
    mostrar_todos: str = "",
    page: int = 1,
    per_page: int = 20,
):
    current_user(request, db)
    conditions = []
    search = busca.strip()
    if search:
        term = f"%{search}%"
        conditions.append(or_(Animal.codigo.ilike(term), Animal.brinco.ilike(term), Animal.nome.ilike(term), Animal.raca.ilike(term)))
    if sexo in SEXES:
        conditions.append(Animal.sexo == sexo)
    if categoria in CATEGORIES:
        conditions.append(Animal.categoria == categoria)
    if not mostrar_todos:
        conditions.append(Animal.status == (situacao if situacao in STATUSES else "Ativo"))
    elif situacao in STATUSES and situacao:
        conditions.append(Animal.status == situacao)
    page = max(page, 1)
    per_page = min(max(per_page, 10), 100)
    total = int(db.scalar(select(func.count(Animal.id)).where(*conditions)) or 0)
    last_production = (
        select(Producao.animal_id, func.max(Producao.data_registro).label("last_date"))
        .group_by(Producao.animal_id).subquery()
    )
    rows = db.execute(
        select(Animal, last_production.c.last_date)
        .outerjoin(last_production, last_production.c.animal_id == Animal.id)
        .where(*conditions).order_by(Animal.codigo).offset((page - 1) * per_page).limit(per_page)
    ).all()
    pages = max((total + per_page - 1) // per_page, 1)
    return render(request, "animais/lista.html", rows=rows, animais=[row[0] for row in rows], busca=search, sexo=sexo, categoria=categoria, situacao=situacao, mostrar_todos=mostrar_todos, sexos=SEXES, categorias=CATEGORIES, situacoes=STATUSES, page=page, pages=pages, per_page=per_page, total=total)


@router.get("/novo", response_class=HTMLResponse)
def new_form(request: Request, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return form_page(request, db, form_data={"data_aquisicao": date.today().isoformat(), "status": "Ativo", "sexo": "Não informado", "origem": "Não informado", "categoria": "Não informado"})


@router.post("/novo")
def create_animal(
    request: Request,
    db: DBSession,
    csrf_token: CSRFToken,
    form_token: Annotated[str, Form()] = "",
    codigo: Annotated[str, Form()] = "",
    brinco: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "",
    sexo: Annotated[str, Form()] = "Não informado",
    raca: Annotated[str, Form()] = "",
    data_nascimento: Annotated[str, Form()] = "",
    data_aquisicao: Annotated[str, Form()] = "",
    origem: Annotated[str, Form()] = "Não informado",
    categoria: Annotated[str, Form()] = "Não informado",
    status_value: Annotated[str, Form(alias="status")] = "Ativo",
    mae_id: Annotated[str, Form()] = "",
    pai_id: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    data = locals().copy()
    data["status"] = status_value
    if not consume_form_token(request, "animal:new", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse("/animais", status_code=303)
    parsed, errors = validate_animal_form(db, data)
    if errors:
        return form_page(request, db, form_data=data, errors=errors, status_code=400)
    animal = Animal(**parsed, criado_por_id=user.id, atualizado_por_id=user.id)
    db.add(animal)
    db.flush()
    movement = MovimentacaoAnimal(
        animal_id=animal.id,
        data=animal.data_aquisicao or date.today(),
        tipo=initial_movement_type(animal.origem),
        situacao_anterior=None,
        situacao_posterior=animal.status,
        motivo=f"Entrada cadastrada: {animal.origem}",
        usuario_id=user.id,
    )
    db.add(movement)
    record_audit(db, user=user, operation="criação", entity="animal", record_id=animal.id, summary=f"Animal {animal.codigo} criado.", after=snapshot(animal, ANIMAL_FIELDS))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        errors["codigo"] = "Código ou brinco já cadastrado."
        return form_page(request, db, form_data=data, errors=errors, status_code=400)
    add_flash(request, "Animal cadastrado com sucesso.")
    return RedirectResponse(f"/animais/{animal.id}", status_code=303)


@router.get("/{animal_id}", response_class=HTMLResponse)
def detail(request: Request, animal_id: int, db: DBSession):
    current_user(request, db)
    animal = db.scalar(
        select(Animal)
        .options(selectinload(Animal.producoes), selectinload(Animal.movimentacoes), selectinload(Animal.eventos), joinedload(Animal.mae), joinedload(Animal.pai))
        .where(Animal.id == animal_id)
    )
    if not animal:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")
    total_liters = sum((Decimal(item.quantidade_litros) for item in animal.producoes), Decimal("0"))
    average = total_liters / len(animal.producoes) if animal.producoes else None
    direct_cost = Decimal(db.scalar(select(func.coalesce(func.sum(Custo.valor_total), 0)).where(Custo.animal_id == animal.id, Custo.situacao != "Cancelado")) or 0)
    allocated_cost = Decimal(db.scalar(select(func.coalesce(func.sum(RateioCusto.valor), 0)).join(Custo).where(RateioCusto.animal_id == animal.id, Custo.situacao != "Cancelado")) or 0)
    direct_revenue = Decimal(db.scalar(select(func.coalesce(func.sum(Receita.valor_total), 0)).where(Receita.animal_id == animal.id, Receita.situacao != "Cancelado")) or 0)
    descendants = db.scalars(select(Animal).where(or_(Animal.mae_id == animal.id, Animal.pai_id == animal.id)).order_by(Animal.codigo)).all()
    return render(request, "animais/detalhe.html", animal=animal, litros_total=total_liters, media=average, ultima_producao=max((item.data_registro for item in animal.producoes), default=None), direct_cost=direct_cost, allocated_cost=allocated_cost, direct_revenue=direct_revenue, direct_result=direct_revenue - direct_cost, allocated_result=direct_revenue - direct_cost - allocated_cost, descendants=descendants, chart_labels=[item.data_registro.strftime("%d/%m/%Y") for item in animal.producoes], chart_values=[float(item.quantidade_litros) for item in animal.producoes])


@router.get("/{animal_id}/editar", response_class=HTMLResponse)
def edit_form(request: Request, animal_id: int, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    return form_page(request, db, animal=animal_or_404(db, animal_id))


@router.post("/{animal_id}/editar")
def update_animal(
    request: Request,
    animal_id: int,
    db: DBSession,
    csrf_token: CSRFToken,
    form_token: Annotated[str, Form()] = "",
    codigo: Annotated[str, Form()] = "",
    brinco: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "",
    sexo: Annotated[str, Form()] = "Não informado",
    raca: Annotated[str, Form()] = "",
    data_nascimento: Annotated[str, Form()] = "",
    data_aquisicao: Annotated[str, Form()] = "",
    origem: Annotated[str, Form()] = "Não informado",
    categoria: Annotated[str, Form()] = "Não informado",
    status_value: Annotated[str, Form(alias="status")] = "Ativo",
    mae_id: Annotated[str, Form()] = "",
    pai_id: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    animal = animal_or_404(db, animal_id)
    data = locals().copy()
    data["status"] = status_value
    if not consume_form_token(request, f"animal:{animal_id}", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse(f"/animais/{animal_id}", status_code=303)
    parsed, errors = validate_animal_form(db, data, animal)
    if errors:
        return form_page(request, db, animal=animal, form_data=data, errors=errors, status_code=400)
    before = snapshot(animal, ANIMAL_FIELDS)
    old_status = animal.status
    for key, value in parsed.items():
        setattr(animal, key, value)
    animal.atualizado_por_id = user.id
    if old_status != animal.status:
        db.add(MovimentacaoAnimal(animal_id=animal.id, data=date.today(), tipo=status_movement_type(animal.status), situacao_anterior=old_status, situacao_posterior=animal.status, motivo="Alteração realizada na edição cadastral.", usuario_id=user.id))
    record_audit(db, user=user, operation="edição", entity="animal", record_id=animal.id, summary=f"Animal {animal.codigo} atualizado.", before=before, after=snapshot(animal, ANIMAL_FIELDS))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        errors["codigo"] = "Código ou brinco já cadastrado."
        return form_page(request, db, animal=animal, form_data=data, errors=errors, status_code=400)
    add_flash(request, "Animal atualizado com sucesso.")
    return RedirectResponse(f"/animais/{animal.id}", status_code=303)


@router.post("/{animal_id}/situacao")
def change_status(
    request: Request,
    animal_id: int,
    db: DBSession,
    csrf_token: CSRFToken,
    situacao: Annotated[str, Form()],
    data_movimentacao: Annotated[str, Form()],
    motivo: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    animal = animal_or_404(db, animal_id)
    if situacao not in STATUSES:
        raise HTTPException(status_code=400, detail="Situação inválida.")
    try:
        movement_date = parse_date(data_movimentacao, "Data", required=True)
    except ValueError as exc:
        add_flash(request, str(exc), "error")
        return RedirectResponse(f"/animais/{animal_id}", status_code=303)
    old = animal.status
    if old == situacao:
        add_flash(request, "O animal já está nessa situação.", "warning")
        return RedirectResponse(f"/animais/{animal_id}", status_code=303)
    animal.status = situacao
    animal.atualizado_por_id = user.id
    db.add(MovimentacaoAnimal(animal_id=animal.id, data=movement_date, tipo=status_movement_type(situacao), situacao_anterior=old, situacao_posterior=situacao, motivo=motivo.strip() or status_movement_type(situacao), observacoes=observacoes.strip() or None, usuario_id=user.id))
    record_audit(db, user=user, operation="alteração de situação", entity="animal", record_id=animal.id, summary=f"Situação alterada de {old} para {situacao}.", before={"status": old}, after={"status": situacao})
    db.commit()
    add_flash(request, "Situação atualizada e movimentação registrada.")
    return RedirectResponse(f"/animais/{animal.id}", status_code=303)


@router.get("/{animal_id}/eventos/novo", response_class=HTMLResponse)
def event_form(request: Request, animal_id: int, db: DBSession):
    user = current_user(request, db)
    require_write(user)
    animal = animal_or_404(db, animal_id)
    fathers = db.scalars(select(Animal).where(Animal.sexo.in_(["Macho", "Não informado"]), Animal.id != animal.id).order_by(Animal.codigo)).all()
    return render(request, "animais/evento_formulario.html", animal=animal, grupos=EVENT_GROUPS, pais=fathers, form_token=issue_form_token(request, f"event:{animal_id}"), field_errors={}, form_data={"data": date.today().isoformat()})


@router.post("/{animal_id}/eventos/novo")
def create_event(
    request: Request,
    animal_id: int,
    db: DBSession,
    csrf_token: CSRFToken,
    form_token: Annotated[str, Form()] = "",
    data_evento: Annotated[str, Form(alias="data")] = "",
    grupo: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = "",
    titulo: Annotated[str, Form()] = "",
    descricao: Annotated[str, Form()] = "",
    observacoes: Annotated[str, Form()] = "",
    pai_id: Annotated[str, Form()] = "",
    descendentes: Annotated[str, Form()] = "",
):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    animal = animal_or_404(db, animal_id)
    if not consume_form_token(request, f"event:{animal_id}", form_token):
        add_flash(request, "O formulário já foi enviado ou expirou.", "warning")
        return RedirectResponse(f"/animais/{animal_id}", status_code=303)
    errors: dict[str, str] = {}
    try:
        parsed_date = parse_date(data_evento, "Data do evento", required=True)
        if parsed_date and parsed_date > date.today():
            errors["data"] = "A data do evento não pode ser futura."
    except ValueError as exc:
        parsed_date = None
        errors["data"] = str(exc)
    if grupo not in EVENT_GROUPS:
        errors["grupo"] = "Grupo de evento inválido."
    elif tipo not in EVENT_GROUPS[grupo]:
        errors["tipo"] = "Tipo de evento inválido."
    if not titulo.strip():
        errors["titulo"] = "O título é obrigatório."
    form_data = {"data": data_evento, "grupo": grupo, "tipo": tipo, "titulo": titulo, "descricao": descricao, "observacoes": observacoes, "pai_id": pai_id, "descendentes": descendentes}
    if errors:
        fathers = db.scalars(select(Animal).where(Animal.sexo.in_(["Macho", "Não informado"]), Animal.id != animal.id).order_by(Animal.codigo)).all()
        return render(request, "animais/evento_formulario.html", status_code=400, animal=animal, grupos=EVENT_GROUPS, pais=fathers, form_token=issue_form_token(request, f"event:{animal_id}"), field_errors=errors, form_data=form_data)
    event = EventoAnimal(animal_id=animal.id, data=parsed_date, grupo=grupo, tipo=tipo, titulo=titulo.strip(), descricao=descricao.strip() or None, observacoes=observacoes.strip() or None, usuario_id=user.id)
    db.add(event)
    db.flush()
    created_children = []
    if tipo == "Parto" and descendentes.strip():
        selected_father_id = optional_int(pai_id)
        father = db.get(Animal, selected_father_id) if selected_father_id else None
        for line in descendentes.splitlines():
            parts = [part.strip() for part in line.split(";")]
            if not parts or not parts[0]:
                continue
            code = parts[0]
            name = parts[1] if len(parts) > 1 else None
            sex_value = parts[2] if len(parts) > 2 and parts[2] in SEXES else "Não informado"
            if db.scalar(select(Animal.id).where(Animal.codigo == code)):
                raise HTTPException(status_code=400, detail=f"O descendente {code} já existe.")
            category = "Bezerra" if sex_value == "Fêmea" else "Bezerro" if sex_value == "Macho" else "Não informado"
            child = Animal(codigo=code, nome=name or None, sexo=sex_value, data_nascimento=parsed_date, data_aquisicao=parsed_date, origem="Nascimento", categoria=category, status="Ativo", mae_id=animal.id, pai_id=father.id if father else None, criado_por_id=user.id, atualizado_por_id=user.id)
            db.add(child)
            db.flush()
            db.add(MovimentacaoAnimal(animal_id=child.id, data=parsed_date, tipo="Entrada por nascimento", situacao_anterior=None, situacao_posterior="Ativo", motivo=f"Nascimento registrado no parto de {animal.codigo}.", usuario_id=user.id))
            created_children.append(child.codigo)
    record_audit(db, user=user, operation="criação", entity="evento", record_id=event.id, summary=f"Evento {tipo} registrado para {animal.codigo}." + (f" Descendentes: {', '.join(created_children)}." if created_children else ""))
    db.commit()
    add_flash(request, "Evento registrado com sucesso." + (f" {len(created_children)} descendente(s) cadastrado(s)." if created_children else ""))
    return RedirectResponse(f"/animais/{animal.id}", status_code=303)


@router.post("/{animal_id}/excluir")
def delete_animal(request: Request, animal_id: int, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    user = current_user(request, db)
    require_write(user)
    animal = animal_or_404(db, animal_id)
    related = any([
        db.scalar(select(func.count(Producao.id)).where(Producao.animal_id == animal.id)),
        db.scalar(select(func.count(MovimentacaoAnimal.id)).where(MovimentacaoAnimal.animal_id == animal.id)),
        db.scalar(select(func.count(EventoAnimal.id)).where(EventoAnimal.animal_id == animal.id)),
        db.scalar(select(func.count(Animal.id)).where(or_(Animal.mae_id == animal.id, Animal.pai_id == animal.id))),
        db.scalar(select(func.count(Custo.id)).where(Custo.animal_id == animal.id)),
        db.scalar(select(func.count(Receita.id)).where(Receita.animal_id == animal.id)),
        db.scalar(select(func.count(RateioCusto.id)).where(RateioCusto.animal_id == animal.id)),
    ])
    if related:
        old = animal.status
        animal.status = "Inativo"
        db.add(MovimentacaoAnimal(animal_id=animal.id, data=date.today(), tipo="Inativação", situacao_anterior=old, situacao_posterior="Inativo", motivo="Exclusão física impedida por registros relacionados.", usuario_id=user.id))
        record_audit(db, user=user, operation="inativação", entity="animal", record_id=animal.id, summary="Animal inativado porque possui histórico relacionado.", before={"status": old}, after={"status": "Inativo"})
        db.commit()
        add_flash(request, "O animal possui histórico e foi inativado em vez de excluído.", "warning")
    else:
        before = snapshot(animal, ANIMAL_FIELDS)
        db.delete(animal)
        record_audit(db, user=user, operation="exclusão", entity="animal", record_id=animal.id, summary="Animal sem relacionamentos excluído.", before=before)
        db.commit()
        add_flash(request, "Animal excluído com sucesso.")
    return RedirectResponse("/animais", status_code=303)
