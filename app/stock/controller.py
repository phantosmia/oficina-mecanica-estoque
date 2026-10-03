from fastapi import APIRouter, Depends

from app.shared.database import get_session_factory
from app.shared.dependencies import get_current_admin
from app.shared.http_errors import domain_error_handler
from app.stock.adapters.presenter import movement_to_response, reservation_to_response, stock_to_response
from app.stock.adapters.sqlalchemy_uow import SqlAlchemyStockUnitOfWork
from app.stock.application.use_cases import (
    GetReservationUseCase,
    GetStockUseCase,
    ListMovementsUseCase,
    ListStockUseCase,
    RegisterEntryUseCase,
    SetMinimumLevelUseCase,
)
from app.stock.domain.repository import IStockUnitOfWork
from app.stock.schemas import MinimumLevelUpdate, MovementRead, ReservationRead, StockEntryCreate, StockItemRead

# Tudo aqui é operação interna da oficina: exige o JWT de admin emitido pelo
# OS Service. Reservas e baixas não têm endpoint: chegam só pela saga (SQS).
router = APIRouter(tags=["stock"], dependencies=[Depends(get_current_admin)])


def get_uow() -> IStockUnitOfWork:
    return SqlAlchemyStockUnitOfWork(get_session_factory())


@router.get("/stock", response_model=list[StockItemRead])
def list_stock(below_minimum: bool = False, uow: IStockUnitOfWork = Depends(get_uow)) -> list[StockItemRead]:
    """Saldos por peça. `?below_minimum=true` lista só as que precisam de reposição."""
    return [stock_to_response(i) for i in ListStockUseCase(uow).execute(below_minimum)]


@router.get("/stock/{part_id}", response_model=StockItemRead)
def get_stock(part_id: str, uow: IStockUnitOfWork = Depends(get_uow)) -> StockItemRead:
    with domain_error_handler():
        return stock_to_response(GetStockUseCase(uow).execute(part_id))


@router.post("/stock/{part_id}/entries", response_model=StockItemRead)
def register_entry(part_id: str, payload: StockEntryCreate, uow: IStockUnitOfWork = Depends(get_uow)) -> StockItemRead:
    """Entrada de estoque (reposição)."""
    with domain_error_handler():
        return stock_to_response(RegisterEntryUseCase(uow).execute(part_id, payload.quantity, payload.note))


@router.put("/stock/{part_id}/minimum", response_model=StockItemRead)
def set_minimum(part_id: str, payload: MinimumLevelUpdate, uow: IStockUnitOfWork = Depends(get_uow)) -> StockItemRead:
    with domain_error_handler():
        return stock_to_response(SetMinimumLevelUseCase(uow).execute(part_id, payload.min_stock_level))


@router.get("/stock/{part_id}/movements", response_model=list[MovementRead])
def list_movements(part_id: str, uow: IStockUnitOfWork = Depends(get_uow)) -> list[MovementRead]:
    """Histórico de entradas, reservas, liberações, baixas e devoluções da peça."""
    with domain_error_handler():
        return [movement_to_response(m) for m in ListMovementsUseCase(uow).execute(part_id)]


@router.get("/reservations/{saga_id}", response_model=ReservationRead)
def get_reservation(saga_id: str, uow: IStockUnitOfWork = Depends(get_uow)) -> ReservationRead:
    """Situação da reserva de uma saga (reservada, recusada, confirmada, liberada ou devolvida)."""
    with domain_error_handler():
        return reservation_to_response(GetReservationUseCase(uow).execute(saga_id))
