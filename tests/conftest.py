import os

# ── Banco de testes ──────────────────────────────────────────────────────────
# Só usa um banco existente se ele vier explicitamente em TEST_DATABASE_URL
# (de propósito não DATABASE_URL: os testes apagam todos os dados a cada
# caso, e DATABASE_URL pode estar apontando para um banco de verdade no
# ambiente de quem roda). Sem ela, o Testcontainers sobe um PostgreSQL
# descartável para a sessão de testes.
_pg_container = None
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
else:
    from testcontainers.postgres import PostgresContainer

    _pg_container = PostgresContainer(
        image="postgres:16-alpine", username="estoque", password="estoque", dbname="estoque_test", driver="psycopg"
    )
    _pg_container.start()
    os.environ["DATABASE_URL"] = _pg_container.get_connection_url()

# ── AWS simulada pelo moto ───────────────────────────────────────────────────
_ACCOUNT = "123456789012"
os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "ESTOQUE_EVENTS_TOPIC_ARN": f"arn:aws:sns:us-east-1:{_ACCOUNT}:estoque-eventos",
        "ESTOQUE_COMMANDS_QUEUE_URL": f"https://sqs.us-east-1.amazonaws.com/{_ACCOUNT}/estoque-comandos",
        "ESTOQUE_CATALOG_EVENTS_QUEUE_URL": f"https://sqs.us-east-1.amazonaws.com/{_ACCOUNT}/estoque-catalogo-eventos",
        "WORKER_WAIT_SECONDS": "0",
        "JWT_SECRET_KEY": "test-secret-key",
        "ADMIN_USERNAME": "admin",
    }
)
os.environ.pop("AWS_ENDPOINT_URL", None)

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jose import jwt
from moto import mock_aws
from sqlalchemy import text

from app.main import app
from app.messaging.dispatcher import Dispatcher
from app.shared.database import get_engine, get_session_factory
from app.shared.events import Envelope
from app.stock.adapters.sqlalchemy_uow import SqlAlchemyStockUnitOfWork
from app.stock.domain.entities import StockItem

TABLES = ["stock_movements", "reservation_items", "reservations", "stock_items", "processed_messages", "outbox_messages"]


def pytest_sessionstart(session) -> None:  # noqa: ARG001
    command.upgrade(Config("alembic.ini"), "head")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    if _pg_container is not None:
        _pg_container.stop()


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    yield
    with get_engine().begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def aws() -> Iterator[None]:
    with mock_aws():
        from scripts.bootstrap_local import bootstrap

        bootstrap()
        yield


def new_uow() -> SqlAlchemyStockUnitOfWork:
    return SqlAlchemyStockUnitOfWork(get_session_factory())


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(new_uow)


def add_stock(part_id: str, on_hand: int, name: str | None = None, min_level: int = 0) -> None:
    with new_uow() as uow:
        uow.add_item(StockItem(part_id=part_id, sku=f"SKU-{part_id}", name=name or f"Peça {part_id}", on_hand=on_hand, min_stock_level=min_level))
        uow.commit()


def stock_of(part_id: str) -> StockItem:
    with new_uow() as uow:
        item = uow.get_item(part_id)
    assert item is not None
    return item


def command_msg(message_type: str, saga_id: str = "saga-1", order_id: int = 42, **payload: object) -> Envelope:
    return Envelope(type=message_type, payload=dict(payload), saga_id=saga_id, order_id=order_id)


def outbox() -> list[dict]:
    """Envelopes gravados na outbox, em ordem."""
    with get_engine().connect() as connection:
        return [row[0] for row in connection.execute(text("SELECT envelope FROM outbox_messages ORDER BY id"))]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def make_token(subject: str = "admin", secret: str = "test-secret-key") -> str:
    return jwt.encode({"sub": subject, "exp": datetime.now(UTC) + timedelta(minutes=5)}, secret, algorithm="HS256")


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token()}"}


def unique_saga() -> str:
    return str(uuid.uuid4())
