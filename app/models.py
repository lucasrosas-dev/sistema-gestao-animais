from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    # Campos do cadastro completo.
    name = Column(String(120), nullable=True)
    role = Column(String(20), default="Administrador", nullable=False)
    session_version = Column(Integer, default=1, nullable=False)

    @property
    def display_name(self) -> str:
        return self.name or self.username

    @property
    def is_admin(self) -> bool:
        return self.role == "Administrador"

    @property
    def can_write(self) -> bool:
        return self.role in {"Administrador", "Operador"}


class Animal(Base):
    __tablename__ = "animais"

    id = Column(Integer, primary_key=True)
    codigo = Column(String(30), unique=True, index=True, nullable=False)
    brinco = Column(String(30), unique=True, nullable=True)
    nome = Column(String(100), nullable=True)
    sexo = Column(String(20), nullable=False, default="Não informado")
    raca = Column(String(80), nullable=True)
    data_nascimento = Column(Date, nullable=True)
    data_aquisicao = Column(Date, nullable=True)  # Mantido por compatibilidade; representa a entrada.
    status = Column(String(30), default="Ativo", nullable=False, index=True)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)

    origem = Column(String(30), default="Não informado", nullable=False, index=True)
    categoria = Column(String(30), default="Não informado", nullable=False, index=True)
    mae_id = Column(Integer, ForeignKey("animais.id"), nullable=True, index=True)
    pai_id = Column(Integer, ForeignKey("animais.id"), nullable=True, index=True)
    atualizado_em = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    atualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    mae = relationship("Animal", remote_side=[id], foreign_keys=[mae_id], backref="filhos_maternos")
    pai = relationship("Animal", remote_side=[id], foreign_keys=[pai_id], backref="filhos_paternos")
    producoes = relationship("Producao", back_populates="animal", order_by="Producao.data_registro")
    movimentacoes = relationship("MovimentacaoAnimal", back_populates="animal", order_by="MovimentacaoAnimal.data")
    eventos = relationship("EventoAnimal", back_populates="animal", order_by="EventoAnimal.data")
    custos_diretos = relationship("Custo", back_populates="animal", foreign_keys="Custo.animal_id")
    receitas_diretas = relationship("Receita", back_populates="animal", foreign_keys="Receita.animal_id")
    rateios = relationship("RateioCusto", back_populates="animal")

    @property
    def identificacao(self) -> str:
        return f"{self.codigo} — {self.nome}" if self.nome else self.codigo


class Producao(Base):
    __tablename__ = "producoes"

    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey("animais.id"), index=True, nullable=False)
    data_registro = Column(Date, index=True, nullable=False)
    quantidade_litros = Column(Numeric(12, 2), nullable=False)
    valor_litro = Column(Numeric(12, 4), nullable=True)
    observacoes = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)
    atualizado_em = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    atualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    animal = relationship("Animal", back_populates="producoes")
    criado_por = relationship("User", foreign_keys=[criado_por_id])
    atualizado_por = relationship("User", foreign_keys=[atualizado_por_id])

    __table_args__ = (
        CheckConstraint("quantidade_litros > 0", name="ck_producoes_quantidade_positiva"),
        Index("ix_producoes_animal_data", "animal_id", "data_registro"),
    )

    @property
    def valor_total(self) -> Decimal:
        if self.valor_litro is None:
            return Decimal("0.00")
        return Decimal(self.quantidade_litros) * Decimal(self.valor_litro)


class MovimentacaoAnimal(Base):
    __tablename__ = "movimentacoes_animais"

    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey("animais.id"), nullable=False, index=True)
    data = Column(Date, nullable=False, index=True)
    tipo = Column(String(50), nullable=False, index=True)
    situacao_anterior = Column(String(30), nullable=True)
    situacao_posterior = Column(String(30), nullable=True)
    motivo = Column(String(250), nullable=True)
    observacoes = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)

    animal = relationship("Animal", back_populates="movimentacoes")
    usuario = relationship("User")


class EventoAnimal(Base):
    __tablename__ = "eventos_animais"

    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey("animais.id"), nullable=False, index=True)
    data = Column(Date, nullable=False, index=True)
    grupo = Column(String(30), nullable=False, index=True)
    tipo = Column(String(60), nullable=False, index=True)
    titulo = Column(String(160), nullable=False)
    descricao = Column(Text, nullable=True)
    observacoes = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)
    atualizado_em = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    animal = relationship("Animal", back_populates="eventos")
    usuario = relationship("User")


