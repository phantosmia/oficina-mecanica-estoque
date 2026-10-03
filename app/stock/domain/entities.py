from dataclasses import dataclass, field
from datetime import datetime

from app.shared.exceptions import DomainError, InsufficientStockError
from app.stock.domain.value_objects import MovementKind, ReservationStatus


def _ensure_positive(quantity: int) -> None:
    if quantity <= 0:
        raise DomainError("A quantidade deve ser maior que zero.")


@dataclass
class StockItem:
    """Saldo de uma peça. Invariante: 0 <= reservado <= em estoque.

    - em estoque (`on_hand`): unidades fisicamente na oficina;
    - reservado: parte do que está em estoque prometida a uma OS (saga) que
      ainda não fez a baixa;
    - disponível: o que pode ser reservado agora.
    """

    part_id: str
    sku: str
    name: str
    on_hand: int = 0
    reserved: int = 0
    min_stock_level: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    @property
    def below_minimum(self) -> bool:
        return self.available < self.min_stock_level

    def add_entry(self, quantity: int) -> None:
        _ensure_positive(quantity)
        self.on_hand += quantity

    def reserve(self, quantity: int) -> None:
        _ensure_positive(quantity)
        if quantity > self.available:
            raise InsufficientStockError(
                f"Estoque insuficiente para a peça {self.name}: disponível {self.available}, pedido {quantity}."
            )
        self.reserved += quantity

    def release(self, quantity: int) -> None:
        """Desfaz uma reserva (compensação de `reserve`)."""
        _ensure_positive(quantity)
        if quantity > self.reserved:
            raise DomainError(f"Não há {quantity} unidades reservadas da peça {self.name} para liberar.")
        self.reserved -= quantity

    def confirm_withdrawal(self, quantity: int) -> None:
        """Transforma unidades reservadas em baixa definitiva."""
        _ensure_positive(quantity)
        if quantity > self.reserved:
            raise DomainError(f"Não há {quantity} unidades reservadas da peça {self.name} para dar baixa.")
        self.reserved -= quantity
        self.on_hand -= quantity

    def return_withdrawn(self, quantity: int) -> None:
        """Devolve ao estoque unidades já baixadas (compensação de `confirm_withdrawal`)."""
        _ensure_positive(quantity)
        self.on_hand += quantity


@dataclass(frozen=True)
class ReservationLine:
    part_id: str
    quantity: int


@dataclass
class Reservation:
    id: str
    saga_id: str
    order_id: int
    status: ReservationStatus
    lines: list[ReservationLine]
    created_at: datetime
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Movement:
    part_id: str
    kind: MovementKind
    quantity: int
    created_at: datetime
    reservation_id: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Unavailability:
    """Por que uma peça não pôde ser reservada (vai no evento ReservaRecusada)."""

    part_id: str
    requested: int
    available: int
    reason: str = field(default="estoque_insuficiente")
