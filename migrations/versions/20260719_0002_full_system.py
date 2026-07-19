"""Ampliação completa: animais, histórico, financeiro, auditoria, usuários e backup.

Revision ID: 20260719_0002
Revises: 20260717_0001
Create Date: 2026-07-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260719_0002"
down_revision: Union[str, None] = "20260717_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_indexes(table) if item.get("name")}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index_if_missing(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    now = sa.text("CURRENT_TIMESTAMP")

    _add_column_if_missing("usuarios", sa.Column("name", sa.String(length=120), nullable=True))
    _add_column_if_missing("usuarios", sa.Column("role", sa.String(length=20), nullable=False, server_default="Administrador"))
    _add_column_if_missing("usuarios", sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"))

    _add_column_if_missing("animais", sa.Column("origem", sa.String(length=30), nullable=False, server_default="Não informado"))
    _add_column_if_missing("animais", sa.Column("categoria", sa.String(length=30), nullable=False, server_default="Não informado"))
    _add_column_if_missing("animais", sa.Column("mae_id", sa.Integer(), nullable=True))
    _add_column_if_missing("animais", sa.Column("pai_id", sa.Integer(), nullable=True))
    if "atualizado_em" not in _columns("animais"):
        if op.get_bind().dialect.name == "sqlite":
            op.add_column("animais", sa.Column("atualizado_em", sa.DateTime(), nullable=True))
            op.execute(sa.text("UPDATE animais SET atualizado_em = CURRENT_TIMESTAMP WHERE atualizado_em IS NULL"))
        else:
            op.add_column("animais", sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=now))
    _add_column_if_missing("animais", sa.Column("criado_por_id", sa.Integer(), nullable=True))
    _add_column_if_missing("animais", sa.Column("atualizado_por_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_animais_status", "animais", ["status"])
    _create_index_if_missing("ix_animais_origem", "animais", ["origem"])
    _create_index_if_missing("ix_animais_categoria", "animais", ["categoria"])
    _create_index_if_missing("ix_animais_mae_id", "animais", ["mae_id"])
    _create_index_if_missing("ix_animais_pai_id", "animais", ["pai_id"])

    if "atualizado_em" not in _columns("producoes"):
        if op.get_bind().dialect.name == "sqlite":
            op.add_column("producoes", sa.Column("atualizado_em", sa.DateTime(), nullable=True))
            op.execute(sa.text("UPDATE producoes SET atualizado_em = CURRENT_TIMESTAMP WHERE atualizado_em IS NULL"))
        else:
            op.add_column("producoes", sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=now))
    _add_column_if_missing("producoes", sa.Column("criado_por_id", sa.Integer(), nullable=True))
    _add_column_if_missing("producoes", sa.Column("atualizado_por_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_producoes_animal_data", "producoes", ["animal_id", "data_registro"])

    tables = _tables()
    if "movimentacoes_animais" not in tables:
        op.create_table(
            "movimentacoes_animais",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animais.id"), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("tipo", sa.String(length=50), nullable=False),
            sa.Column("situacao_anterior", sa.String(length=30), nullable=True),
            sa.Column("situacao_posterior", sa.String(length=30), nullable=True),
            sa.Column("motivo", sa.String(length=250), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
        )
        op.create_index("ix_movimentacoes_animais_animal_id", "movimentacoes_animais", ["animal_id"])
        op.create_index("ix_movimentacoes_animais_data", "movimentacoes_animais", ["data"])
        op.create_index("ix_movimentacoes_animais_tipo", "movimentacoes_animais", ["tipo"])
        op.create_index("ix_movimentacoes_animais_usuario_id", "movimentacoes_animais", ["usuario_id"])

    if "eventos_animais" not in tables:
        op.create_table(
            "eventos_animais",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animais.id"), nullable=False),
            sa.Column("data", sa.Date(), nullable=False),
            sa.Column("grupo", sa.String(length=30), nullable=False),
            sa.Column("tipo", sa.String(length=60), nullable=False),
            sa.Column("titulo", sa.String(length=160), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=now),
        )
        op.create_index("ix_eventos_animais_animal_id", "eventos_animais", ["animal_id"])
        op.create_index("ix_eventos_animais_data", "eventos_animais", ["data"])
        op.create_index("ix_eventos_animais_grupo", "eventos_animais", ["grupo"])
        op.create_index("ix_eventos_animais_tipo", "eventos_animais", ["tipo"])
        op.create_index("ix_eventos_animais_usuario_id", "eventos_animais", ["usuario_id"])

    if "custos" not in tables:
        op.create_table(
            "custos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("data_competencia", sa.Date(), nullable=False),
            sa.Column("data_pagamento", sa.Date(), nullable=True),
            sa.Column("categoria", sa.String(length=60), nullable=False),
            sa.Column("descricao", sa.String(length=250), nullable=False),
            sa.Column("tipo_apropriacao", sa.String(length=40), nullable=False),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animais.id"), nullable=True),
            sa.Column("quantidade", sa.Numeric(14, 3), nullable=True),
            sa.Column("unidade_medida", sa.String(length=30), nullable=True),
            sa.Column("valor_unitario", sa.Numeric(14, 4), nullable=True),
            sa.Column("valor_total", sa.Numeric(14, 2), nullable=False),
            sa.Column("fornecedor", sa.String(length=160), nullable=True),
            sa.Column("documento", sa.String(length=100), nullable=True),
            sa.Column("situacao", sa.String(length=20), nullable=False, server_default="Pendente"),
            sa.Column("forma_pagamento", sa.String(length=30), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("atualizado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("cancelado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("cancelado_em", sa.DateTime(), nullable=True),
            sa.CheckConstraint("valor_total > 0", name="ck_custos_valor_positivo"),
        )
        for name, cols in [
            ("ix_custos_data_competencia", ["data_competencia"]), ("ix_custos_data_pagamento", ["data_pagamento"]),
            ("ix_custos_categoria", ["categoria"]), ("ix_custos_tipo_apropriacao", ["tipo_apropriacao"]),
            ("ix_custos_animal_id", ["animal_id"]), ("ix_custos_fornecedor", ["fornecedor"]),
            ("ix_custos_situacao", ["situacao"]), ("ix_custos_competencia_situacao", ["data_competencia", "situacao"]),
        ]:
            op.create_index(name, "custos", cols)

    if "rateios_custos" not in tables:
        op.create_table(
            "rateios_custos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("custo_id", sa.Integer(), sa.ForeignKey("custos.id"), nullable=False),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animais.id"), nullable=False),
            sa.Column("metodo", sa.String(length=40), nullable=False),
            sa.Column("percentual", sa.Numeric(8, 4), nullable=True),
            sa.Column("valor", sa.Numeric(14, 2), nullable=False),
            sa.Column("periodo_inicio", sa.Date(), nullable=True),
            sa.Column("periodo_fim", sa.Date(), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.UniqueConstraint("custo_id", "animal_id", name="uq_rateio_custo_animal"),
            sa.CheckConstraint("valor >= 0", name="ck_rateios_valor_nao_negativo"),
        )
        op.create_index("ix_rateios_custos_custo_id", "rateios_custos", ["custo_id"])
        op.create_index("ix_rateios_custos_animal_id", "rateios_custos", ["animal_id"])

    if "receitas" not in tables:
        op.create_table(
            "receitas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("data_competencia", sa.Date(), nullable=False),
            sa.Column("data_recebimento", sa.Date(), nullable=True),
            sa.Column("categoria", sa.String(length=60), nullable=False),
            sa.Column("descricao", sa.String(length=250), nullable=False),
            sa.Column("animal_id", sa.Integer(), sa.ForeignKey("animais.id"), nullable=True),
            sa.Column("quantidade", sa.Numeric(14, 3), nullable=True),
            sa.Column("unidade_medida", sa.String(length=30), nullable=True),
            sa.Column("valor_unitario", sa.Numeric(14, 4), nullable=True),
            sa.Column("valor_total", sa.Numeric(14, 2), nullable=False),
            sa.Column("comprador", sa.String(length=160), nullable=True),
            sa.Column("documento", sa.String(length=100), nullable=True),
            sa.Column("situacao", sa.String(length=20), nullable=False, server_default="Pendente"),
            sa.Column("forma_recebimento", sa.String(length=30), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("criado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("atualizado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("cancelado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("atualizado_em", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("cancelado_em", sa.DateTime(), nullable=True),
            sa.CheckConstraint("valor_total > 0", name="ck_receitas_valor_positivo"),
        )
        for name, cols in [
            ("ix_receitas_data_competencia", ["data_competencia"]), ("ix_receitas_data_recebimento", ["data_recebimento"]),
            ("ix_receitas_categoria", ["categoria"]), ("ix_receitas_animal_id", ["animal_id"]),
            ("ix_receitas_comprador", ["comprador"]), ("ix_receitas_situacao", ["situacao"]),
            ("ix_receitas_competencia_situacao", ["data_competencia", "situacao"]),
        ]:
            op.create_index(name, "receitas", cols)

    if "auditoria" not in tables:
        op.create_table(
            "auditoria",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("operacao", sa.String(length=30), nullable=False),
            sa.Column("entidade", sa.String(length=60), nullable=False),
            sa.Column("registro_id", sa.String(length=60), nullable=True),
            sa.Column("resumo", sa.Text(), nullable=True),
            sa.Column("antes", sa.Text(), nullable=True),
            sa.Column("depois", sa.Text(), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
        )
        for name, cols in [
            ("ix_auditoria_usuario_id", ["usuario_id"]), ("ix_auditoria_operacao", ["operacao"]),
            ("ix_auditoria_entidade", ["entidade"]), ("ix_auditoria_registro_id", ["registro_id"]),
            ("ix_auditoria_criado_em", ["criado_em"]),
        ]:
            op.create_index(name, "auditoria", cols)

    if "backups" not in tables:
        op.create_table(
            "backups",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ambiente", sa.String(length=20), nullable=False),
            sa.Column("tipo", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("arquivo", sa.String(length=255), nullable=True),
            sa.Column("tamanho_bytes", sa.Integer(), nullable=True),
            sa.Column("schema_version", sa.String(length=50), nullable=True),
            sa.Column("mensagem", sa.Text(), nullable=True),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False, server_default=now),
        )
        op.create_index("ix_backups_criado_em", "backups", ["criado_em"])


def downgrade() -> None:
    # Downgrade seguro para as tabelas novas. Colunas adicionadas às tabelas legadas
    # são preservadas para evitar perda de dados em rollback operacional.
    for table in ["backups", "auditoria", "rateios_custos", "receitas", "custos", "eventos_animais", "movimentacoes_animais"]:
        if table in _tables():
            op.drop_table(table)
