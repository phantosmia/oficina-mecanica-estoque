"""Testes unitários das regras de saldo (entidade pura, sem banco)."""

import pytest

from app.shared.exceptions import DomainError, InsufficientStockError
from app.stock.domain.entities import StockItem


def item(on_hand: int = 10, reserved: int = 0, min_level: int = 0) -> StockItem:
    return StockItem(part_id="p", sku="P", name="Pastilha", on_hand=on_hand, reserved=reserved, min_stock_level=min_level)


def test_available_is_on_hand_minus_reserved() -> None:
    assert item(10, 3).available == 7


def test_reserve_up_to_available() -> None:
    stock = item(10, 3)
    stock.reserve(7)
    assert (stock.on_hand, stock.reserved, stock.available) == (10, 10, 0)


def test_reserve_more_than_available_is_refused() -> None:
    stock = item(10, 3)
    with pytest.raises(InsufficientStockError, match="disponível 7, pedido 8"):
        stock.reserve(8)
    assert stock.reserved == 3


def test_release_and_withdrawal_only_touch_reserved_units() -> None:
    stock = item(10, 6)
    stock.release(2)
    stock.confirm_withdrawal(4)
    assert (stock.on_hand, stock.reserved) == (6, 0)
    with pytest.raises(DomainError):
        stock.release(1)
    with pytest.raises(DomainError):
        stock.confirm_withdrawal(1)


def test_return_withdrawn_and_entry_increase_on_hand() -> None:
    stock = item(5)
    stock.return_withdrawn(2)
    stock.add_entry(3)
    assert stock.on_hand == 10


@pytest.mark.parametrize("operation", ["reserve", "release", "confirm_withdrawal", "return_withdrawn", "add_entry"])
@pytest.mark.parametrize("quantity", [0, -1])
def test_quantities_must_be_positive(operation: str, quantity: int) -> None:
    with pytest.raises(DomainError, match="maior que zero"):
        getattr(item(10, 5), operation)(quantity)


def test_below_minimum_uses_available_units() -> None:
    assert item(on_hand=10, reserved=6, min_level=5).below_minimum is True
    assert item(on_hand=10, reserved=5, min_level=5).below_minimum is False
