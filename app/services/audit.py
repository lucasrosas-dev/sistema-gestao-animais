from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def _json_default(value: Any):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def compact_json(value: Any | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(obj, field, None) for field in fields}


def record_audit(
    db: Session,
    *,
    user: User | None,
    operation: str,
    entity: str,
    record_id: int | str | None,
    summary: str,
    before: Any | None = None,
    after: Any | None = None,
) -> None:
    db.add(
        AuditLog(
            usuario_id=user.id if user else None,
            operacao=operation,
            entidade=entity,
            registro_id=str(record_id) if record_id is not None else None,
            resumo=summary[:2000],
            antes=compact_json(before),
            depois=compact_json(after),
        )
    )