class Custo(Base):
    __tablename__ = "custos"

    id = Column(Integer, primary_key=True)
    data_competencia = Column(Date, nullable=False, index=True)
    data_pagamento = Column(Date, nullable=True, index=True)
    categoria = Column(String(60), nullable=False, index=True)
    descricao = Column(String(250), nullable=False)
    tipo_apropriacao = Column(String(40), nullable=False, index=True)
    animal_id = Column(Integer, ForeignKey("animais.id"), nullable=True, index=True)
    quantidade = Column(Numeric(14, 3), nullable=True)
    unidade_medida = Column(String(30), nullable=True)
    valor_unitario = Column(Numeric(14, 4), nullable=True)
    valor_total = Column(Numeric(14, 2), nullable=False)
    fornecedor = Column(String(160), nullable=True, index=True)
    documento = Column(String(100), nullable=True)
    situacao = Column(String(20), nullable=False, default="Pendente", index=True)
    forma_pagamento = Column(String(30), nullable=True)
    observacoes = Column(Text, nullable=True)
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    atualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cancelado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)
    atualizado_em = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    cancelado_em = Column(DateTime, nullable=True)

    animal = relationship("Animal", back_populates="custos_diretos", foreign_keys=[animal_id])
    rateios = relationship("RateioCusto", back_populates="custo", cascade="all, delete-orphan")
    criado_por = relationship("User", foreign_keys=[criado_por_id])
    atualizado_por = relationship("User", foreign_keys=[atualizado_por_id])
    cancelado_por = relationship("User", foreign_keys=[cancelado_por_id])

    __table_args__ = (
        CheckConstraint("valor_total > 0", name="ck_custos_valor_positivo"),
        Index("ix_custos_competencia_situacao", "data_competencia", "situacao"),
    )


class RateioCusto(Base):
    __tablename__ = "rateios_custos"

    id = Column(Integer, primary_key=True)
    custo_id = Column(Integer, ForeignKey("custos.id"), nullable=False, index=True)
    animal_id = Column(Integer, ForeignKey("animais.id"), nullable=False, index=True)
    metodo = Column(String(40), nullable=False)
    percentual = Column(Numeric(8, 4), nullable=True)
    valor = Column(Numeric(14, 2), nullable=False)
    periodo_inicio = Column(Date, nullable=True)
    periodo_fim = Column(Date, nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)

    custo = relationship("Custo", back_populates="rateios")
    animal = relationship("Animal", back_populates="rateios")

    __table_args__ = (
        UniqueConstraint("custo_id", "animal_id", name="uq_rateio_custo_animal"),
        CheckConstraint("valor >= 0", name="ck_rateios_valor_nao_negativo"),
    )


class Receita(Base):
    __tablename__ = "receitas"

    id = Column(Integer, primary_key=True)
    data_competencia = Column(Date, nullable=False, index=True)
    data_recebimento = Column(Date, nullable=True, index=True)
    categoria = Column(String(60), nullable=False, index=True)
    descricao = Column(String(250), nullable=False)
    animal_id = Column(Integer, ForeignKey("animais.id"), nullable=True, index=True)
    quantidade = Column(Numeric(14, 3), nullable=True)
    unidade_medida = Column(String(30), nullable=True)
    valor_unitario = Column(Numeric(14, 4), nullable=True)
    valor_total = Column(Numeric(14, 2), nullable=False)
    comprador = Column(String(160), nullable=True, index=True)
    documento = Column(String(100), nullable=True)
    situacao = Column(String(20), nullable=False, default="Pendente", index=True)
    forma_recebimento = Column(String(30), nullable=True)
    observacoes = Column(Text, nullable=True)
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    atualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cancelado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False)
    atualizado_em = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    cancelado_em = Column(DateTime, nullable=True)

    animal = relationship("Animal", back_populates="receitas_diretas", foreign_keys=[animal_id])
    criado_por = relationship("User", foreign_keys=[criado_por_id])
    atualizado_por = relationship("User", foreign_keys=[atualizado_por_id])
    cancelado_por = relationship("User", foreign_keys=[cancelado_por_id])

    __table_args__ = (
        CheckConstraint("valor_total > 0", name="ck_receitas_valor_positivo"),
        Index("ix_receitas_competencia_situacao", "data_competencia", "situacao"),
    )


class AuditLog(Base):
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    operacao = Column(String(30), nullable=False, index=True)
    entidade = Column(String(60), nullable=False, index=True)
    registro_id = Column(String(60), nullable=True, index=True)
    resumo = Column(Text, nullable=True)
    antes = Column(Text, nullable=True)
    depois = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False, index=True)

    usuario = relationship("User")


class BackupRecord(Base):
    __tablename__ = "backups"

    id = Column(Integer, primary_key=True)
    ambiente = Column(String(20), nullable=False)
    tipo = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)
    arquivo = Column(String(255), nullable=True)
    tamanho_bytes = Column(Integer, nullable=True)
    schema_version = Column(String(50), nullable=True)
    mensagem = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=utcnow, nullable=False, index=True)

    usuario = relationship("User")
