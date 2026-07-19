from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import normalize_database_url  # noqa: E402
from app.models import Animal, Producao  # noqa: E402
from app.schema import upgrade_database  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migra animais e produções de um banco SQLite local para PostgreSQL."
    )
    parser.add_argument(
        "--source",
        default=str(ROOT_DIR / "data" / "sistema_animais.db"),
        help="Caminho do arquivo SQLite de origem.",
    )
    parser.add_argument(
        "--target-url",
        default=os.getenv("DATABASE_URL", ""),
        help="URL do PostgreSQL. Prefira definir DATABASE_URL para não expor a senha no histórico do terminal.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Apaga animais e produções existentes no destino antes da migração. Usuários são preservados.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas valida a origem e mostra as quantidades, sem gravar no destino.",
    )
    return parser.parse_args()


def as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def as_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def read_source(source_path: Path) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not source_path.is_file():
        raise RuntimeError(f"Arquivo de origem não encontrado: {source_path}")

    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        missing = {"animais", "producoes"} - tables
        if missing:
            raise RuntimeError("O arquivo não contém as tabelas esperadas: " + ", ".join(sorted(missing)))

        animais = connection.execute(
            """
            SELECT id, codigo, brinco, nome, sexo, raca, data_nascimento,
                   data_aquisicao, status, observacoes, criado_em
              FROM animais
             ORDER BY id
            """
        ).fetchall()
        producoes = connection.execute(
            """
            SELECT id, animal_id, data_registro, quantidade_litros, valor_litro,
                   observacoes, criado_em
              FROM producoes
             ORDER BY id
            """
        ).fetchall()
        return animais, producoes
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source).expanduser().resolve()
    animais_source, producoes_source = read_source(source_path)

    source_animal_ids = {row["id"] for row in animais_source}
    orphan_count = sum(1 for row in producoes_source if row["animal_id"] not in source_animal_ids)
    if orphan_count:
        raise RuntimeError(f"A origem possui {orphan_count} produção(ões) sem animal correspondente.")

    print(f"Origem: {source_path}")
    print(f"Animais encontrados: {len(animais_source)}")
    print(f"Produções encontradas: {len(producoes_source)}")

    if args.dry_run:
        print("Validação concluída. Nenhum dado foi gravado.")
        return 0

    if not args.target_url:
        raise RuntimeError("DATABASE_URL não foi informada. Defina a variável ou use --target-url.")

    normalized_url = normalize_database_url(args.target_url)
    if not normalized_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("O destino deve ser PostgreSQL.")

    target_engine = create_engine(
        normalized_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=1,
    )
    upgrade_database(target_engine)

    with Session(target_engine) as db:
        target_animals = db.scalar(select(func.count(Animal.id))) or 0
        target_productions = db.scalar(select(func.count(Producao.id))) or 0
        if (target_animals or target_productions) and not args.replace:
            raise RuntimeError(
                "O destino já contém dados. Execute sem alterações ou use --replace somente após confirmar o backup."
            )

        try:
            if args.replace:
                db.execute(delete(Producao))
                db.execute(delete(Animal))
                db.flush()

            id_map: dict[int, int] = {}
            for row in animais_source:
                animal = Animal(
                    codigo=row["codigo"],
                    brinco=row["brinco"],
                    nome=row["nome"],
                    sexo=row["sexo"],
                    raca=row["raca"],
                    data_nascimento=as_date(row["data_nascimento"]),
                    data_aquisicao=as_date(row["data_aquisicao"]),
                    status=row["status"],
                    observacoes=row["observacoes"],
                    criado_em=as_datetime(row["criado_em"]) or datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(animal)
                db.flush()
                id_map[row["id"]] = animal.id

            for row in producoes_source:
                db.add(
                    Producao(
                        animal_id=id_map[row["animal_id"]],
                        data_registro=as_date(row["data_registro"]),
                        quantidade_litros=Decimal(str(row["quantidade_litros"])),
                        valor_litro=(
                            Decimal(str(row["valor_litro"])) if row["valor_litro"] is not None else None
                        ),
                        observacoes=row["observacoes"],
                        criado_em=as_datetime(row["criado_em"]) or datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                )

            db.commit()
        except Exception:
            db.rollback()
            raise

        migrated_animals = db.scalar(select(func.count(Animal.id))) or 0
        migrated_productions = db.scalar(select(func.count(Producao.id))) or 0

    if migrated_animals != len(animais_source) or migrated_productions != len(producoes_source):
        raise RuntimeError(
            "A conferência final não corresponde à origem: "
            f"destino={migrated_animals} animais/{migrated_productions} produções."
        )

    print("Migração concluída e conferida.")
    print(f"Destino: {migrated_animals} animais e {migrated_productions} produções.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
