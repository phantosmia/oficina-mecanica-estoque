"""Casos de uso administrativos (API REST)."""

from datetime import UTC, datetime

from app.shared.exceptions import DomainError, NotFoundError
from app.stock.domain.entities import Movement, Reservation, StockItem
from app.stock.domain.repository import IStockUnitOfWork
from app.stock.domain.value_objects import MovementKind


class ListStockUseCase:
    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, below_minimum: bool = False) -> list[StockItem]:
        with self._uow as uow:
            items = uow.list_items()
        return [i for i in items if i.below_minimum] if below_minimum else items


class GetStockUseCase:
    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, part_id: str) -> StockItem:
        with self._uow as uow:
            item = uow.get_item(part_id)
        if item is None:
            raise NotFoundError("Saldo da peça", part_id)
        return item


class RegisterEntryUseCase:
    """Entrada de estoque (reposição): aumenta o que está em estoque."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, part_id: str, quantity: int, note: str | None = None) -> StockItem:
        with self._uow as uow:
            item = uow.lock_items([part_id]).get(part_id)
            if item is None:
                raise NotFoundError("Saldo da peça", part_id)
            now = datetime.now(UTC)
            item.add_entry(quantity)
            item.updated_at = now
            uow.save_item(item)
            uow.add_movement(Movement(part_id=part_id, kind=MovementKind.ENTRY, quantity=quantity, created_at=now, note=note))
            uow.commit()
        return item


class SetMinimumLevelUseCase:
    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, part_id: str, min_stock_level: int) -> StockItem:
        if min_stock_level < 0:
            raise DomainError("O estoque mínimo não pode ser negativo.")
        with self._uow as uow:
            item = uow.lock_items([part_id]).get(part_id)
            if item is None:
                raise NotFoundError("Saldo da peça", part_id)
            item.min_stock_level = min_stock_level
            item.updated_at = datetime.now(UTC)
            uow.save_item(item)
            uow.commit()
        return item


class ListMovementsUseCase:
    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, part_id: str) -> list[Movement]:
        with self._uow as uow:
            if uow.get_item(part_id) is None:
                raise NotFoundError("Saldo da peça", part_id)
            return uow.list_movements(part_id)


class GetReservationUseCase:
    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, saga_id: str) -> Reservation:
        with self._uow as uow:
            reservation = uow.get_reservation_by_saga(saga_id)
        if reservation is None:
            raise NotFoundError("Reserva", saga_id)
        return reservation
