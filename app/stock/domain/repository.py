from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from app.shared.events import Envelope
from app.stock.domain.entities import Movement, Reservation, StockItem


class IStockUnitOfWork(ABC):
    """Tudo o que um caso de uso grava (saldo, reserva, movimentações,
    mensagem de resposta na outbox e o registro de mensagem processada)
    só é confirmado junto, em `commit()`. Sair do bloco `with` sem commit
    desfaz tudo."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.rollback()

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    # ── saldo ────────────────────────────────────────────────────────────────

    @abstractmethod
    def list_items(self) -> list[StockItem]: ...

    @abstractmethod
    def get_item(self, part_id: str) -> StockItem | None: ...

    @abstractmethod
    def lock_items(self, part_ids: list[str]) -> dict[str, StockItem]:
        """Busca os saldos travando as linhas até o fim da transação
        (`SELECT ... FOR UPDATE`), sempre na mesma ordem para evitar
        deadlock entre reservas concorrentes. Peças sem saldo cadastrado
        ficam de fora do dicionário."""
        ...

    @abstractmethod
    def add_item(self, item: StockItem) -> bool:
        """Cria o saldo; retorna False (sem erro) se a peça já tiver saldo."""
        ...

    @abstractmethod
    def save_item(self, item: StockItem) -> None: ...

    @abstractmethod
    def add_movement(self, movement: Movement) -> None: ...

    @abstractmethod
    def list_movements(self, part_id: str) -> list[Movement]: ...

    # ── reservas ─────────────────────────────────────────────────────────────

    @abstractmethod
    def get_reservation_by_saga(self, saga_id: str) -> Reservation | None: ...

    @abstractmethod
    def save_reservation(self, reservation: Reservation) -> None: ...

    # ── mensageria ───────────────────────────────────────────────────────────

    @abstractmethod
    def mark_processed(self, message_id: str, message_type: str) -> bool:
        """Registra a mensagem como processada. Retorna False se ela já
        tinha sido processada antes (reentrega): o chamador não deve repetir
        o efeito colateral."""
        ...

    @abstractmethod
    def publish(self, envelope: Envelope) -> None:
        """Grava a mensagem na outbox (publicada no SNS depois do commit, pelo relay)."""
        ...
