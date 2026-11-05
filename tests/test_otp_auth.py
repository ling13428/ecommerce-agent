import pytest
from fastapi.testclient import TestClient

from core.otp import reset_otp_store
from main import app
from services import orders as order_service


@pytest.fixture(autouse=True)
def _reset_otp():
    reset_otp_store()
    yield
    reset_otp_store()


def _demo_phone():
    buyer = order_service.list_buyers()[0]
    return (
        order_service.buyer_login_phone(buyer),
        buyer["buyer_id"],
    )


def test_phone_maps_to_buyer():
    phone, buyer_id = _demo_phone()
    buyer = order_service.find_buyer_by_phone(phone)
    assert buyer is not None
    assert buyer["buyer_id"] == buyer_id


def test_otp_login_success_and_single_use():
    phone, buyer_id = _demo_phone()
    client = TestClient(app)

    send = client.post(
        "/api/auth/buyer/send-code", json={"phone": phone}
    )
    assert send.status_code == 200
    code = send.json()["debug_code"]

    login = client.post(
        "/api/auth/buyer/otp/login",
        json={"phone": phone, "code": code},
    )
    assert login.status_code == 200
    assert login.json()["token"]
    assert login.json()["buyer"]["buyer_id"] == buyer_id

    again = client.post(
        "/api/auth/buyer/otp/login",
        json={"phone": phone, "code": code},
    )
    assert again.status_code == 401


def test_send_code_cooldown():
    phone, _ = _demo_phone()
    client = TestClient(app)

    first = client.post(
        "/api/auth/buyer/send-code", json={"phone": phone}
    )
    second = client.post(
        "/api/auth/buyer/send-code", json={"phone": phone}
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_wrong_code_rejected():
    phone, _ = _demo_phone()
    client = TestClient(app)

    send = client.post(
        "/api/auth/buyer/send-code", json={"phone": phone}
    )
    code = send.json()["debug_code"]
    wrong = "000000" if code != "000000" else "111111"

    login = client.post(
        "/api/auth/buyer/otp/login",
        json={"phone": phone, "code": wrong},
    )
    assert login.status_code == 401


def test_legacy_login_still_works():
    buyer = order_service.list_buyers()[0]
    client = TestClient(app)
    response = client.post(
        "/api/auth/buyer/login",
        json={
            "buyer_id": buyer["buyer_id"],
            "login_code": buyer["login_code"],
        },
    )
    assert response.status_code == 200
    assert response.json()["buyer"]["buyer_id"] == buyer["buyer_id"]
