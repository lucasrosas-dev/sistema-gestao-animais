from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from ..models import Animal, Custo, Producao, RateioCusto, Receita
from ..utils.parsing import Period

COST_CATEGORIES = [
    "Alimentação", "Vacinas", "Medicamentos", "Serviços veterinários", "Reprodução",
    "Mão de obra", "Gestão da atividade", "Energia elétrica", "Água", "Transporte",
    "Manutenção", "Equipamentos", "Materiais", "Impostos e taxas", "Serviços de terceiros",
    "Administração", "Outros",
]
COST_TYPES = ["Custo direto de animal", "Custo geral do rebanho", "Custo de grupo de animais", "Custo não apropriado"]
COST_STATUSES = ["Pendente", "Pago", "Cancelado"]
PAYMENT_METHODS = ["Dinheiro", "Pix", "Transferência", "Boleto", "Cartão", "Outro", "Não informado"]
REVENUE_CATEGORIES = ["Venda de leite", "Venda de animal", "Venda de bezerro", "Venda de esterco ou subproduto", "Indenização", "Outras receitas"]
REVENUE_STATUSES = ["Pendente", "Recebido", "Cancelado"]
ALLOCATION_METHODS = ["Rateio igualitário", "Rateio proporcional à produção", "Rateio percentual manual", "Rateio por valor manual"]


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def date_filter(column, period: Period):
    conditions = []
    if period.start:
        conditions.append(column >= period.start)
    if period.end:
        conditions.append(column <= period.end)
    return conditions


def active_cost_conditions(regime: str, period: Period):
    if regime == "caixa":
        return [Custo.situacao == "Pago", Custo.data_pagamento.is_not(None), *date_filter(Custo.data_pagamento, period)]
    return [Custo.situacao != "Cancelado", *date_filter(Custo.data_competencia, period)]


def active_revenue_conditions(regime: str, period: Period):
    if regime == "caixa":
        return [Receita.situacao == "Recebido", Receita.data_recebimento.is_not(None), *date_filter(Receita.data_recebimento, period)]
    return [Receita.situacao != "Cancelado", *date_filter(Receita.data_competencia, period)]


def calculate_allocations(
    db: Session,
    *,
    total: Decimal,
    method: str,
    animal_ids: list[int],
    competence_date: date,
    percentages: dict[int, Decimal] | None = None,
    values: dict[int, Decimal] | None = None,
) -> list[dict[str, Decimal | int | date | None | str]]:
    unique_ids = list(dict.fromkeys(animal_ids))
    if len(unique_ids) < 2:
        raise ValueError("O custo de grupo exige pelo menos dois animais.")
    existing = set(db.scalars(select(Animal.id).where(Animal.id.in_(unique_ids))).all())
    if existing != set(unique_ids):
        raise ValueError("Um ou mais animais selecionados não existem.")
    total = money(total)
    allocations: list[dict[str, Decimal | int | date | None | str]] = []

    if method == "Rateio igualitário":
        base = money(total / len(unique_ids))
        remaining = total
        for index, animal_id in enumerate(unique_ids):
            value = remaining if index == len(unique_ids) - 1 else base
            remaining -= value
            allocations.append({"animal_id": animal_id, "metodo": method, "percentual": money(value / total * 100) if total else None, "valor": money(value), "periodo_inicio": None, "periodo_fim": None})
        return allocations

    if method == "Rateio proporcional à produção":
        month_start = competence_date.replace(day=1)
        if competence_date.month == 12:
            month_end = date(competence_date.year + 1, 1, 1)
        else:
            month_end = date(competence_date.year, competence_date.month + 1, 1)
        production_rows = db.execute(
            select(Producao.animal_id, func.coalesce(func.sum(Producao.quantidade_litros), 0))
            .where(Producao.animal_id.in_(unique_ids), Producao.data_registro >= month_start, Producao.data_registro < month_end)
            .group_by(Producao.animal_id)
        ).all()
        by_animal = {animal_id: Decimal(qty) for animal_id, qty in production_rows}
        total_production = sum(by_animal.values(), Decimal("0"))
        if total_production <= 0:
            raise ValueError("Não há produção registrada para os animais no mês da competência. O rateio proporcional não pode ser calculado.")
        remaining = total
        for index, animal_id in enumerate(unique_ids):
            proportion = by_animal.get(animal_id, Decimal("0")) / total_production
            value = remaining if index == len(unique_ids) - 1 else money(total * proportion)
            remaining -= value
            allocations.append({"animal_id": animal_id, "metodo": method, "percentual": (proportion * 100).quantize(Decimal("0.0001")), "valor": money(value), "periodo_inicio": month_start, "periodo_fim": month_end})
        return allocations

    if method == "Rateio percentual manual":
        percentages = percentages or {}
        total_percent = sum((percentages.get(item, Decimal("0")) for item in unique_ids), Decimal("0"))
        if abs(total_percent - Decimal("100")) > Decimal("0.0001"):
            raise ValueError("A soma dos percentuais deve corresponder exatamente a 100%.")
        remaining = total
        for index, animal_id in enumerate(unique_ids):
            percent = percentages.get(animal_id, Decimal("0"))
            value = remaining if index == len(unique_ids) - 1 else money(total * percent / 100)
            remaining -= value
            allocations.append({"animal_id": animal_id, "metodo": method, "percentual": percent, "valor": money(value), "periodo_inicio": None, "periodo_fim": None})
        return allocations

    if method == "Rateio por valor manual":
        values = values or {}
        total_values = sum((money(values.get(item, Decimal("0"))) for item in unique_ids), Decimal("0"))
        if total_values != total:
            raise ValueError(f"A soma dos valores rateados deve corresponder ao custo total ({total}).")
        for animal_id in unique_ids:
            value = money(values.get(animal_id, Decimal("0")))
            allocations.append({"animal_id": animal_id, "metodo": method, "percentual": (value / total * 100).quantize(Decimal("0.0001")) if total else None, "valor": value, "periodo_inicio": None, "periodo_fim": None})
        return allocations

    raise ValueError("Método de rateio inválido.")


