from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..dependencies import current_user
from ..models import Animal, Custo, EventoAnimal, MovimentacaoAnimal, Producao, Receita
from ..services.exports import csv_response, pdf_response, xlsx_response
from ..services.finance import active_cost_conditions, active_revenue_conditions, date_filter, financial_summary
from ..services.reports import (
    animal_report,
    dashboard_metrics,
    grouped_costs,
    grouped_revenues,
    monthly_report,
    production_cost_report,
)
from ..utils.formatting import br_currency, br_date, br_liters, br_number, br_percent
from ..utils.parsing import Period, resolve_period
from ..web import DBSession, render

router = APIRouter(prefix="/relatorios", tags=["relatórios"])

REPORT_META = {
    "mensal": ("Relatório mensal consolidado", "Visão mensal de produção, vendas, receitas, custos e resultado."),
    "animais": ("Relatório de animais", "Cadastro, produção e resultado financeiro por animal."),
    "producao": ("Relatório de produção", "Produção por animal, médias e últimos lançamentos."),
    "custos": ("Relatório de custos", "Custos por categoria e detalhamento dos lançamentos."),
    "receitas": ("Relatório de receitas", "Receitas por categoria e detalhamento dos lançamentos."),
    "financeiro": ("Resultado financeiro", "Receitas, custos, margem e indicadores por período."),
    "producao-custos": ("Produção versus custo", "Comparação de produção e custos atribuídos por animal."),
    "eventos": ("Eventos e movimentações", "Histórico de eventos, entradas, saídas e alterações de situação."),
}


