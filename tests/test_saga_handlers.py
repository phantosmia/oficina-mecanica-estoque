"""Participação do Estoque na saga (docs/saga.md), contra PostgreSQL real."""

from concurrent.futures import ThreadPoolExecutor
import threading

from app.messaging.dispatcher import Dispatcher
from app.shared.events import Envelope
from tests.conftest import add_stock, command_msg, new_uow, outbox, stock_of

OIL, PAD = "oleo", "pastilha"


def reserve(dispatcher: Dispatcher, saga_id: str = "saga-1", **quantities: int) -> Envelope:
    message = command_msg("ReservarPecas", saga_id, items=[{"part_id": p, "quantity": q} for p, q in quantities.items()])
    dispatcher.handle(message)
    return message


def last_reply() -> dict:
    return outbox()[-1]


# ── PecaCadastrada ───────────────────────────────────────────────────────────


def test_part_registered_creates_zero_balance_once(dispatcher: Dispatcher) -> None:
    event = Envelope(type="PecaCadastrada", payload={"part_id": "novo", "sku": "NOVO", "name": "Peça nova"})
    dispatcher.handle(event)
    dispatcher.handle(event)  # reentrega
    dispatcher.handle(Envelope(type="PecaCadastrada", payload={"part_id": "novo", "sku": "X", "name": "Outro nome"}))

    stock = stock_of("novo")
    assert (stock.sku, stock.name, stock.on_hand, stock.reserved) == ("NOVO", "Peça nova", 0, 0)
    assert outbox() == []  # evento recebido não gera resposta


# ── ReservarPecas ────────────────────────────────────────────────────────────


