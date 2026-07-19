from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException, status


def optional_int(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def required_int(value: str | int | None, label: str) -> int:
    parsed = optional_int(value)
    if parsed is None:
        raise ValueError(f"{label} é obrigatório.")
    return parsed


def parse_date(value: str | date | None, label: str = "Data", required: bool = False) -> date | None:
    if isinstance(value, date):
        return value
    cleaned = (value or "").strip()
    if not cleaned:
        if required:
            raise ValueError(f"{label} é obrigatória.")
        return None
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} inválida.") from exc


def parse_decimal(
    value: str | Decimal | int | float | None,
    label: str,
    *,
    required: bool = True,
    positive: bool = False,
    non_negative: bool = False,
    places: int | None = None,
) -> Decimal | None:
    if isinstance(value, Decimal):
        number = value
    else:
        cleaned = "" if value is None else str(value).strip()
        if not cleaned:
            if required:
                raise ValueError(f"{label} é obrigatório.")
            return None
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            number = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"{label} inválido.") from exc
    if positive and number <= 0:
        raise ValueError(f"{label} deve ser maior que zero.")
    if non_negative and number < 0:
        raise ValueError(f"{label} não pode ser negativo.")
    if places is not None:
        quant = Decimal("1." + ("0" * places))
        number = number.quantize(quant, rounding=ROUND_HALF_UP)
    return number


@dataclass(frozen=True)
class Period:
    start: date | None
    end: date | None
    label: str


def resolve_period(preset: str | None, start_raw: str | None, end_raw: str | None, today: date | None = None) -> Period:
    today = today or date.today()
    preset = (preset or "all").strip().lower()
    if preset == "custom":
        start = parse_date(start_raw, "Data inicial")
        end = parse_date(end_raw, "Data final")
        if start and end and start > end:
            raise ValueError("A data inicial não pode ser posterior à data final.")
        label = "Todo o período" if not start and not end else f"{start.strftime('%d/%m/%Y') if start else 'início'} a {end.strftime('%d/%m/%Y') if end else 'hoje'}"
        return Period(start, end, label)
    if preset == "current_month":
        start = today.replace(day=1)
        return Period(start, today, f"Mês atual — {today.strftime('%m/%Y')}")
    if preset == "previous_month":
        first_current = today.replace(day=1)
        end = first_current - timedelta(days=1)
        start = end.replace(day=1)
        return Period(start, end, f"Mês anterior — {end.strftime('%m/%Y')}")
    if preset == "current_year":
        return Period(date(today.year, 1, 1), today, f"Ano atual — {today.year}")
    months_map = {"last_3": 3, "last_6": 6, "last_12": 12}
    if preset in months_map:
        months = months_map[preset]
        month_index = today.year * 12 + today.month - months
        start = date(month_index // 12, month_index % 12 + 1, 1)
        return Period(start, today, f"Últimos {months} meses")
    return Period(None, None, "Todo o período")


def equivalent_previous_period(period: Period) -> Period | None:
    if not period.start or not period.end:
        return None
    days = (period.end - period.start).days + 1
    previous_end = period.start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return Period(previous_start, previous_end, f"{previous_start.strftime('%d/%m/%Y')} a {previous_end.strftime('%d/%m/%Y')}")
