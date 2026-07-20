from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models import Animal, Custo, Producao, Receita
from app.services.reports import dashboard_metrics, monthly_report
from app.utils.parsing import Period
from conftest import login


def seed_financial_scenario() -> tuple[int, int]:
    year = date.today().year
    with SessionLocal() as db:
        animal = Animal(
            codigo="PERF-001",
            nome="Teste do painel",
            sexo="Fêmea",
            origem="Compra",
            categoria="Vaca",
            status="Ativo",
            data_aquisicao=date(year, 1, 2),
        )
        db.add(animal)
        db.flush()
        db.add(Producao(
            animal_id=animal.id,
            data_registro=date(year, 1, 10),
            quantidade_litros=Decimal("100.00"),
            valor_litro=Decimal("2.5000"),
        ))
        db.add_all([
            Receita(
                data_competencia=date(year, 1, 15),
                data_recebimento=date(year, 2, 5),
                categoria="Venda de leite",
                descricao="Leite recebido em fevereiro",
                quantidade=Decimal("80.000"),
                valor_total=Decimal("240.00"),
                situacao="Recebido",
            ),
            Receita(
                data_competencia=date(year, 1, 20),
                categoria="Outras receitas",
                descricao="Receita pendente",
                valor_total=Decimal("100.00"),
                situacao="Pendente",
            ),
            Receita(
                data_competencia=date(year, 1, 21),
                categoria="Venda de leite",
                descricao="Receita cancelada",
                quantidade=Decimal("999.000"),
                valor_total=Decimal("999.00"),
                situacao="Cancelado",
            ),
            Custo(
                data_competencia=date(year, 1, 12),
                data_pagamento=date(year, 2, 6),
                categoria="Alimentação",
                descricao="Custo pago em fevereiro",
                tipo_apropriacao="Custo direto de animal",
                animal_id=animal.id,
                valor_total=Decimal("50.00"),
                situacao="Pago",
            ),
            Custo(
                data_competencia=date(year, 1, 18),
                categoria="Energia elétrica",
                descricao="Custo pendente",
                tipo_apropriacao="Custo geral do rebanho",
                valor_total=Decimal("20.00"),
                situacao="Pendente",
            ),
            Custo(
                data_competencia=date(year, 1, 19),
                categoria="Outros",
                descricao="Custo cancelado",
                tipo_apropriacao="Custo não apropriado",
                valor_total=Decimal("999.00"),
                situacao="Cancelado",
            ),
        ])
        db.commit()
    return year, animal.id


def test_dashboard_aggregates_preserve_financial_results(client):
    year, _ = seed_financial_scenario()
    january = Period(date(year, 1, 1), date(year, 1, 31), "Janeiro")

    with SessionLocal() as db:
        metrics = dashboard_metrics(db, january, "competencia")
        competence = monthly_report(db, year, "competencia")
        cash = monthly_report(db, year, "caixa")

    assert metrics["production_total"] == Decimal("100.00")
    assert metrics["animals_in_production"] == 1
    assert metrics["revenue_total"] == Decimal("340.00")
    assert metrics["cost_total"] == Decimal("70.00")
    assert metrics["result"] == Decimal("270.00")
    assert metrics["liters_sold"] == Decimal("80.000")
    assert metrics["pending_revenue"] == Decimal("100.00")
    assert metrics["pending_cost"] == Decimal("20.00")
    assert metrics["direct_cost"] == Decimal("50.00")
    assert metrics["general_cost"] == Decimal("20.00")

    january_competence = competence[0]
    assert january_competence["production_total"] == Decimal("100.00")
    assert january_competence["revenue_total"] == Decimal("340.00")
    assert january_competence["cost_total"] == Decimal("70.00")
    assert january_competence["result"] == Decimal("270.00")
    assert january_competence["liters_sold"] == Decimal("80.000")

    january_cash, february_cash = cash[0], cash[1]
    assert january_cash["revenue_total"] == Decimal("0.00")
    assert january_cash["cost_total"] == Decimal("0.00")
    assert february_cash["revenue_total"] == Decimal("240.00")
    assert february_cash["cost_total"] == Decimal("50.00")
    assert february_cash["result"] == Decimal("190.00")


def test_panel_query_count_stays_bounded(client):
    seed_financial_scenario()
    assert login(client).status_code == 303
    statements: list[str] = []

    def count_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        response = client.get("/painel")
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert response.status_code == 200
    assert "Painel gerencial" in response.text
    assert len(statements) <= 8
