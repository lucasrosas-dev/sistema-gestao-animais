from __future__ import annotations

from calendar import month_name
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, case, cast, func, literal, select, true
from sqlalchemy.orm import Session

from ..models import Animal, Custo, EventoAnimal, MovimentacaoAnimal, Producao, RateioCusto, Receita
from ..utils.parsing import Period, equivalent_previous_period
from .finance import active_cost_conditions, active_revenue_conditions, date_filter, financial_summary, money

MONTHS_PT = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _percentage_change(current: Decimal | int | None, previous: Decimal | int | None) -> Decimal | None:
    if current is None or previous in (None, 0, Decimal("0")):
        return None
    return (Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100


def dashboard_metrics(db: Session, period: Period, regime: str, compare: bool = False) -> dict[str, Any]:
    summary = financial_summary(db, period, regime)
    animal_date = Animal.data_aquisicao
    animal_added_conditions = date_filter(animal_date, period)
    active_count = func.count(Animal.id).filter(Animal.status == "Ativo")
    added_count = func.count(Animal.id)
    if animal_added_conditions:
        added_count = added_count.filter(*animal_added_conditions)
    animal_summary = select(active_count, added_count).subquery()
    movement_conditions = date_filter(MovimentacaoAnimal.data, period)
    sold_count = func.count(MovimentacaoAnimal.id).filter(MovimentacaoAnimal.tipo == "Venda", *movement_conditions)
    deceased_count = func.count(MovimentacaoAnimal.id).filter(MovimentacaoAnimal.tipo == "Falecimento", *movement_conditions)
    movement_summary = select(sold_count, deceased_count).subquery()
    animals_active, added, sold, deceased = db.execute(
        select(*animal_summary.c, *movement_summary.c)
        .select_from(animal_summary.join(movement_summary, true()))
    ).one()
    animals_active = int(animals_active or 0)
    animals_in_production = int(summary["animals_in_production"] or 0)
    added = int(added or 0)
    sold = int(sold or 0)
    deceased = int(deceased or 0)
    days = ((period.end - period.start).days + 1) if period.start and period.end else None
    summary.update({
        "animals_active": animals_active,
        "animals_in_production": animals_in_production,
        "animals_added": added,
        "animals_sold": sold,
        "animals_deceased": deceased,
        "daily_average": summary["production_total"] / days if days else None,
        "average_per_producing_animal": summary["production_total"] / animals_in_production if animals_in_production else None,
    })
    if compare:
        previous_period = equivalent_previous_period(period)
        if previous_period:
            previous = dashboard_metrics(db, previous_period, regime, False)
            comparison = {}
            for key in ["production_total", "revenue_total", "cost_total", "result", "animals_in_production"]:
                comparison[key] = {
                    "current": summary.get(key),
                    "previous": previous.get(key),
                    "difference": (Decimal(summary.get(key) or 0) - Decimal(previous.get(key) or 0)),
                    "percentage": _percentage_change(summary.get(key), previous.get(key)),
                }
            summary["comparison"] = comparison
            summary["previous_period"] = previous_period
    return summary


def monthly_report(db: Session, year: int, regime: str = "competencia") -> list[dict[str, Any]]:
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)

    production_month = func.extract("month", Producao.data_registro)
    zero = cast(literal(0), Numeric)
    production_query = (
        select(
            literal("production"),
            production_month,
            func.coalesce(func.sum(Producao.quantidade_litros), 0),
            cast(func.count(Producao.id), Numeric),
            cast(func.count(func.distinct(Producao.animal_id)), Numeric),
            zero,
            zero,
        )
        .where(Producao.data_registro >= start, Producao.data_registro < end)
        .group_by(production_month)
    )

    revenue_date = Receita.data_recebimento if regime == "caixa" else Receita.data_competencia
    revenue_month = func.extract("month", revenue_date)
    revenue_conditions = (
        [Receita.situacao == "Recebido", Receita.data_recebimento.is_not(None)]
        if regime == "caixa"
        else [Receita.situacao != "Cancelado"]
    )
    revenue_query = (
        select(
            literal("revenue"),
            revenue_month,
            func.coalesce(func.sum(Receita.valor_total), 0),
            func.coalesce(func.sum(case((Receita.categoria == "Venda de leite", Receita.valor_total), else_=0)), 0),
            func.coalesce(func.sum(case((Receita.categoria == "Venda de leite", Receita.quantidade), else_=0)), 0),
            zero,
            zero,
        )
        .where(*revenue_conditions, revenue_date >= start, revenue_date < end)
        .group_by(revenue_month)
    )

    cost_date = Custo.data_pagamento if regime == "caixa" else Custo.data_competencia
    cost_month = func.extract("month", cost_date)
    cost_conditions = (
        [Custo.situacao == "Pago", Custo.data_pagamento.is_not(None)]
        if regime == "caixa"
        else [Custo.situacao != "Cancelado"]
    )
    cost_query = (
        select(
            literal("cost"),
            cost_month,
            func.coalesce(func.sum(Custo.valor_total), 0),
            func.coalesce(func.sum(case((Custo.tipo_apropriacao == "Custo direto de animal", Custo.valor_total), else_=0)), 0),
            func.coalesce(func.sum(case((Custo.tipo_apropriacao == "Custo de grupo de animais", Custo.valor_total), else_=0)), 0),
            func.coalesce(func.sum(case((Custo.tipo_apropriacao == "Custo geral do rebanho", Custo.valor_total), else_=0)), 0),
            func.coalesce(func.sum(case((Custo.tipo_apropriacao == "Custo não apropriado", Custo.valor_total), else_=0)), 0),
        )
        .where(*cost_conditions, cost_date >= start, cost_date < end)
        .group_by(cost_month)
    )

    production_by_month: dict[int, dict[str, Decimal | int]] = {}
    revenue_by_month: dict[int, dict[str, Decimal]] = {}
    cost_by_month: dict[int, dict[str, Decimal]] = {}
    for row in db.execute(production_query.union_all(revenue_query, cost_query)).all():
        kind, month = row[0], int(row[1])
        if kind == "production":
            production_by_month[month] = {
                "production_total": Decimal(row[2] or 0),
                "entries": int(row[3] or 0),
                "animals_in_production": int(row[4] or 0),
            }
        elif kind == "revenue":
            revenue_by_month[month] = {
                "revenue_total": Decimal(row[2] or 0),
                "milk_revenue": Decimal(row[3] or 0),
                "liters_sold": Decimal(row[4] or 0),
            }
        else:
            cost_by_month[month] = {
                "cost_total": Decimal(row[2] or 0),
                "direct_cost": Decimal(row[3] or 0),
                "allocated_cost": Decimal(row[4] or 0),
                "general_cost": Decimal(row[5] or 0),
                "unappropriated_cost": Decimal(row[6] or 0),
            }

    rows: list[dict[str, Any]] = []
    for month in range(1, 13):
        production = production_by_month.get(month, {})
        revenue = revenue_by_month.get(month, {})
        costs = cost_by_month.get(month, {})
        production_total = Decimal(production.get("production_total", 0))
        entries = int(production.get("entries", 0))
        animals_in_production = int(production.get("animals_in_production", 0))
        revenue_total = Decimal(revenue.get("revenue_total", 0))
        milk_revenue = Decimal(revenue.get("milk_revenue", 0))
        liters_sold = Decimal(revenue.get("liters_sold", 0))
        cost_total = Decimal(costs.get("cost_total", 0))
        result = revenue_total - cost_total
        cost_per_liter = cost_total / production_total if production_total else None
        revenue_per_liter_sold = milk_revenue / liters_sold if liters_sold else None
        rows.append({
            "month": month,
            "month_name": MONTHS_PT[month],
            "year": year,
            "production_total": production_total,
            "entries": entries,
            "animals_in_production": animals_in_production,
            "average_production": production_total / entries if entries else None,
            "revenue_total": money(revenue_total),
            "cost_total": money(cost_total),
            "result": money(result),
            "margin": result / revenue_total * 100 if revenue_total else None,
            "milk_revenue": money(milk_revenue),
            "liters_sold": liters_sold,
            "production_sales_difference": production_total - liters_sold,
            "direct_cost": money(Decimal(costs.get("direct_cost", 0))),
            "allocated_cost": money(Decimal(costs.get("allocated_cost", 0))),
            "general_cost": money(Decimal(costs.get("general_cost", 0))),
            "unappropriated_cost": money(Decimal(costs.get("unappropriated_cost", 0))),
            "cost_per_liter": cost_per_liter,
            "revenue_per_liter_sold": revenue_per_liter_sold,
            "result_per_liter": revenue_per_liter_sold - cost_per_liter if revenue_per_liter_sold is not None and cost_per_liter is not None else None,
        })
    return rows


