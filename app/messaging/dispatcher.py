"""Roteia cada mensagem recebida para o caso de uso correspondente."""

import json
import logging
from collections.abc import Callable
from typing import Any

from app.shared.events import Envelope
from app.stock.application.saga_handlers import (
    ConfirmWithdrawalUseCase,
    RegisterPartUseCase,
    ReleasePartsUseCase,
    ReservePartsUseCase,
    ReturnPartsUseCase,
)
from app.stock.domain.repository import IStockUnitOfWork

logger = logging.getLogger(__name__)

HANDLERS: dict[str, type] = {
    # comandos do orquestrador (fila estoque-comandos)
    "ReservarPecas": ReservePartsUseCase,
    "ConfirmarBaixa": ConfirmWithdrawalUseCase,
    "LiberarPecas": ReleasePartsUseCase,
    "DevolverPecas": ReturnPartsUseCase,
    # eventos do Catálogo (fila estoque-catalogo-eventos, assinando o SNS)
    "PecaCadastrada": RegisterPartUseCase,
}


def parse_body(body: str) -> Envelope:
    """Corpo da mensagem SQS → envelope. Aceita também o formato com
    `RawMessageDelivery` desligado, em que o SNS embrulha a mensagem
    original no campo `Message`."""
    data: dict[str, Any] = json.loads(body)
    if data.get("Type") == "Notification" and "Message" in data:
        data = json.loads(data["Message"])
    return Envelope(
        type=data["type"],
        payload=data.get("payload") or {},
        saga_id=data.get("saga_id"),
        order_id=data.get("order_id"),
        message_id=data["message_id"],
        occurred_at=data["occurred_at"],
    )


class Dispatcher:
    def __init__(self, uow_factory: Callable[[], IStockUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def handle(self, envelope: Envelope) -> bool:
        """Processa a mensagem. Retorna False para tipo desconhecido (não há
        o que fazer; o worker apaga a mensagem em vez de deixá-la voltar)."""
        handler = HANDLERS.get(envelope.type)
        if handler is None:
            logger.warning("mensagem de tipo desconhecido ignorada type=%s message_id=%s", envelope.type, envelope.message_id)
            return False
        handler(self._uow_factory()).execute(envelope)
        logger.info(
            "mensagem processada type=%s message_id=%s saga_id=%s order_id=%s",
            envelope.type, envelope.message_id, envelope.saga_id, envelope.order_id,
        )
        return True
