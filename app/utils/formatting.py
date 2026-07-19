from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def br_number(value: Any, decimals: int = 2) -> str:
    number = _decimal(value).quantize(Decimal("1." + ("0" * decimals)), rounding=ROUND_HALF_UP)
    raw = f"{number:,.{decimals}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def br_currency(value: Any) -> str:
    return f"R$ {br_number(value, 2)}"


def br_liters(value: Any) -> str:
    return f"{br_number(value, 2)} L"


def br_percent(value: Any) -> str:
    if value is None:
        return "Não calculável"
    return f"{br_number(value, 2)}%"


def br_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def br_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d/%m/%Y %H:%M")


def age_label(birth_date: date | None, reference: date | None = None) -> str:
    if not birth_date:
        return "Não calculável"
    reference = reference or date.today()
    if birth_date > reference:
        return "Não calculável"
    years = reference.year - birth_date.year - ((reference.month, reference.day) < (birth_date.month, birth_date.day))
    if years > 0:
        return f"{years} ano{'s' if years != 1 else ''}"
    months = (reference.year - birth_date.year) * 12 + reference.month - birth_date.month
    if reference.day < birth_date.day:
        months -= 1
    return f"{max(months, 0)} mês{'es' if months != 1 else ''}"


def safe_filename(value: str, fallback: str = "relatorio") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or fallback


def csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
