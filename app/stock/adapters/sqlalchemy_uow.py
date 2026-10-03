from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.shared.events import Envelope
from app.shared.models import OutboxMessage, ProcessedMessage
from app.shared.models import Reservation as ReservationORM
from app.shared.models import ReservationItem as ReservationItemORM
from app.shared.models import StockItem as StockItemORM
from app.shared.models import StockMovement as StockMovementORM
from app.shared.tracing import current_trace_headers
from app.stock.domain.entities import Movement, Reservation, ReservationLine, StockItem
from app.stock.domain.repository import IStockUnitOfWork
from app.stock.domain.value_objects import MovementKind, ReservationStatus


def _item_to_entity(orm: StockItemORM) -> StockItem:
    return StockItem(
        part_id=orm.part_id,
        sku=orm.sku,
        name=orm.name,
        on_hand=orm.quantity_on_hand,
        reserved=orm.quantity_reserved,
        min_stock_level=orm.min_stock_level,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _reservation_to_entity(orm: ReservationORM) -> Reservation:
    return Reservation(
        id=orm.id,
        saga_id=orm.saga_id,
        order_id=orm.order_id,
        status=ReservationStatus(orm.status),
        lines=[ReservationLine(part_id=i.part_id, quantity=i.quantity) for i in orm.items],
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


class SqlAlchemyStockUnitOfWork(IStockUnitOfWork):
    """Uma sessão SQLAlchemy = uma transação. Cada `with` abre uma sessão
    nova; `commit()` confirma tudo o que foi gravado nela."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyStockUnitOfWork":
        self._session = self._session_factory()
        return self

    def __exit__(self, *args: object) -> None:
        super().__exit__(*args)  # rollback do que não foi confirmado
        self.session.close()
        self._session = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Unit of work usada fora de um bloco `with`.")
        return self._session

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    # ── saldo ────────────────────────────────────────────────────────────────

    def list_items(self) -> list[StockItem]:
        rows = self.session.scalars(select(StockItemORM).order_by(StockItemORM.name, StockItemORM.part_id))
        return [_item_to_entity(r) for r in rows]

    def get_item(self, part_id: str) -> StockItem | None:
        orm = self.session.get(StockItemORM, part_id)
        return _item_to_entity(orm) if orm else None

    def lock_items(self, part_ids: list[str]) -> dict[str, StockItem]:
        rows = self.session.scalars(
            select(StockItemORM)
            .where(StockItemORM.part_id.in_(part_ids))
            .order_by(StockItemORM.part_id)
            .with_for_update()
        )
        return {r.part_id: _item_to_entity(r) for r in rows}

    def add_item(self, item: StockItem) -> bool:
        result = self.session.execute(
            insert(StockItemORM)
            .values(
                part_id=item.part_id,
                sku=item.sku,
                name=item.name,
                quantity_on_hand=item.on_hand,
                quantity_reserved=item.reserved,
                min_stock_level=item.min_stock_level,
            )
            .on_conflict_do_nothing(index_elements=["part_id"])
            .returning(StockItemORM.part_id)
        )
        # RETURNING em vez de rowcount: num INSERT feito pela sessão ORM, o
        # rowcount não indica de forma confiável se a linha foi inserida.
        return result.scalar() is not None

    def save_item(self, item: StockItem) -> None:
        orm = self.session.get(StockItemORM, item.part_id)
        if orm is None:
            raise LookupError(f"Saldo da peça {item.part_id} não existe.")
        orm.quantity_on_hand = item.on_hand
        orm.quantity_reserved = item.reserved
        orm.min_stock_level = item.min_stock_level
        orm.updated_at = item.updated_at
        self.session.flush()

    def add_movement(self, movement: Movement) -> None:
        self.session.add(
            StockMovementORM(
                part_id=movement.part_id,
                kind=movement.kind.value,
                quantity=movement.quantity,
                reservation_id=movement.reservation_id,
                note=movement.note,
                created_at=movement.created_at,
            )
        )

    def list_movements(self, part_id: str) -> list[Movement]:
        rows = self.session.scalars(
            select(StockMovementORM).where(StockMovementORM.part_id == part_id).order_by(StockMovementORM.id)
        )
        return [
            Movement(
                part_id=r.part_id,
                kind=MovementKind(r.kind),
                quantity=r.quantity,
                created_at=r.created_at,
                reservation_id=r.reservation_id,
                note=r.note,
            )
            for r in rows
        ]

    # ── reservas ─────────────────────────────────────────────────────────────

    def get_reservation_by_saga(self, saga_id: str) -> Reservation | None:
        orm = self.session.scalar(select(ReservationORM).where(ReservationORM.saga_id == saga_id).with_for_update())
        return _reservation_to_entity(orm) if orm else None

    def save_reservation(self, reservation: Reservation) -> None:
        orm = self.session.get(ReservationORM, reservation.id)
        if orm is None:
            orm = ReservationORM(
                id=reservation.id,
                saga_id=reservation.saga_id,
                order_id=reservation.order_id,
                created_at=reservation.created_at,
                items=[ReservationItemORM(part_id=line.part_id, quantity=line.quantity) for line in reservation.lines],
            )
            self.session.add(orm)
        orm.status = reservation.status.value
        orm.updated_at = reservation.updated_at
        self.session.flush()

    # ── mensageria ───────────────────────────────────────────────────────────

    def mark_processed(self, message_id: str, message_type: str) -> bool:
        result = self.session.execute(
            insert(ProcessedMessage)
            .values(message_id=message_id, message_type=message_type)
            .on_conflict_do_nothing(index_elements=["message_id"])
            .returning(ProcessedMessage.message_id)
        )
        return result.scalar() is not None

    def publish(self, envelope: Envelope) -> None:
        self.session.add(
            OutboxMessage(
                message_id=envelope.message_id,
                message_type=envelope.type,
                envelope=envelope.to_dict(),
                trace_headers=current_trace_headers(),
            )
        )