def report_period(preset: str, data_inicio: str, data_fim: str) -> Period:
    try:
        return resolve_period(preset, data_inicio, data_fim)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_report(db, report_name: str, period: Period, regime: str, year: int | None = None, include_all: bool = False) -> dict[str, Any]:
    regime = regime if regime in {"competencia", "caixa"} else "competencia"
    title, description = REPORT_META.get(report_name, ("Relatório", ""))
    result: dict[str, Any] = {"title": title, "description": description, "summary": [], "headers": [], "raw_rows": [], "display_rows": [], "chart": None}

    if report_name == "mensal":
        year = year or date.today().year
        items = monthly_report(db, year, regime)
        headers = ["Mês", "Produção", "Litros vendidos", "Receita total", "Custo total", "Resultado", "Margem", "Custo/L"]
        raw = [[item["month_name"], item["production_total"], item["liters_sold"], item["revenue_total"], item["cost_total"], item["result"], item["margin"], item["cost_per_liter"]] for item in items]
        display = [[row[0], br_liters(row[1]), br_liters(row[2]), br_currency(row[3]), br_currency(row[4]), br_currency(row[5]), br_percent(row[6]), br_currency(row[7]) if row[7] is not None else "Não calculável"] for row in raw]
        annual = {key: sum((Decimal(item.get(key) or 0) for item in items), Decimal("0")) for key in ["production_total", "liters_sold", "revenue_total", "cost_total", "result"]}
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Ano", year), ("Produção", br_liters(annual["production_total"])), ("Receita", br_currency(annual["revenue_total"])), ("Custos", br_currency(annual["cost_total"])), ("Resultado", br_currency(annual["result"]))], chart={"labels": [item["month_name"][:3] for item in items], "series": [{"label": "Receitas", "values": [float(item["revenue_total"]) for item in items]}, {"label": "Custos", "values": [float(item["cost_total"]) for item in items]}, {"label": "Resultado", "values": [float(item["result"]) for item in items]}]})
        return result

    if report_name == "animais":
        items = animal_report(db, period, include_all=include_all)
        headers = ["Código", "Nome", "Sexo", "Categoria", "Situação", "Produção", "Média", "Custos diretos", "Custos rateados", "Receitas", "Resultado"]
        raw = [[item["animal"].codigo, item["animal"].nome or "", item["animal"].sexo, item["animal"].categoria, item["animal"].status, item["production_total"], item["production_average"], item["direct_cost"], item["allocated_cost"], item["direct_revenue"], item["result_after_allocations"]] for item in items]
        display = [[row[0], row[1] or "—", row[2], row[3], row[4], br_liters(row[5]), br_liters(row[6]) if row[6] is not None else "Não calculável", br_currency(row[7]), br_currency(row[8]), br_currency(row[9]), br_currency(row[10])] for row in raw]
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Animais no relatório", len(items)), ("Período", period.label)])
        return result

    if report_name == "producao":
        conditions = date_filter(Producao.data_registro, period)
        items = db.execute(
            select(Animal.codigo, Animal.nome, func.sum(Producao.quantidade_litros), func.avg(Producao.quantidade_litros), func.count(Producao.id), func.max(Producao.data_registro))
            .join(Producao, Producao.animal_id == Animal.id).where(*conditions)
            .group_by(Animal.id, Animal.codigo, Animal.nome).order_by(func.sum(Producao.quantidade_litros).desc())
        ).all()
        headers = ["Animal", "Nome", "Produção total", "Média", "Lançamentos", "Última produção"]
        raw = [[row[0], row[1] or "", Decimal(row[2] or 0), Decimal(row[3]) if row[3] is not None else None, row[4], row[5]] for row in items]
        display = [[row[0], row[1] or "—", br_liters(row[2]), br_liters(row[3]) if row[3] is not None else "Não calculável", row[4], br_date(row[5])] for row in raw]
        total = sum((row[2] for row in raw), Decimal("0"))
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Produção total", br_liters(total)), ("Animais com produção", len(items))], chart={"labels": [row[0] for row in raw[:20]], "series": [{"label": "Produção", "values": [float(row[2]) for row in raw[:20]]}]})
        return result

    if report_name == "custos":
        conditions = active_cost_conditions(regime, period)
        items = db.scalars(select(Custo).options(joinedload(Custo.animal)).where(*conditions).order_by(Custo.data_competencia.desc(), Custo.id.desc())).all()
        headers = ["Data", "Categoria", "Descrição", "Apropriação", "Animal", "Situação", "Valor"]
        raw = [[item.data_competencia, item.categoria, item.descricao, item.tipo_apropriacao, item.animal.identificacao if item.animal else "", item.situacao, Decimal(item.valor_total)] for item in items]
        display = [[br_date(row[0]), row[1], row[2], row[3], row[4] or "—", row[5], br_currency(row[6])] for row in raw]
        groups = grouped_costs(db, period, regime)
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Total", br_currency(sum((row[6] for row in raw), Decimal("0")))), ("Lançamentos", len(items))], chart={"labels": [item["category"] for item in groups[:12]], "series": [{"label": "Custos", "values": [float(item["value"]) for item in groups[:12]]}]})
        return result

    if report_name == "receitas":
        conditions = active_revenue_conditions(regime, period)
        items = db.scalars(select(Receita).options(joinedload(Receita.animal)).where(*conditions).order_by(Receita.data_competencia.desc(), Receita.id.desc())).all()
        headers = ["Data", "Categoria", "Descrição", "Animal", "Comprador", "Situação", "Valor"]
        raw = [[item.data_competencia, item.categoria, item.descricao, item.animal.identificacao if item.animal else "", item.comprador or "", item.situacao, Decimal(item.valor_total)] for item in items]
        display = [[br_date(row[0]), row[1], row[2], row[3] or "—", row[4] or "—", row[5], br_currency(row[6])] for row in raw]
        groups = grouped_revenues(db, period, regime)
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Total", br_currency(sum((row[6] for row in raw), Decimal("0")))), ("Lançamentos", len(items))], chart={"labels": [item["category"] for item in groups[:12]], "series": [{"label": "Receitas", "values": [float(item["value"]) for item in groups[:12]]}]})
        return result

    if report_name == "financeiro":
        item = dashboard_metrics(db, period, regime, True)
        headers = ["Indicador", "Valor"]
        raw = [
            ["Receita total", item["revenue_total"]], ["Custo total", item["cost_total"]], ["Resultado", item["result"]],
            ["Margem", item["margin"]], ["Produção", item["production_total"]], ["Litros vendidos", item["liters_sold"]],
            ["Custo por litro", item["cost_per_liter"]], ["Receita por litro vendido", item["revenue_per_liter_sold"]],
            ["Resultado por litro", item["result_per_liter"]], ["Receitas pendentes", item["pending_revenue"]], ["Custos pendentes", item["pending_cost"]],
        ]
        display = []
        for label, value in raw:
            if label in {"Margem"}:
                shown = br_percent(value)
            elif label in {"Produção", "Litros vendidos"}:
                shown = br_liters(value)
            else:
                shown = br_currency(value) if value is not None else "Não calculável"
            display.append([label, shown])
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Regime", "Caixa" if regime == "caixa" else "Competência"), ("Período", period.label)], chart={"labels": ["Receita", "Custo", "Resultado"], "series": [{"label": "Valor", "values": [float(item["revenue_total"]), float(item["cost_total"]), float(item["result"])]}]})
        return result

    if report_name == "producao-custos":
        items = production_cost_report(db, period, only_with_activity=not include_all)
        headers = ["Animal", "Produção", "Custo direto", "Custo rateado", "Custo total", "Custo/L", "Receita direta", "Resultado"]
        raw = [[item["animal"].identificacao, item["production_total"], item["direct_cost"], item["allocated_cost"], item["total_cost"], item["cost_per_liter"], item["direct_revenue"], item["result_after_allocations"]] for item in items]
        display = [[row[0], br_liters(row[1]), br_currency(row[2]), br_currency(row[3]), br_currency(row[4]), br_currency(row[5]) if row[5] is not None else "Não calculável", br_currency(row[6]), br_currency(row[7])] for row in raw]
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Animais analisados", len(items)), ("Período", period.label)], chart={"type": "scatter", "points": [{"label": row[0], "x": float(row[1]), "y": float(row[4])} for row in raw]})
        return result

    if report_name == "eventos":
        event_conditions = date_filter(EventoAnimal.data, period)
        movement_conditions = date_filter(MovimentacaoAnimal.data, period)
        events = db.execute(select(EventoAnimal, Animal.codigo).join(Animal, Animal.id == EventoAnimal.animal_id).where(*event_conditions).order_by(EventoAnimal.data.desc())).all()
        movements = db.execute(select(MovimentacaoAnimal, Animal.codigo).join(Animal, Animal.id == MovimentacaoAnimal.animal_id).where(*movement_conditions).order_by(MovimentacaoAnimal.data.desc())).all()
        raw = [[item.data, code, "Evento", item.grupo, item.tipo, item.titulo] for item, code in events] + [[item.data, code, "Movimentação", "", item.tipo, item.motivo or ""] for item, code in movements]
        raw.sort(key=lambda row: row[0], reverse=True)
        headers = ["Data", "Animal", "Natureza", "Grupo", "Tipo", "Descrição"]
        display = [[br_date(row[0]), *row[1:]] for row in raw]
        result.update(headers=headers, raw_rows=raw, display_rows=display, summary=[("Eventos", len(events)), ("Movimentações", len(movements))])
        return result

    raise HTTPException(status_code=404, detail="Relatório não encontrado.")