def apply_allocations(custo: Custo, allocations: list[dict]) -> None:
    custo.rateios.clear()
    for item in allocations:
        custo.rateios.append(RateioCusto(**item))


def _filtered(aggregate, conditions):
    return aggregate.filter(*conditions) if conditions else aggregate


def financial_summary(db: Session, period: Period, regime: str = "competencia") -> dict[str, Decimal | int | None]:
    cost_conditions = active_cost_conditions(regime, period)
    revenue_conditions = active_revenue_conditions(regime, period)
    production_conditions = date_filter(Producao.data_registro, period)
    pending_revenue_conditions = [Receita.situacao == "Pendente", *date_filter(Receita.data_competencia, period)]
    pending_cost_conditions = [Custo.situacao == "Pendente", *date_filter(Custo.data_competencia, period)]

    revenue_summary = select(
        func.coalesce(_filtered(func.sum(Receita.valor_total), revenue_conditions), 0),
        func.coalesce(_filtered(func.sum(Receita.valor_total), [*revenue_conditions, Receita.categoria == "Venda de leite"]), 0),
        func.coalesce(_filtered(func.sum(Receita.quantidade), [*revenue_conditions, Receita.categoria == "Venda de leite"]), 0),
        func.coalesce(_filtered(func.sum(Receita.valor_total), pending_revenue_conditions), 0),
    ).subquery()

    cost_summary = select(
        func.coalesce(_filtered(func.sum(Custo.valor_total), cost_conditions), 0),
        func.coalesce(_filtered(func.sum(Custo.valor_total), pending_cost_conditions), 0),
        func.coalesce(_filtered(func.sum(Custo.valor_total), [*cost_conditions, Custo.tipo_apropriacao == "Custo direto de animal"]), 0),
        func.coalesce(_filtered(func.sum(Custo.valor_total), [*cost_conditions, Custo.tipo_apropriacao == "Custo geral do rebanho"]), 0),
        func.coalesce(_filtered(func.sum(Custo.valor_total), [*cost_conditions, Custo.tipo_apropriacao == "Custo não apropriado"]), 0),
        func.coalesce(_filtered(func.sum(Custo.valor_total), [*cost_conditions, Custo.tipo_apropriacao == "Custo de grupo de animais"]), 0),
    ).subquery()

    production_summary = select(
        func.coalesce(_filtered(func.sum(Producao.quantidade_litros), production_conditions), 0),
        _filtered(func.count(Producao.id), production_conditions),
        _filtered(func.count(func.distinct(Producao.animal_id)), production_conditions),
    ).subquery()

    summary_row = db.execute(
        select(*revenue_summary.c, *cost_summary.c, *production_summary.c)
        .select_from(revenue_summary.join(cost_summary, true()).join(production_summary, true()))
    ).one()
    revenue_total, milk_revenue, liters_sold, pending_revenue = (Decimal(value or 0) for value in summary_row[0:4])
    cost_total, pending_cost, direct_cost, general_cost, unappropriated_cost, group_cost = (Decimal(value or 0) for value in summary_row[4:10])
    production_total = Decimal(summary_row[10] or 0)
    entries = int(summary_row[11] or 0)
    animals_in_production = int(summary_row[12] or 0)

    result = revenue_total - cost_total
    margin = result / revenue_total * 100 if revenue_total else None
    cost_per_liter = cost_total / production_total if production_total else None
    revenue_per_liter_sold = milk_revenue / liters_sold if liters_sold else None
    result_per_liter = revenue_per_liter_sold - cost_per_liter if revenue_per_liter_sold is not None and cost_per_liter is not None else None
    average_production = production_total / entries if entries else None

    return {
        "revenue_total": money(revenue_total), "cost_total": money(cost_total), "result": money(result),
        "margin": margin, "production_total": production_total, "entries": entries,
        "animals_in_production": animals_in_production,
        "average_production": average_production, "milk_revenue": money(milk_revenue),
        "liters_sold": liters_sold, "production_sales_difference": production_total - liters_sold,
        "pending_revenue": money(pending_revenue), "pending_cost": money(pending_cost),
        "direct_cost": money(direct_cost), "allocated_cost": money(group_cost),
        "general_cost": money(general_cost), "unappropriated_cost": money(unappropriated_cost),
        "cost_per_liter": cost_per_liter, "revenue_per_liter_sold": revenue_per_liter_sold,
        "result_per_liter": result_per_liter,
    }
