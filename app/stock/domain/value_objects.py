from enum import StrEnum


class ReservationStatus(StrEnum):
    RESERVED = "reservada"      # saldo reservado, aguardando a baixa
    REFUSED = "recusada"        # faltou saldo: nada foi reservado
    CONFIRMED = "confirmada"    # baixa definitiva (ConfirmarBaixa)
    RELEASED = "liberada"       # reserva desfeita (LiberarPecas)
    RETURNED = "devolvida"      # baixa desfeita (DevolverPecas)


class MovementKind(StrEnum):
    ENTRY = "entrada"           # reposição de estoque (admin)
    RESERVE = "reserva"
    RELEASE = "liberacao"
    WITHDRAWAL = "baixa"
    RETURN = "devolucao"