@router.get("", response_class=HTMLResponse)
def reports_center(request: Request, db: DBSession):
    current_user(request, db)
    return render(request, "relatorios/central.html", reports=REPORT_META)


@router.get("/{report_name}", response_class=HTMLResponse)
def report_view(request: Request, report_name: str, db: DBSession, preset: str = "all", data_inicio: str = "", data_fim: str = "", regime: str = "competencia", ano: int | None = None, mostrar_todos: str = ""):
    current_user(request, db)
    if report_name not in REPORT_META:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    period = report_period(preset, data_inicio, data_fim)
    report = build_report(db, report_name, period, regime, year=ano, include_all=mostrar_todos == "1")
    return render(request, "relatorios/relatorio.html", report=report, report_name=report_name, period=period, preset=preset, data_inicio=data_inicio, data_fim=data_fim, regime=regime, ano=ano or date.today().year, mostrar_todos=mostrar_todos)


@router.get("/{report_name}/{fmt}")
def report_export(request: Request, report_name: str, fmt: str, db: DBSession, preset: str = "all", data_inicio: str = "", data_fim: str = "", regime: str = "competencia", ano: int | None = None, mostrar_todos: str = ""):
    user = current_user(request, db)
    if report_name not in REPORT_META or fmt not in {"xlsx", "csv", "pdf"}:
        raise HTTPException(status_code=404, detail="Exportação não encontrada.")
    period = report_period(preset, data_inicio, data_fim)
    report = build_report(db, report_name, period, regime, year=ano, include_all=mostrar_todos == "1")
    filename = f"{report_name}_{date.today().isoformat()}"
    if fmt == "csv":
        return csv_response(filename, report["headers"], report["raw_rows"])
    if fmt == "xlsx":
        return xlsx_response(filename, report["title"], report["headers"], report["raw_rows"], generated_by=user.display_name, period_label=period.label if report_name != "mensal" else str(ano or date.today().year), filters_label=f"Regime: {regime}", summary=report["summary"])
    return pdf_response(filename, report["title"], report["headers"], report["display_rows"], generated_by=user.display_name, period_label=period.label if report_name != "mensal" else str(ano or date.today().year), landscape_mode=len(report["headers"]) > 6, summary=report["summary"])


