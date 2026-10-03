from contextlib import contextmanager
from collections.abc import Generator

from fastapi import HTTPException, status

from app.shared.exceptions import ConflictError, DomainError, InsufficientStockError, NotFoundError


@contextmanager
def domain_error_handler() -> Generator[None, None, None]:
    """Context manager that converts domain errors into FastAPI HTTP exceptions."""
    try:
        yield
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ConflictError, InsufficientStockError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
