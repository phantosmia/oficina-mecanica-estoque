import pytest
from fastapi.testclient import TestClient

from app.messaging.dispatcher import Dispatcher
from tests.conftest import add_stock, command_msg, make_token

ROUTES = [
    ("get", "/stock", None),
    ("get", "/stock/oleo", None),
    ("post", "/stock/oleo/entries", {"quantity": 1}),
    ("put", "/stock/oleo/minimum", {"min_stock_level": 1}),
    ("get", "/stock/oleo/movements", None),
    ("get", "/reservations/saga-1", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_all_routes_require_admin(client: TestClient, method: str, path: str, body: dict | None) -> None:
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    bad = {"Authorization": f"Bearer {make_token(subject='12345678909')}"}
    assert getattr(client, method)(path, headers=bad, **kwargs).status_code == 401


def test_stock_listing_and_minimum_filter(client: TestClient, admin_headers: dict[str, str]) -> None:
    add_stock("oleo", 50, name="Óleo", min_level=10)
    add_stock("disco", 1, name="Disco de freio", min_level=2)

    listed = client.get("/stock", headers=admin_headers).json()
    assert [i["name"] for i in listed] == ["Disco de freio", "Óleo"]
    assert listed[1] | {"updated_at": None} == {
        "part_id": "oleo", "sku": "SKU-oleo", "name": "Óleo", "quantity_on_hand": 50, "quantity_reserved": 0,
        "quantity_available": 50, "min_stock_level": 10, "below_minimum": False, "updated_at": None,
    }
    below = client.get("/stock", params={"below_minimum": True}, headers=admin_headers).json()
    assert [i["part_id"] for i in below] == ["disco"]


def test_entry_minimum_and_movements(client: TestClient, admin_headers: dict[str, str]) -> None:
    add_stock("disco", 1, min_level=2)

    entry = client.post("/stock/disco/entries", json={"quantity": 5, "note": "NF 123"}, headers=admin_headers)
    assert entry.status_code == 200
    assert entry.json()["quantity_on_hand"] == 6

    minimum = client.put("/stock/disco/minimum", json={"min_stock_level": 8}, headers=admin_headers)
    assert minimum.json()["below_minimum"] is True

    movements = client.get("/stock/disco/movements", headers=admin_headers).json()
    assert [(m["kind"], m["quantity"], m["note"]) for m in movements] == [("entrada", 5, "NF 123")]


def test_validation_and_not_found(client: TestClient, admin_headers: dict[str, str]) -> None:
    add_stock("disco", 1)
    assert client.post("/stock/disco/entries", json={"quantity": 0}, headers=admin_headers).status_code == 422
    assert client.put("/stock/disco/minimum", json={"min_stock_level": -1}, headers=admin_headers).status_code == 422
    for method, path, body in ROUTES[1:]:
        kwargs = {"json": body} if body else {}
        assert getattr(client, method)(path.replace("oleo", "nao-existe"), headers=admin_headers, **kwargs).status_code == 404


def test_reservation_status_during_saga(client: TestClient, admin_headers: dict[str, str], dispatcher: Dispatcher) -> None:
    add_stock("oleo", 10)
    dispatcher.handle(command_msg("ReservarPecas", saga_id="saga-9", order_id=9, items=[{"part_id": "oleo", "quantity": 2}]))

    reservation = client.get("/reservations/saga-9", headers=admin_headers).json()
    assert (reservation["status"], reservation["order_id"], reservation["items"]) == ("reservada", 9, [{"part_id": "oleo", "quantity": 2}])

    dispatcher.handle(command_msg("LiberarPecas", saga_id="saga-9", order_id=9))
    assert client.get("/reservations/saga-9", headers=admin_headers).json()["status"] == "liberada"
    assert client.get("/stock/oleo", headers=admin_headers).json()["quantity_reserved"] == 0