@router.get("/animal/{animal_id}/{fmt}")
def individual_animal_export(request: Request, animal_id: int, fmt: str, db: DBSession):
    user = current_user(request, db)
    animal = db.get(Animal, animal_id)
    if not animal:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")
    period = Period(None, None, "Todo o período")
    item = next((row for row in animal_report(db, period, include_all=True) if row["animal"].id == animal_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")
    headers = ["Campo", "Valor"]
    raw = [
        ["Código", animal.codigo], ["Nome", animal.nome or ""], ["Sexo", animal.sexo], ["Raça", animal.raca or ""],
        ["Categoria", animal.categoria], ["Situação", animal.status], ["Data de nascimento", animal.data_nascimento], ["Data de entrada", animal.data_aquisicao],
        ["Origem", animal.origem], ["Produção total", item["production_total"]], ["Média", item["production_average"]],
        ["Custos diretos", item["direct_cost"]], ["Custos rateados", item["allocated_cost"]], ["Receitas diretas", item["direct_revenue"]],
        ["Resultado após rateios", item["result_after_allocations"]], ["Eventos", item["event_count"]], ["Última movimentação", item["last_movement"]],
    ]
    display = [[row[0], br_date(row[1]) if hasattr(row[1], "year") else (br_currency(row[1]) if row[0] in {"Custos diretos", "Custos rateados", "Receitas diretas", "Resultado após rateios"} else br_liters(row[1]) if row[0] in {"Produção total", "Média"} and row[1] is not None else str(row[1] if row[1] is not None else "Não calculável"))] for row in raw]
    filename = f"animal_{animal.codigo}_relatorio"
    if fmt == "xlsx":
        return xlsx_response(filename, f"Relatório do animal {animal.identificacao}", headers, raw, generated_by=user.display_name, period_label="Todo o período")
    if fmt == "pdf":
        return pdf_response(filename, f"Relatório do animal {animal.identificacao}", headers, display, generated_by=user.display_name, period_label="Todo o período")
    raise HTTPException(status_code=404, detail="Formato não suportado.")
