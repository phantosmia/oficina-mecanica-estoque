from datetime import datetime

from pydantic import BaseModel, Field


class StockItemRead(BaseModel):
    part_id: str
    sku: str
    name: str
    quantity_on_hand: int = Field(description="Unidades fisicamente na oficina")
    quantity_reserved: int = Field(description="Unidades prometidas a OS que ainda não fizeram a baixa")
    quantity_available: int = Field(description="Em estoque menos reservado: o que pode ser reservado agora")
    min_stock_level: int
    below_minimum: bool
    updated_at: datetime | None = None


class StockEntryCreate(BaseModel):
    quantity: int = Field(gt=0)
    note: str | None = Field(default=None, description="Ex.: número da nota fiscal do fornecedor")


class MinimumLevelUpdate(BaseModel):
    min_stock_level: int = Field(ge=0)


class MovementRead(BaseModel):
    kind: str
    quantity: int
    reservation_id: str | None = None
    note: str | None = None
    created_at: datetime


class ReservationLineRead(BaseModel):
    part_id: str
    quantity: int


class ReservationRead(BaseModel):
    id: str
    saga_id: str
    order_id: int
    status: str
    items: list[ReservationLineRead]
    created_at: datetime
    updated_at: datetime | None = None
