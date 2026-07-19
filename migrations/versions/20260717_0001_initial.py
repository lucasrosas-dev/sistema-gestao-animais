"""Estrutura inicial do sistema com usuários, animais e produções.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_indexes(table_name) if item.get("name")}


def upgrade() -> None:
    tables = _tables()

    if "usuarios" not in tables:
        op.create_table(
            "usuarios",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=80), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("username", name="uq_usuarios_username"),
        )
        op.create_index("ix_usuarios_username", "usuarios", ["username"], unique=True)

    if "animais" not in tables:
        op.create_table(
            "animais",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("codigo", sa.String(length=30), nullable=False),
            sa.Column("brinco", sa.String(length=30), nullable=True),
            sa.Column("nome", sa.String(length=100), nullable=True),
            sa.Column("sexo", sa.String(length=10), nullable=False),
            sa.Column("raca", sa.String(length=80), nullable=True),
            sa.Column("data_nascimento", sa.Date(), nullable=True),
            sa.Column("data_aquisicao", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="Ativo"),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("codigo", name="uq_animais_codigo"),
            sa.UniqueConstraint("brinco", name="uq_animais_brinco"),
        )
        op.create_index("ix_animais_codigo", "animais", ["codigo"], unique=True)
    else:
        indexes = _indexes("animais")
        if "ix_animais_codigo" not in indexes:
            op.create_index("ix_animais_codigo", "animais", ["codigo"], unique=True)

    tables = _tables()
    if "producoes" not in tables:
        op.create_table(
            "producoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("animal_id", sa.Integer(), nullable=False),
            sa.Column("data_registro", sa.Date(), nullable=False),
            sa.Column("quantidade_litros", sa.Numeric(10, 2), nullable=False),
            sa.Column("valor_litro", sa.Numeric(10, 2), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("criado_em", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["animal_id"], ["animais.id"], name="fk_producoes_animal_id_animais"),
        )
        op.create_index("ix_producoes_animal_id", "producoes", ["animal_id"], unique=False)
        op.create_index("ix_producoes_data_registro", "producoes", ["data_registro"], unique=False)
    else:
        indexes = _indexes("producoes")
        if "ix_producoes_animal_id" not in indexes:
            op.create_index("ix_producoes_animal_id", "producoes", ["animal_id"], unique=False)
        if "ix_producoes_data_registro" not in indexes:
            op.create_index("ix_producoes_data_registro", "producoes", ["data_registro"], unique=False)


def downgrade() -> None:
    tables = _tables()
    if "producoes" in tables:
        op.drop_table("producoes")
    if "animais" in tables:
        op.drop_table("animais")
    if "usuarios" in tables:
        op.drop_table("usuarios")
