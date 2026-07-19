from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from ..config import BASE_DIR, get_settings
from ..dependencies import add_flash, current_user, require_admin
from ..models import Animal, AuditLog, BackupRecord, Custo, EventoAnimal, MovimentacaoAnimal, Producao, RateioCusto, Receita, User
from ..security import hash_password, verify_csrf_token
from ..services.audit import record_audit
from ..services.exports import zip_response
from ..utils.formatting import csv_safe
from ..web import CSRFToken, DBSession, render

router = APIRouter(prefix="/admin", tags=["administração"])
ROLES = ["Administrador", "Operador", "Consulta"]
settings = get_settings()


def admin_user(request: Request, db) -> User:
    user = current_user(request, db)
    require_admin(user)
    return user


def user_or_404(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return user


@router.get("/usuarios", response_class=HTMLResponse)
def users_list(request: Request, db: DBSession):
    admin_user(request, db)
    users = db.scalars(select(User).order_by(User.username)).all()
    return render(request, "admin/usuarios.html", usuarios=users, roles=ROLES)


@router.get("/usuarios/novo", response_class=HTMLResponse)
def new_user_form(request: Request, db: DBSession):
    admin_user(request, db)
    return render(request, "admin/usuario_formulario.html", usuario=None, roles=ROLES, erro=None, form_data={})


@router.post("/usuarios/novo")
def create_user(request: Request, db: DBSession, csrf_token: CSRFToken, name: Annotated[str, Form()] = "", username: Annotated[str, Form()] = "", password: Annotated[str, Form()] = "", confirm_password: Annotated[str, Form()] = "", role: Annotated[str, Form()] = "Consulta"):
    verify_csrf_token(request, csrf_token)
    admin = admin_user(request, db)
    normalized = username.strip().lower()
    error = None
    if not normalized:
        error = "O login é obrigatório."
    elif db.scalar(select(User.id).where(User.username == normalized)):
        error = "Este login já está cadastrado."
    elif role not in ROLES:
        error = "Perfil inválido."
    elif len(password) < 8 or not password.strip():
        error = "A senha deve ter pelo menos oito caracteres e não pode conter apenas espaços."
    elif password.lower() == normalized:
        error = "A senha não pode ser igual ao login."
    elif password != confirm_password:
        error = "A confirmação da senha não corresponde."
    if error:
        return render(request, "admin/usuario_formulario.html", status_code=400, usuario=None, roles=ROLES, erro=error, form_data={"name": name, "username": username, "role": role})
    user = User(name=name.strip() or None, username=normalized, password_hash=hash_password(password), role=role, is_active=True, must_change_password=True, session_version=1)
    db.add(user)
    db.flush()
    record_audit(db, user=admin, operation="criação", entity="usuário", record_id=user.id, summary=f"Usuário {user.username} criado com perfil {role}.")
    db.commit()
    add_flash(request, "Usuário criado com sucesso.")
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.get("/usuarios/{user_id}/editar", response_class=HTMLResponse)
def edit_user_form(request: Request, user_id: int, db: DBSession):
    admin_user(request, db)
    return render(request, "admin/usuario_formulario.html", usuario=user_or_404(db, user_id), roles=ROLES, erro=None, form_data={})


@router.post("/usuarios/{user_id}/editar")
def update_user(request: Request, user_id: int, db: DBSession, csrf_token: CSRFToken, name: Annotated[str, Form()] = "", role: Annotated[str, Form()] = "Consulta", is_active: Annotated[str, Form()] = ""):
    verify_csrf_token(request, csrf_token)
    admin = admin_user(request, db)
    user = user_or_404(db, user_id)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Perfil inválido.")
    active = is_active == "1"
    if user.id == admin.id and (not active or role != "Administrador"):
        raise HTTPException(status_code=400, detail="O administrador atual não pode remover o próprio acesso administrativo.")
    before = {"name": user.name, "role": user.role, "is_active": user.is_active}
    user.name = name.strip() or None
    user.role = role
    if user.is_active != active:
        user.session_version += 1
    user.is_active = active
    record_audit(db, user=admin, operation="edição", entity="usuário", record_id=user.id, summary=f"Usuário {user.username} atualizado.", before=before, after={"name": user.name, "role": user.role, "is_active": user.is_active})
    db.commit()
    add_flash(request, "Usuário atualizado com sucesso.")
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/usuarios/{user_id}/redefinir-senha")
def reset_user_password(request: Request, user_id: int, db: DBSession, csrf_token: CSRFToken, new_password: Annotated[str, Form()], confirm_password: Annotated[str, Form()]):
    verify_csrf_token(request, csrf_token)
    admin = admin_user(request, db)
    user = user_or_404(db, user_id)
    if len(new_password) < 8 or not new_password.strip() or new_password.lower() == user.username.lower():
        raise HTTPException(status_code=400, detail="A senha deve ter oito caracteres, não pode ser vazia e não pode ser igual ao login.")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="A confirmação da senha não corresponde.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.session_version += 1
    record_audit(db, user=admin, operation="redefinição de senha", entity="usuário", record_id=user.id, summary=f"Senha do usuário {user.username} redefinida administrativamente.")
    db.commit()
    add_flash(request, "Senha redefinida. O usuário deverá alterá-la no próximo acesso.")
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.get("/auditoria", response_class=HTMLResponse)
def audit_list(request: Request, db: DBSession, entidade: str = "", operacao: str = "", page: int = 1, per_page: int = 50):
    admin_user(request, db)
    conditions = []
    if entidade.strip():
        conditions.append(AuditLog.entidade == entidade.strip())
    if operacao.strip():
        conditions.append(AuditLog.operacao == operacao.strip())
    page, per_page = max(page, 1), min(max(per_page, 20), 100)
    total = int(db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0)
    rows = db.scalars(select(AuditLog).where(*conditions).order_by(AuditLog.criado_em.desc(), AuditLog.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    entities = db.scalars(select(AuditLog.entidade).distinct().order_by(AuditLog.entidade)).all()
    operations = db.scalars(select(AuditLog.operacao).distinct().order_by(AuditLog.operacao)).all()
    pages = max((total + per_page - 1) // per_page, 1)
    return render(request, "admin/auditoria.html", registros=rows, entidades=entities, operacoes=operations, entidade=entidade, operacao=operacao, page=page, pages=pages, per_page=per_page, total=total)


@router.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request, db: DBSession):
    admin_user(request, db)
    records = db.scalars(select(BackupRecord).order_by(BackupRecord.criado_em.desc()).limit(30)).all()
    is_sqlite = settings.database_url.startswith("sqlite")
    return render(request, "admin/backup.html", registros=records, is_sqlite=is_sqlite, app_env=settings.app_env)


@router.post("/backup")
def run_backup(request: Request, db: DBSession, csrf_token: CSRFToken):
    verify_csrf_token(request, csrf_token)
    admin = admin_user(request, db)
    record = BackupRecord(ambiente=settings.app_env, tipo="manual", status="iniciado", usuario_id=admin.id, schema_version="2.0.0")
    db.add(record)
    db.flush()
    if settings.database_url.startswith("sqlite"):
        try:
            source = Path(settings.database_url.replace("sqlite:///", "", 1))
            backup_dir = BASE_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)
            target = backup_dir / f"sistema_animais_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(source, target)
            record.status = "concluído"
            record.arquivo = str(target.relative_to(BASE_DIR))
            record.tamanho_bytes = target.stat().st_size
            record.mensagem = "Cópia local do SQLite concluída. Guarde o arquivo fora da pasta do sistema."
            record_audit(db, user=admin, operation="backup", entity="banco", record_id=record.id, summary="Backup local SQLite concluído.")
            add_flash(request, "Backup local concluído. Copie o arquivo da pasta backups para um local seguro.")
        except Exception as exc:
            record.status = "falhou"
            record.mensagem = "Não foi possível concluir o backup local. Consulte os logs administrativos."
            record_audit(db, user=admin, operation="falha de backup", entity="banco", record_id=record.id, summary="Falha no backup local SQLite.")
            add_flash(request, "O backup local falhou. Consulte os registros.", "error")
    else:
        record.status = "orientação externa"
        record.mensagem = "Em PostgreSQL/Render, utilize o backup nativo do provedor ou pg_dump em ambiente administrativo. O disco do Render é efêmero."
        record_audit(db, user=admin, operation="solicitação de backup", entity="banco", record_id=record.id, summary="Backup PostgreSQL deve ser executado externamente pelo provedor.")
        add_flash(request, "No ambiente online, execute o backup pelo provedor PostgreSQL. A orientação foi registrada.", "warning")
    db.commit()
    return RedirectResponse("/admin/backup", status_code=303)


def table_csv(headers: list[str], rows: list[list[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_safe(value) for value in row])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


@router.get("/exportar-dados")
def export_all_data(request: Request, db: DBSession):
    admin = admin_user(request, db)
    files: dict[str, bytes] = {}
    animals = db.scalars(select(Animal).order_by(Animal.id)).all()
    files["animais.csv"] = table_csv(["id", "codigo", "brinco", "nome", "sexo", "raca", "data_nascimento", "data_entrada", "origem", "categoria", "situacao", "mae_id", "pai_id", "observacoes"], [[a.id, a.codigo, a.brinco, a.nome, a.sexo, a.raca, a.data_nascimento, a.data_aquisicao, a.origem, a.categoria, a.status, a.mae_id, a.pai_id, a.observacoes] for a in animals])
    productions = db.scalars(select(Producao).order_by(Producao.id)).all()
    files["producoes.csv"] = table_csv(["id", "animal_id", "data", "litros", "valor_litro", "observacoes"], [[p.id, p.animal_id, p.data_registro, p.quantidade_litros, p.valor_litro, p.observacoes] for p in productions])
    movements = db.scalars(select(MovimentacaoAnimal).order_by(MovimentacaoAnimal.id)).all()
    files["movimentacoes.csv"] = table_csv(["id", "animal_id", "data", "tipo", "situacao_anterior", "situacao_posterior", "motivo", "observacoes"], [[m.id, m.animal_id, m.data, m.tipo, m.situacao_anterior, m.situacao_posterior, m.motivo, m.observacoes] for m in movements])
    events = db.scalars(select(EventoAnimal).order_by(EventoAnimal.id)).all()
    files["eventos.csv"] = table_csv(["id", "animal_id", "data", "grupo", "tipo", "titulo", "descricao", "observacoes"], [[e.id, e.animal_id, e.data, e.grupo, e.tipo, e.titulo, e.descricao, e.observacoes] for e in events])
    costs = db.scalars(select(Custo).order_by(Custo.id)).all()
    files["custos.csv"] = table_csv(["id", "competencia", "pagamento", "categoria", "descricao", "tipo_apropriacao", "animal_id", "quantidade", "unidade", "valor_unitario", "valor_total", "fornecedor", "documento", "situacao", "forma", "observacoes"], [[c.id, c.data_competencia, c.data_pagamento, c.categoria, c.descricao, c.tipo_apropriacao, c.animal_id, c.quantidade, c.unidade_medida, c.valor_unitario, c.valor_total, c.fornecedor, c.documento, c.situacao, c.forma_pagamento, c.observacoes] for c in costs])
    allocations = db.scalars(select(RateioCusto).order_by(RateioCusto.id)).all()
    files["rateios.csv"] = table_csv(["id", "custo_id", "animal_id", "metodo", "percentual", "valor", "periodo_inicio", "periodo_fim"], [[r.id, r.custo_id, r.animal_id, r.metodo, r.percentual, r.valor, r.periodo_inicio, r.periodo_fim] for r in allocations])
    revenues = db.scalars(select(Receita).order_by(Receita.id)).all()
    files["receitas.csv"] = table_csv(["id", "competencia", "recebimento", "categoria", "descricao", "animal_id", "quantidade", "unidade", "valor_unitario", "valor_total", "comprador", "documento", "situacao", "forma", "observacoes"], [[r.id, r.data_competencia, r.data_recebimento, r.categoria, r.descricao, r.animal_id, r.quantidade, r.unidade_medida, r.valor_unitario, r.valor_total, r.comprador, r.documento, r.situacao, r.forma_recebimento, r.observacoes] for r in revenues])
    record_audit(db, user=admin, operation="exportação completa", entity="dados", record_id=None, summary="Exportação administrativa completa gerada sem senhas, hashes, tokens ou segredos.")
    db.commit()
    return zip_response(f"exportacao_completa_{datetime.now().strftime('%Y%m%d_%H%M%S')}", files)
