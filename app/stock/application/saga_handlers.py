"""Participação do Estoque na saga da OS (contrato em docs/saga.md, no
repositório oficina-mecanica-fiap).

Cada handler recebe uma mensagem já decodificada e, numa única transação:
registra o `message_id` como processado (idempotência), aplica o efeito no
saldo e grava a resposta na outbox. Uma reentrega da mesma mensagem não faz
nada; um comando repetido com outro `message_id` (o orquestrador reenvia
depois do prazo) devolve a mesma resposta, sem repetir o efeito.

Falha de negócio (faltou saldo, reserva inexistente) vira um evento de
falha, nunca uma exceção: exceção é para falha técnica, e faz a mensagem
voltar para a fila.
"""

import logging
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import uuid

from app.shared.events import Envelope
from app.stock.domain.entities import Movement, Reservation, ReservationLine, StockItem, Unavailability
from app.stock.domain.repository import IStockUnitOfWork
from app.stock.domain.value_objects import MovementKind, ReservationStatus

logger = logging.getLogger(__name__)


def _reply(command: Envelope, event_type: str, payload: dict) -> Envelope:
    return Envelope(type=event_type, payload=payload, saga_id=command.saga_id, order_id=command.order_id)


def _lines_payload(reservation: Reservation) -> list[dict]:
    return [{"part_id": line.part_id, "quantity": line.quantity} for line in reservation.lines]


class RegisterPartUseCase:
    """Evento `PecaCadastrada` do Catálogo: cria o saldo zerado da peça."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, event: Envelope) -> None:
        with self._uow as uow:
            if not uow.mark_processed(event.message_id, event.type):
                return
            payload = event.payload
            created = uow.add_item(
                StockItem(part_id=payload["part_id"], sku=payload["sku"], name=payload["name"], created_at=datetime.now(UTC))
            )
            if not created:
                logger.info("saldo da peça %s já existia; PecaCadastrada ignorado", payload["part_id"])
            uow.commit()


class ReservePartsUseCase:
    """`ReservarPecas`: reserva todas as peças do diagnóstico, tudo ou nada."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, command: Envelope) -> None:
        with self._uow as uow:
            if not uow.mark_processed(command.message_id, command.type):
                return
            existing = uow.get_reservation_by_saga(command.saga_id)
            if existing is not None:
                uow.publish(self._reply_for_existing(command, existing))
                uow.commit()
                return

            requested = Counter[str]()
            for item in command.payload.get("items", []):
                requested[item["part_id"]] += int(item["quantity"])
            lines = [ReservationLine(part_id=p, quantity=q) for p, q in sorted(requested.items())]
            now = datetime.now(UTC)
            reservation = Reservation(
                id=str(uuid.uuid4()),
                saga_id=command.saga_id,
                order_id=command.order_id,
                status=ReservationStatus.RESERVED,
                lines=lines,
                created_at=now,
            )

            if any(line.quantity <= 0 for line in lines):
                reservation.status = ReservationStatus.REFUSED
                uow.save_reservation(reservation)
                uow.publish(_reply(command, "ReservaRecusada", {"reservation_id": reservation.id, "reason": "quantidade_invalida", "unavailable": []}))
                uow.commit()
                return

            stock = uow.lock_items([line.part_id for line in lines])
            unavailable = [u for line in lines if (u := self._check(line, stock.get(line.part_id))) is not None]
            if unavailable:
                reservation.status = ReservationStatus.REFUSED
                uow.save_reservation(reservation)
                uow.publish(
                    _reply(
                        command,
                        "ReservaRecusada",
                        {
                            "reservation_id": reservation.id,
                            "reason": "estoque_insuficiente",
                            "unavailable": [asdict(u) for u in unavailable],
                        },
                    )
                )
                uow.commit()
                return

            for line in lines:
                item = stock[line.part_id]
                item.reserve(line.quantity)
                item.updated_at = now
                uow.save_item(item)
                uow.add_movement(Movement(line.part_id, MovementKind.RESERVE, line.quantity, now, reservation.id))
            uow.save_reservation(reservation)
            uow.publish(_reply(command, "PecasReservadas", {"reservation_id": reservation.id, "items": _lines_payload(reservation)}))
            uow.commit()

    @staticmethod
    def _check(line: ReservationLine, item: StockItem | None) -> Unavailability | None:
        if item is None:
            return Unavailability(part_id=line.part_id, requested=line.quantity, available=0, reason="peca_sem_saldo_cadastrado")
        if item.available < line.quantity:
            return Unavailability(part_id=line.part_id, requested=line.quantity, available=item.available)
        return None

    @staticmethod
    def _reply_for_existing(command: Envelope, reservation: Reservation) -> Envelope:
        if reservation.status in (ReservationStatus.RESERVED, ReservationStatus.CONFIRMED):
            return _reply(command, "PecasReservadas", {"reservation_id": reservation.id, "items": _lines_payload(reservation)})
        # REFUSED, ou RELEASED/RETURNED: a saga já foi compensada antes deste
        # comando chegar (fora de ordem). Reservar agora prenderia estoque
        # que ninguém mais vai liberar.
        reason = "estoque_insuficiente" if reservation.status == ReservationStatus.REFUSED else "saga_ja_compensada"
        return _reply(command, "ReservaRecusada", {"reservation_id": reservation.id, "reason": reason, "unavailable": []})


