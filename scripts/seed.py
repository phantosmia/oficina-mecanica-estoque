"""Carga idempotente do saldo inicial das peças de exemplo.

As peças são as mesmas dos dados de exemplo do Catálogo
(`oficina-mecanica-catalogo/scripts/seed.py`), com os mesmos IDs: UUID v5
do SKU no mesmo namespace. Por isso dá para semear o saldo sem consultar o
Catálogo nem esperar o evento `PecaCadastrada` (que, se chegar depois, é
ignorado: o saldo já existe). As quantidades são as do monólito das fases
anteriores. Peça que já tem saldo não é alterada.

Uso: `python -m scripts.seed`
"""

import logging
import uuid
from datetime import UTC, datetime

from app.shared.database import get_session_factory
from app.stock.adapters.sqlalchemy_uow import SqlAlchemyStockUnitOfWork
from app.stock.domain.entities import Movement, StockItem
from app.stock.domain.value_objects import MovementKind

# Mesmo namespace do Catálogo: não mudar sem mudar lá também.
SEED_NAMESPACE = uuid.UUID("6f1c2e4a-9b3d-4f5e-8a7c-1d2e3f4a5b6c")

# (nome, SKU, quantidade em estoque, estoque mínimo)
PARTS = [
    ("Óleo sintético 5W30", "OLEO-5W30-1L", 50, 10),
    ("Filtro de óleo", "FILTRO-OLEO-GENERIC", 30, 5),
    ("Pastilha de freio dianteira", "PAST-FREIO-DIAN", 20, 3),
    ("Disco de freio", "DISCO-FREIO-DIAN", 15, 2),
    ("Filtro de ar", "FILTRO-AR-GENERIC", 25, 5),
]


def part_id_for(sku: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, f"part:{sku}"))


def seed() -> int:
    """Retorna quantos saldos foram criados."""
    created = 0
    with SqlAlchemyStockUnitOfWork(get_session_factory()) as uow:
        now = datetime.now(UTC)
        for name, sku, quantity, minimum in PARTS:
            part_id = part_id_for(sku)
            if uow.add_item(StockItem(part_id=part_id, sku=sku, name=name, on_hand=quantity, min_stock_level=minimum)):
                uow.add_movement(Movement(part_id, MovementKind.ENTRY, quantity, now, note="saldo inicial (dados de exemplo)"))
                created += 1
        uow.commit()
    return created


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("seed").info("dados de exemplo: %s saldos criados", seed())
