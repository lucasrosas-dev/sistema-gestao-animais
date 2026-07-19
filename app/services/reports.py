from __future__ import annotations

from calendar import month_name
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
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
    animals_active = int(db.scalar(select(func.count(Animal.id)).where(Animal.status == "Ativo")) or 0)
    animals_in_production = int(db.scalar(select(func.count(func.distinct(Producao.animal_id))).where(*date_filter(Producao.data_registro, period))) or 0)
    added = int(db.scalar(select(func.count(Animal.id)).where(*animal_added_conditions)) or 0)
    sold = int(db.scalar(select(func.count(MovimentacaoAnimal.id)).where(MovimentacaoAnimal.tipo == "Venda", *date_filter(MovimentacaoAnimal.data, period))) or 0)
    deceased = int(db.scalar(select(func.count(MovimentacaoAnimal.id)).where(MovimentacaoAnimal.tipo == "Falecimento", *date_filter(MovimentacaoAnimal.data, period))) or 0)
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
    rows: list[dict[str, Any]] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        period = Period(start, end, f"{MONTHS_PT[month]}/{year}")
        item = dashboard_metrics(db, period, regime, False)
        item.update({"month": month, "month_name": MONTHS_PT[month], "year": year})
        rows.append(item)
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
