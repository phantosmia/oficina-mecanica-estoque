from app.stock.domain.entities import Movement, Reservation, StockItem
from app.stock.schemas import MovementRead, ReservationLineRead, ReservationRead, StockItemRead


def stock_to_response(item: StockItem) -> StockItemRead:
    return StockItemRead(
        part_id=item.part_id,
        sku=item.sku,
        name=item.name,
        quantity_on_hand=item.on_hand,
        quantity_reserved=item.reserved,
        quantity_available=item.available,
        min_stock_level=item.min_stock_level,
        below_minimum=item.below_minimum,
        updated_at=item.updated_at,
    )


def movement_to_response(movement: Movement) -> MovementRead:
    return MovementRead(
        kind=movement.kind.value,
        quantity=movement.quantity,
        reservation_id=movement.reservation_id,
        note=movement.note,
        created_at=movement.created_at,
    )


def reservation_to_response(reservation: Reservation) -> ReservationRead:
    return ReservationRead(
        id=reservation.id,
        saga_id=reservation.saga_id,
        order_id=reservation.order_id,
        status=reservation.status.value,
        items=[ReservationLineRead(part_id=line.part_id, quantity=line.quantity) for line in reservation.lines],
        created_at=reservation.created_at,
        updated_at=reservation.updated_at,
    )
