class DomainError(Exception):
    """Base class for all domain errors."""


class NotFoundError(DomainError):
    """Raised when an entity is not found."""

    def __init__(self, entity: str, identifier: object) -> None:
        super().__init__(f"{entity} não encontrado(a).")
        self.entity = entity
        self.identifier = identifier


class ConflictError(DomainError):
    """Raised when a uniqueness or integrity constraint is violated."""


class InsufficientStockError(DomainError):
    """Raised when there is not enough available stock for an operation."""
