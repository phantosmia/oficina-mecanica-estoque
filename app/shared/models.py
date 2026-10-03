from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StockItem(Base):
    """Saldo de uma peça. `part_id` é o ID da peça no Catálogo (sem chave
    estrangeira: é outro banco, de outro serviço). `sku` e `name` são cópias
    recebidas no evento `PecaCadastrada`, só para exibição."""

    __tablename__ = "stock_items"
    __table_args__ = (
        # Rede de segurança no banco para a regra que o domínio já garante.
        CheckConstraint("quantity_on_hand >= 0", name="ck_stock_items_on_hand_non_negative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_stock_items_reserved_non_negative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="ck_stock_items_reserved_within_on_hand"),
    )

    part_id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    min_stock_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Reservation(Base):
    """Reserva de peças de uma saga (uma por saga)."""

    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    saga_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["ReservationItem"]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan", order_by="ReservationItem.part_id"
    )


class ReservationItem(Base):
    __tablename__ = "reservation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    # Sem FK para stock_items: uma reserva recusada registra também peças sem saldo cadastrado.
    part_id: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    reservation: Mapped[Reservation] = relationship(back_populates="items")


class StockMovement(Base):
    """Histórico de toda mudança de saldo (auditoria e demonstração da saga)."""

    __tablename__ = "stock_movements"
    __table_args__ = (Index("idx_stock_movements_part_id_created_at", "part_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("stock_items.part_id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessedMessage(Base):
    """Idempotência (docs/saga.md): `message_id` de toda mensagem já tratada,
    gravado na mesma transação do efeito colateral."""

    __tablename__ = "processed_messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    message_type: Mapped[str] = mapped_column(String, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxMessage(Base):
    """Padrão *transactional outbox* (RFC-0007): mensagens a publicar no SNS,
    gravadas na mesma transação da mudança de estado."""

    __tablename__ = "outbox_messages"
    __table_args__ = (
        # Índice parcial: o relay só procura as pendentes.
        Index("idx_outbox_messages_pending", "id", postgresql_where="published_at IS NULL"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    message_type: Mapped[str] = mapped_column(String, nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trace_headers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