class ConfirmWithdrawalUseCase:
    """`ConfirmarBaixa`: a reserva vira baixa definitiva (depois do pagamento)."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, command: Envelope) -> None:
        with self._uow as uow:
            if not uow.mark_processed(command.message_id, command.type):
                return
            reservation = uow.get_reservation_by_saga(command.saga_id)
            if reservation is None or reservation.status not in (ReservationStatus.RESERVED, ReservationStatus.CONFIRMED):
                reason = "reserva_inexistente" if reservation is None else f"reserva_{reservation.status.value}"
                uow.publish(_reply(command, "BaixaFalhou", {"reason": reason}))
                uow.commit()
                return
            if reservation.status == ReservationStatus.RESERVED:
                _apply(uow, reservation, MovementKind.WITHDRAWAL, ReservationStatus.CONFIRMED)
            uow.publish(_reply(command, "BaixaConfirmada", {"reservation_id": reservation.id, "items": _lines_payload(reservation)}))
            uow.commit()


class ReleasePartsUseCase:
    """`LiberarPecas` (compensação de ReservarPecas). Sempre confirma com
    `PecasLiberadas`, mesmo sem nada a desfazer (docs/saga.md)."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, command: Envelope) -> None:
        with self._uow as uow:
            if not uow.mark_processed(command.message_id, command.type):
                return
            reservation = uow.get_reservation_by_saga(command.saga_id)
            if reservation is None:
                # Liberação chegou antes da reserva (fora de ordem): registra a
                # saga como já compensada, para uma reserva atrasada ser recusada.
                _save_tombstone(uow, command)
            elif reservation.status == ReservationStatus.RESERVED:
                _apply(uow, reservation, MovementKind.RELEASE, ReservationStatus.RELEASED)
            elif reservation.status == ReservationStatus.CONFIRMED:
                logger.warning("LiberarPecas para reserva já baixada (saga %s): devolvendo as peças ao estoque", command.saga_id)
                _apply(uow, reservation, MovementKind.RETURN, ReservationStatus.RETURNED)
            uow.publish(_reply(command, "PecasLiberadas", {}))
            uow.commit()


class ReturnPartsUseCase:
    """`DevolverPecas` (compensação de ConfirmarBaixa). Sempre confirma com
    `PecasDevolvidas`, mesmo sem nada a desfazer."""

    def __init__(self, uow: IStockUnitOfWork) -> None:
        self._uow = uow

    def execute(self, command: Envelope) -> None:
        with self._uow as uow:
            if not uow.mark_processed(command.message_id, command.type):
                return
            reservation = uow.get_reservation_by_saga(command.saga_id)
            if reservation is None:
                _save_tombstone(uow, command)
            elif reservation.status == ReservationStatus.CONFIRMED:
                _apply(uow, reservation, MovementKind.RETURN, ReservationStatus.RETURNED)
            elif reservation.status == ReservationStatus.RESERVED:
                # A baixa nunca chegou a acontecer: basta desfazer a reserva.
                _apply(uow, reservation, MovementKind.RELEASE, ReservationStatus.RELEASED)
            uow.publish(_reply(command, "PecasDevolvidas", {}))
            uow.commit()


def _apply(uow: IStockUnitOfWork, reservation: Reservation, kind: MovementKind, new_status: ReservationStatus) -> None:
    now = datetime.now(UTC)
    stock = uow.lock_items([line.part_id for line in reservation.lines])
    for line in reservation.lines:
        item = stock[line.part_id]
        if kind == MovementKind.WITHDRAWAL:
            item.confirm_withdrawal(line.quantity)
        elif kind == MovementKind.RELEASE:
            item.release(line.quantity)
        else:
            item.return_withdrawn(line.quantity)
        item.updated_at = now
        uow.save_item(item)
        uow.add_movement(Movement(line.part_id, kind, line.quantity, now, reservation.id))
    reservation.status = new_status
    reservation.updated_at = now
    uow.save_reservation(reservation)


def _save_tombstone(uow: IStockUnitOfWork, command: Envelope) -> None:
    now = datetime.now(UTC)
    uow.save_reservation(
        Reservation(
            id=str(uuid.uuid4()),
            saga_id=command.saga_id,
            order_id=command.order_id,
            status=ReservationStatus.RELEASED,
            lines=[],
            created_at=now,
            updated_at=now,
        )
    )