def animal_report(db: Session, period: Period, include_all: bool = False) -> list[dict[str, Any]]:
    animals_stmt = select(Animal).order_by(Animal.codigo)
    if not include_all:
        animals_stmt = animals_stmt.where(Animal.status == "Ativo")
    animals = db.scalars(animals_stmt).all()
    ids = [item.id for item in animals]
    if not ids:
        return []
    production_rows = db.execute(
        select(Producao.animal_id, func.coalesce(func.sum(Producao.quantidade_litros), 0), func.avg(Producao.quantidade_litros), func.max(Producao.data_registro))
        .where(Producao.animal_id.in_(ids), *date_filter(Producao.data_registro, period))
        .group_by(Producao.animal_id)
    ).all()
    direct_cost_rows = db.execute(
        select(Custo.animal_id, func.coalesce(func.sum(Custo.valor_total), 0))
        .where(Custo.animal_id.in_(ids), Custo.situacao != "Cancelado", *date_filter(Custo.data_competencia, period))
        .group_by(Custo.animal_id)
    ).all()
    allocation_rows = db.execute(
        select(RateioCusto.animal_id, func.coalesce(func.sum(RateioCusto.valor), 0))
        .join(Custo, Custo.id == RateioCusto.custo_id)
        .where(RateioCusto.animal_id.in_(ids), Custo.situacao != "Cancelado", *date_filter(Custo.data_competencia, period))
        .group_by(RateioCusto.animal_id)
    ).all()
    revenue_rows = db.execute(
        select(Receita.animal_id, func.coalesce(func.sum(Receita.valor_total), 0))
        .where(Receita.animal_id.in_(ids), Receita.situacao != "Cancelado", *date_filter(Receita.data_competencia, period))
        .group_by(Receita.animal_id)
    ).all()
    event_rows = dict(db.execute(select(EventoAnimal.animal_id, func.count(EventoAnimal.id)).where(EventoAnimal.animal_id.in_(ids)).group_by(EventoAnimal.animal_id)).all())
    movement_rows = dict(db.execute(select(MovimentacaoAnimal.animal_id, func.max(MovimentacaoAnimal.data)).where(MovimentacaoAnimal.animal_id.in_(ids)).group_by(MovimentacaoAnimal.animal_id)).all())
    production_map = {row[0]: row[1:] for row in production_rows}
    direct_map = dict(direct_cost_rows)
    allocation_map = dict(allocation_rows)
    revenue_map = dict(revenue_rows)
    result = []
    for animal in animals:
        prod_total, prod_avg, last_prod = production_map.get(animal.id, (Decimal("0"), None, None))
        direct_cost = Decimal(direct_map.get(animal.id, 0))
        allocated = Decimal(allocation_map.get(animal.id, 0))
        revenue = Decimal(revenue_map.get(animal.id, 0))
        result.append({
            "animal": animal, "production_total": Decimal(prod_total or 0), "production_average": Decimal(prod_avg) if prod_avg is not None else None,
            "last_production": last_prod, "direct_cost": money(direct_cost), "allocated_cost": money(allocated),
            "direct_revenue": money(revenue), "direct_result": money(revenue - direct_cost),
            "result_after_allocations": money(revenue - direct_cost - allocated), "event_count": event_rows.get(animal.id, 0),
            "last_movement": movement_rows.get(animal.id),
        })
    return result


