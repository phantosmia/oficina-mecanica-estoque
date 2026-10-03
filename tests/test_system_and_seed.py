from fastapi.testclient import TestClient
from sqlalchemy import text

from app.shared.database import get_engine
from scripts.seed import PARTS, part_id_for, seed
from tests.conftest import stock_of


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_checks_migrations(client: TestClient) -> None:
    assert client.get("/ready").json() == {"status": "ok", "schema_revision": "0001"}

    with get_engine().begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'antiga'"))
    try:
        assert client.get("/ready").status_code == 503
    finally:
        with get_engine().begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0001'"))


def test_seed_is_idempotent_and_matches_catalog_ids() -> None:
    assert seed() == len(PARTS)
    assert seed() == 0

    # Mesmo ID que o Catálogo gera para o SKU em oficina-mecanica-catalogo/scripts/seed.py.
    assert part_id_for("OLEO-5W30-1L") == "572e22d4-2e66-527d-a0ca-9ec61bbd1376"
    oil = stock_of(part_id_for("OLEO-5W30-1L"))
    assert (oil.on_hand, oil.min_stock_level) == (50, 10)