def test_reserve_all_parts(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    add_stock(PAD, 4)

    command = command_msg(
        "ReservarPecas",
        items=[{"part_id": OIL, "quantity": 2}, {"part_id": PAD, "quantity": 4}, {"part_id": OIL, "quantity": 1}],
    )
    dispatcher.handle(command)

    assert (stock_of(OIL).reserved, stock_of(PAD).reserved) == (3, 4)
    reply = last_reply()
    assert reply["type"] == "PecasReservadas"
    assert (reply["saga_id"], reply["order_id"]) == (command.saga_id, command.order_id)
    # Itens repetidos são somados, e as linhas saem em ordem de part_id.
    assert reply["payload"]["items"] == [{"part_id": OIL, "quantity": 3}, {"part_id": PAD, "quantity": 4}]


def test_reservation_is_all_or_nothing(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    add_stock(PAD, 1)

    reserve(dispatcher, oleo=2, pastilha=3)

    assert (stock_of(OIL).reserved, stock_of(PAD).reserved) == (0, 0)
    reply = last_reply()
    assert reply["type"] == "ReservaRecusada"
    assert reply["payload"]["reason"] == "estoque_insuficiente"
    assert reply["payload"]["unavailable"] == [
        {"part_id": PAD, "requested": 3, "available": 1, "reason": "estoque_insuficiente"}
    ]
    with new_uow() as uow:
        assert uow.get_reservation_by_saga("saga-1").status == "recusada"


def test_part_without_balance_is_refused(dispatcher: Dispatcher) -> None:
    reserve(dispatcher, fantasma=1)

    assert last_reply()["payload"]["unavailable"] == [
        {"part_id": "fantasma", "requested": 1, "available": 0, "reason": "peca_sem_saldo_cadastrado"}
    ]


def test_invalid_quantity_is_refused(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=0)
    assert last_reply()["type"] == "ReservaRecusada"
    assert last_reply()["payload"]["reason"] == "quantidade_invalida"
    assert stock_of(OIL).reserved == 0


def test_diagnosis_without_parts_reserves_nothing(dispatcher: Dispatcher) -> None:
    reserve(dispatcher)
    assert last_reply()["type"] == "PecasReservadas"
    assert last_reply()["payload"]["items"] == []


def test_redelivered_message_is_processed_once(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    message = reserve(dispatcher, oleo=2)

    dispatcher.handle(message)

    assert stock_of(OIL).reserved == 2
    assert len(outbox()) == 1


def test_resent_command_repeats_reply_without_repeating_effect(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=2)
    reserve(dispatcher, oleo=2)  # mesmo comando, novo message_id (reenvio por prazo)

    assert stock_of(OIL).reserved == 2
    first, second = outbox()
    assert first["type"] == second["type"] == "PecasReservadas"
    assert first["payload"] == second["payload"]
    assert first["message_id"] != second["message_id"]


def test_concurrent_reservations_never_oversell(dispatcher: Dispatcher) -> None:
    """Duas sagas disputando as últimas unidades ao mesmo tempo: só uma leva."""
    add_stock(OIL, 3)
    start = threading.Barrier(2)

    def run(saga_id: str) -> None:
        start.wait()
        reserve(Dispatcher(new_uow), saga_id, oleo=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ["saga-a", "saga-b"]))

    assert sorted(m["type"] for m in outbox()) == ["PecasReservadas", "ReservaRecusada"]
    assert stock_of(OIL).reserved == 2


# ── ConfirmarBaixa ───────────────────────────────────────────────────────────


def test_confirm_withdrawal(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)

    dispatcher.handle(command_msg("ConfirmarBaixa"))
    dispatcher.handle(command_msg("ConfirmarBaixa"))  # reenvio: não baixa de novo

    stock = stock_of(OIL)
    assert (stock.on_hand, stock.reserved) == (7, 0)
    assert [m["type"] for m in outbox()] == ["PecasReservadas", "BaixaConfirmada", "BaixaConfirmada"]


def test_confirm_without_reservation_fails(dispatcher: Dispatcher) -> None:
    dispatcher.handle(command_msg("ConfirmarBaixa"))
    assert last_reply()["type"] == "BaixaFalhou"
    assert last_reply()["payload"] == {"reason": "reserva_inexistente"}


def test_confirm_after_release_fails(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)
    dispatcher.handle(command_msg("LiberarPecas"))

    dispatcher.handle(command_msg("ConfirmarBaixa"))

    assert last_reply()["payload"] == {"reason": "reserva_liberada"}
    assert stock_of(OIL).on_hand == 10


# ── Compensações ─────────────────────────────────────────────────────────────


def test_release_undoes_reservation(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)

    dispatcher.handle(command_msg("LiberarPecas"))
    dispatcher.handle(command_msg("LiberarPecas"))

    assert stock_of(OIL).reserved == 0
    assert [m["type"] for m in outbox()] == ["PecasReservadas", "PecasLiberadas", "PecasLiberadas"]


def test_release_before_reserve_blocks_late_reservation(dispatcher: Dispatcher) -> None:
    """Mensagens fora de ordem: a compensação chega antes da reserva."""
    add_stock(OIL, 10)

    dispatcher.handle(command_msg("LiberarPecas"))
    reserve(dispatcher, oleo=3)

    assert stock_of(OIL).reserved == 0
    assert [m["type"] for m in outbox()] == ["PecasLiberadas", "ReservaRecusada"]
    assert last_reply()["payload"]["reason"] == "saga_ja_compensada"


def test_release_after_withdrawal_returns_parts(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)
    dispatcher.handle(command_msg("ConfirmarBaixa"))

    dispatcher.handle(command_msg("LiberarPecas"))

    assert (stock_of(OIL).on_hand, stock_of(OIL).reserved) == (10, 0)
    assert last_reply()["type"] == "PecasLiberadas"


def test_return_undoes_withdrawal(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)
    dispatcher.handle(command_msg("ConfirmarBaixa"))

    dispatcher.handle(command_msg("DevolverPecas"))
    dispatcher.handle(command_msg("DevolverPecas"))

    assert (stock_of(OIL).on_hand, stock_of(OIL).reserved) == (10, 0)
    assert [m["type"] for m in outbox()][-2:] == ["PecasDevolvidas", "PecasDevolvidas"]
    with new_uow() as uow:
        kinds = [m.kind.value for m in uow.list_movements(OIL)]
    assert kinds == ["reserva", "baixa", "devolucao"]


def test_return_before_withdrawal_releases_reservation(dispatcher: Dispatcher) -> None:
    add_stock(OIL, 10)
    reserve(dispatcher, oleo=3)

    dispatcher.handle(command_msg("DevolverPecas"))

    assert (stock_of(OIL).on_hand, stock_of(OIL).reserved) == (10, 0)


def test_return_without_reservation_still_confirms(dispatcher: Dispatcher) -> None:
    dispatcher.handle(command_msg("DevolverPecas"))
    assert last_reply()["type"] == "PecasDevolvidas"


def test_unknown_message_type_is_ignored(dispatcher: Dispatcher) -> None:
    assert dispatcher.handle(command_msg("ComandoQueNaoExiste")) is False
    assert outbox() == []