def production_cost_report(db: Session, period: Period, only_with_activity: bool = True) -> list[dict[str, Any]]:
    rows = animal_report(db, period, include_all=True)
    result = []
    for row in rows:
        total_cost = row["direct_cost"] + row["allocated_cost"]
        production = row["production_total"]
        cost_per_liter = total_cost / production if production else None
        if only_with_activity and production == 0 and total_cost == 0 and row["direct_revenue"] == 0:
            continue
        result.append({**row, "total_cost": total_cost, "cost_per_liter": cost_per_liter})
    return result


def grouped_costs(db: Session, period: Period, regime: str = "competencia") -> list[dict[str, Any]]:
    conditions = active_cost_conditions(regime, period)
    total = Decimal(db.scalar(select(func.coalesce(func.sum(Custo.valor_total), 0)).where(*conditions)) or 0)
    rows = db.execute(select(Custo.categoria, func.sum(Custo.valor_total)).where(*conditions).group_by(Custo.categoria).order_by(func.sum(Custo.valor_total).desc())).all()
    return [{"category": category, "value": money(Decimal(value)), "percentage": (Decimal(value) / total * 100) if total else None} for category, value in rows]


def grouped_revenues(db: Session, period: Period, regime: str = "competencia") -> list[dict[str, Any]]:
    conditions = active_revenue_conditions(regime, period)
    total = Decimal(db.scalar(select(func.coalesce(func.sum(Receita.valor_total), 0)).where(*conditions)) or 0)
    rows = db.execute(select(Receita.categoria, func.sum(Receita.valor_total)).where(*conditions).group_by(Receita.categoria).order_by(func.sum(Receita.valor_total).desc())).all()
    return [{"category": category, "value": money(Decimal(value)), "percentage": (Decimal(value) / total * 100) if total else None} for category, value in rows]
