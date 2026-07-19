from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..dependencies import current_user
from ..models import Animal, Producao
from ..services.finance import financial_summary
from ..services.reports import dashboard_metrics, monthly_report
from ..utils.parsing import resolve_period
from ..web import DBSession, render

router = APIRouter()


@router.get("/")
def dashboard_root():
    return RedirectResponse("/painel", status_code=303)


@router.get("/painel", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: DBSession,
    preset: str = "all",
    data_inicio: str = "",
    data_fim: str = "",
    regime: str = "competencia",
    comparar: str = "",
):
    current_user(request, db)
    regime = regime if regime in {"competencia", "caixa"} else "competencia"
    try:
        period = resolve_period(preset, data_inicio, data_fim)
        errors: list[str] = []
    except ValueError as exc:
        period = resolve_period("all", "", "")
        errors = [str(exc)]
    metrics = dashboard_metrics(db, period, regime, comparar == "1")
    today = date.today()
    monthly = monthly_report(db, today.year, regime)
    monthly_chart = {
        'labels': [item['month_name'][:3] for item in monthly],
        'series': [
            {'label': 'Receitas', 'values': [float(item['revenue_total']) for item in monthly]},
            {'label': 'Custos', 'values': [float(item['cost_total']) for item in monthly]},
            {'label': 'Resultado', 'values': [float(item['result']) for item in monthly]},
        ],
    }
    recent = db.scalars(
        select(Producao).options(joinedload(Producao.animal)).order_by(Producao.data_registro.desc(), Producao.id.desc()).limit(8)
    ).all()
    animals = db.execute(select(Animal.id, Animal.codigo, Animal.nome).order_by(Animal.codigo)).all()
    production_rows = db.execute(
        select(Producao.animal_id, Producao.data_registro, Producao.quantidade_litros, Producao.valor_litro)
        .order_by(Producao.data_registro, Producao.animal_id)
    ).all()
    if production_rows:
        first_year = min(row.data_registro.year for row in production_rows)
        last_year = max(row.data_registro.year for row in production_rows)
    else:
        first_year = last_year = today.year
    month_keys = [f"{year:04d}-{month:02d}" for year in range(first_year, last_year + 1) for month in range(1, 13)]
    month_labels = [f"{key[5:7]}/{key[:4]}" for key in month_keys]
    by_animal: dict[int, dict[str, Decimal]] = {row.id: {} for row in animals}
    for row in production_rows:
        key = row.data_registro.strftime("%Y-%m")
        value = Decimal(row.quantidade_litros or 0) * Decimal(row.valor_litro or 0)
        by_animal.setdefault(row.animal_id, {})[key] = by_animal.setdefault(row.animal_id, {}).get(key, Decimal("0")) + value
    datasets = [
        {
            "id": row.id,
            "label": f"{row.codigo} — {row.nome}" if row.nome else row.codigo,
            "values": [float(by_animal.get(row.id, {}).get(key, 0)) for key in month_keys],
        }
        for row in animals
    ]
    return render(
        request,
        "dashboard.html",
        metrics=metrics,
        period=period,
        preset=preset,
        data_inicio=data_inicio,
        data_fim=data_fim,
        regime=regime,
        comparar=comparar,
        errors=errors,
        recent=recent,
        monthly=monthly,
        monthly_chart=monthly_chart,
        financial_month_keys=month_keys,
        financial_month_labels=month_labels,
        financial_animal_datasets=datasets,
    )
