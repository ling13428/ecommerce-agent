from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import BASE_DIR, get_settings
from core.db import get_pool

ORDER_DATA_DIR = BASE_DIR / "data" / "orders"
ORDER_DB_PATH = ORDER_DATA_DIR / "orders.db"

TIMEZONE = timezone(timedelta(hours=8))
AFTERSALE_WINDOW_DAYS = 7

STATUS_LABELS = {
    "canceled": "已取消",
    "intercepting": "拦截中",
    "refunding": "退款中",
    "aftersale_processing": "售后处理中",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS buyers (
    buyer_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    buyer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_buyer
    ON orders (buyer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status
    ON orders (status);
CREATE TABLE IF NOT EXISTS shipments (
    tracking_no TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aftersales (
    aftersale_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    buyer_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aftersales_buyer
    ON aftersales (buyer_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS coupons (
    coupon_id TEXT PRIMARY KEY,
    buyer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coupons_buyer
    ON coupons (buyer_id, status);
"""

_lock = threading.Lock()
_write_lock = threading.Lock()
_seeded = False


class OrderDataError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(TIMEZONE)


def _iso(value: datetime) -> str:
    return value.astimezone(TIMEZONE).isoformat(timespec="seconds")


class _SqliteConnectionWrapper:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def execute(self, sql: str, params: Any = ()) -> Any:
        return self._connection.execute(sql, params)

    def executescript(self, script: str) -> None:
        self._connection.executescript(script)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


class _PostgresConnectionWrapper:
    def __init__(self, pool: Any, connection: Any):
        self._pool = pool
        self._connection = connection

    def execute(self, sql: str, params: Any = ()) -> Any:
        translated = sql.replace("?", "%s")
        if translated.strip().upper() == "BEGIN IMMEDIATE":
            translated = "BEGIN"
        return self._connection.execute(translated, params)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._connection.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        try:
            self._connection.rollback()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._connection.rollback()
        except Exception:
            pass
        self._pool.putconn(self._connection)


_Connection = _SqliteConnectionWrapper | _PostgresConnectionWrapper


def _backend() -> str:
    return (get_settings().orders_backend or "sqlite").strip().lower()


def _order_provider(buyer_id: str | None = None) -> str:
    provider = (get_settings().order_provider or "mock").strip().lower()
    if provider != "saleor":
        return "mock"
    from core.features import saleor_enabled

    return "saleor" if saleor_enabled(buyer_id) else "mock"


def _connect() -> _Connection:
    if _backend() == "postgres":
        pool = get_pool()
        return _PostgresConnectionWrapper(pool, pool.getconn())
    ORDER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ORDER_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return _SqliteConnectionWrapper(conn)


def _read_json(name: str) -> dict[str, Any]:
    path = ORDER_DATA_DIR / name
    if not path.exists():
        raise OrderDataError(f"缺少订单数据文件：{path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _load(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def _seed(conn: Any) -> None:
    now = _iso(_now())
    for buyer in _read_json("buyers.json")["buyers"]:
        conn.execute(
            "INSERT INTO buyers (buyer_id, payload) VALUES (?, ?)",
            (buyer["buyer_id"], _dump(buyer)),
        )
    for order in _read_json("orders.json")["orders"]:
        conn.execute(
            "INSERT INTO orders "
            "(order_id, buyer_id, status, created_at, payload, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                order["order_id"],
                order["buyer_id"],
                order["status"],
                order["created_at"],
                _dump(order),
                now,
            ),
        )
    for shipment in _read_json("logistics.json")["shipments"]:
        conn.execute(
            "INSERT INTO shipments "
            "(tracking_no, order_id, updated_at, payload) VALUES (?, ?, ?, ?)",
            (
                shipment["tracking_no"],
                shipment["order_id"],
                shipment["updated_at"],
                _dump(shipment),
            ),
        )
    for aftersale in _read_json("aftersales.json")["aftersales"]:
        conn.execute(
            "INSERT INTO aftersales "
            "(aftersale_id, order_id, buyer_id, updated_at, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                aftersale["aftersale_id"],
                aftersale["order_id"],
                aftersale["buyer_id"],
                aftersale["updated_at"],
                _dump(aftersale),
            ),
        )
    coupon_file = ORDER_DATA_DIR / "coupons.json"
    coupons = _read_json("coupons.json")["coupons"] if coupon_file.exists() else []
    for coupon in coupons:
        conn.execute(
            "INSERT INTO coupons "
            "(coupon_id, buyer_id, status, updated_at, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                coupon["coupon_id"],
                coupon["buyer_id"],
                coupon["status"],
                coupon["valid_to"],
                _dump(coupon),
            ),
        )


def ensure_seeded() -> None:
    global _seeded
    if _seeded:
        return
    with _lock:
        if _seeded:
            return
        conn = _connect()
        try:
            conn.executescript(SCHEMA)
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM orders"
            ).fetchone()
            count = int(row["total"]) if row else 0
            if count == 0:
                for table in (
                    "buyers",
                    "orders",
                    "shipments",
                    "aftersales",
                    "coupons",
                ):
                    conn.execute(f"DELETE FROM {table}")
                _seed(conn)
            conn.commit()
        finally:
            conn.close()
        _seeded = True


def reset_store() -> None:
    global _seeded
    with _lock:
        if _backend() == "postgres":
            conn = _connect()
            try:
                conn.executescript(SCHEMA)
                conn.execute(
                    "TRUNCATE buyers, orders, shipments, aftersales, coupons"
                )
                conn.commit()
            finally:
                conn.close()
        elif ORDER_DB_PATH.exists():
            ORDER_DB_PATH.unlink()
        _seeded = False


def _normalize_buyer_id(buyer_id: str | None) -> str:
    return (buyer_id or "").strip().upper()


def _normalize_order_id(order_id: str | None) -> str:
    return (order_id or "").strip().upper()


def list_buyers() -> list[dict[str, Any]]:
    ensure_seeded()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT payload FROM buyers").fetchall()
    buyers = [_load(row["payload"]) for row in rows]
    buyers.sort(key=lambda item: item["buyer_id"])
    return buyers


def get_buyer(buyer_id: str | None) -> dict[str, Any] | None:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return None
    ensure_seeded()
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT payload FROM buyers WHERE buyer_id = ?", (normalized,)
        ).fetchone()
    return _load(row["payload"]) if row else None


def verify_buyer_login(
    buyer_id: str | None, login_code: str | None
) -> dict[str, Any] | None:
    buyer = get_buyer(buyer_id)
    if buyer is None:
        return None
    expected = str(buyer.get("login_code") or "").strip()
    provided = (login_code or "").strip()
    if not expected or not provided:
        return None
    if not secrets.compare_digest(expected, provided):
        return None
    return buyer


def buyer_login_phone(buyer: dict[str, Any]) -> str:
    masked = str(buyer.get("phone") or "")
    digits = re.sub(r"\D", "", masked)
    prefix = digits[:3] if len(digits) >= 7 else "139"
    suffix = digits[-4:] if len(digits) >= 4 else "0000"
    digest = hashlib.sha256(
        str(buyer.get("buyer_id") or "").encode("utf-8")
    ).hexdigest()
    middle = "".join(str(int(char, 16) % 10) for char in digest[:4])
    return f"{prefix}{middle}{suffix}"


def find_buyer_by_phone(phone: str) -> dict[str, Any] | None:
    normalized = re.sub(r"\D", "", phone or "")
    if not normalized:
        return None
    for buyer in list_buyers():
        if buyer_login_phone(buyer) == normalized:
            return buyer
    return None


def order_summary(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "status_label": order["status_label"],
        "created_at": order["created_at"],
        "item_count": order["item_count"],
        "payable": order["payable"],
        "items": [
            {
                "product_id": item["product_id"],
                "model": item["model"],
                "name": item["name"],
                "quantity": item["quantity"],
            }
            for item in order["items"]
        ],
        "tracking_no": order.get("tracking_no"),
        "carrier": order.get("carrier"),
        "aftersale_id": order.get("aftersale_id"),
    }


def list_orders(
    buyer_id: str | None, *, limit: int = 5, status: str | None = None
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_orders

        orders = list_saleor_orders(normalized, limit)
        return [
            order_summary(order)
            for order in orders
            if status is None or order.get("status") == status
        ]
    ensure_seeded()
    query = "SELECT payload FROM orders WHERE buyer_id = ?"
    params: list[Any] = [normalized]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [order_summary(_load(row["payload"])) for row in rows]


def _get_order_payload(
    conn: Any, order_id: str, buyer_id: str
) -> tuple[sqlite3.Row, dict[str, Any]] | None:
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ? AND buyer_id = ?",
        (order_id, buyer_id),
    ).fetchone()
    if row is None:
        return None
    return row, _load(row["payload"])


def get_order(order_id: str | None, buyer_id: str | None) -> dict[str, Any] | None:
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return None
    if _order_provider(normalized_buyer) == "saleor":
        from services.saleor_orders import get_saleor_order

        return get_saleor_order(normalized_order, normalized_buyer)
    ensure_seeded()
    with closing(_connect()) as conn:
        found = _get_order_payload(conn, normalized_order, normalized_buyer)
    return found[1] if found else None


def list_shipments(buyer_id: str | None, *, limit: int = 5) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_shipments

        return list_saleor_shipments(normalized, limit)
    ensure_seeded()
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT s.payload FROM shipments s "
            "JOIN orders o ON o.order_id = s.order_id "
            "WHERE o.buyer_id = ? ORDER BY s.updated_at DESC LIMIT ?",
            (normalized, limit),
        ).fetchall()
    return [_load(row["payload"]) for row in rows]


def _shipment_with_items(
    shipment: dict[str, Any], order: dict[str, Any]
) -> dict[str, Any]:
    return {
        **shipment,
        "items": [
            {
                "product_id": item["product_id"],
                "model": item["model"],
                "quantity": item["quantity"],
            }
            for item in order["items"]
        ],
    }


def get_shipment(
    buyer_id: str | None,
    *,
    order_id: str | None = None,
    tracking_no: str | None = None,
) -> dict[str, Any] | None:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return None
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import get_saleor_shipment

        return get_saleor_shipment(
            normalized, order_id=order_id, tracking_no=tracking_no
        )
    ensure_seeded()

    with closing(_connect()) as conn:
        if tracking_no:
            row = conn.execute(
                "SELECT s.payload, o.order_id FROM shipments s "
                "JOIN orders o ON o.order_id = s.order_id "
                "WHERE s.tracking_no = ? AND o.buyer_id = ?",
                (tracking_no.strip().upper(), normalized),
            ).fetchone()
            if row is None:
                return None
            order_row = conn.execute(
                "SELECT payload FROM orders WHERE order_id = ?",
                (row["order_id"],),
            ).fetchone()
            return _shipment_with_items(
                _load(row["payload"]), _load(order_row["payload"])
            )

        if order_id:
            row = conn.execute(
                "SELECT s.payload FROM shipments s "
                "JOIN orders o ON o.order_id = s.order_id "
                "WHERE o.order_id = ? AND o.buyer_id = ?",
                (_normalize_order_id(order_id), normalized),
            ).fetchone()
            if row is None:
                return None
            order_row = conn.execute(
                "SELECT payload FROM orders WHERE order_id = ?",
                (_normalize_order_id(order_id),),
            ).fetchone()
            return _shipment_with_items(
                _load(row["payload"]), _load(order_row["payload"])
            )

    return None


def get_aftersale(
    order_id: str | None, buyer_id: str | None
) -> dict[str, Any] | None:
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return None
    if _order_provider(normalized_buyer) == "saleor":
        from services.saleor_orders import get_saleor_aftersale

        return get_saleor_aftersale(normalized_order, normalized_buyer)
    ensure_seeded()
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT a.payload FROM aftersales a "
            "JOIN orders o ON o.order_id = a.order_id "
            "WHERE a.order_id = ? AND o.buyer_id = ?",
            (normalized_order, normalized_buyer),
        ).fetchone()
    return _load(row["payload"]) if row else None


def list_aftersales(
    buyer_id: str | None, *, limit: int = 5
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_aftersales

        return list_saleor_aftersales(normalized, limit)
    ensure_seeded()
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT payload FROM aftersales WHERE buyer_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (normalized, limit),
        ).fetchall()
    return [_load(row["payload"]) for row in rows]


PAYMENT_METHODS = [
    {
        "code": "alipay",
        "name": "支付宝",
        "available": True,
        "installment": False,
        "note": "支持余额、余额宝和绑定银行卡支付",
    },
    {
        "code": "wechat",
        "name": "微信支付",
        "available": True,
        "installment": False,
        "note": "支持零钱和绑定银行卡支付",
    },
    {
        "code": "huabei",
        "name": "花呗",
        "available": True,
        "installment": True,
        "installment_options": ["3 期", "6 期", "12 期"],
        "note": "分期手续费以支付宝页面显示为准",
    },
    {
        "code": "card",
        "name": "银行卡",
        "available": True,
        "installment": False,
        "note": "支持储蓄卡和信用卡",
    },
    {
        "code": "cod",
        "name": "货到付款",
        "available": False,
        "installment": False,
        "note": "当前店铺暂不支持货到付款",
    },
]


def list_payment_methods(
    buyer_id: str | None = None, *, order_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "methods": [dict(item) for item in PAYMENT_METHODS],
        "installment_available": True,
        "cod_available": False,
    }
    if order_id and buyer_id:
        order = get_order(order_id, buyer_id)
        if order is not None:
            payload["current_order"] = {
                "order_id": order["order_id"],
                "status": order["status"],
                "status_label": order["status_label"],
                "payment_method": order.get("payment_method"),
            }
    return payload


def list_coupons(
    buyer_id: str | None, *, active_only: bool = True, limit: int = 10
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    ensure_seeded()
    query = "SELECT payload FROM coupons WHERE buyer_id = ?"
    params: list[Any] = [normalized]
    if active_only:
        query += " AND status = 'active'"
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_load(row["payload"]) for row in rows]


def _save_order(conn: Any, order: dict[str, Any]) -> None:
    order["updated_at"] = _iso(_now())
    conn.execute(
        "UPDATE orders SET status = ?, payload = ?, updated_at = ? "
        "WHERE order_id = ?",
        (order["status"], _dump(order), order["updated_at"], order["order_id"]),
    )


def _save_shipment(conn: Any, shipment: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE shipments SET payload = ?, updated_at = ? WHERE tracking_no = ?",
        (_dump(shipment), shipment["updated_at"], shipment["tracking_no"]),
    )


def _append_event(
    order: dict[str, Any], event_type: str, description: str
) -> None:
    order.setdefault("operation_events", []).append(
        {"time": _iso(_now()), "type": event_type, "description": description}
    )


def _not_found_buyer() -> dict[str, Any]:
    return {
        "found": False,
        "message": "没有找到该订单。请确认订单号是否正确，以及是否属于当前买家。",
    }


_SALEOR_WRITE_MESSAGE = (
    "真实订单系统目前只开放查询，取消/改地址/拦截/售后请转人工处理。"
)


def _saleor_write_guard(buyer_id: str | None = None) -> dict[str, Any] | None:
    if _order_provider(buyer_id) == "saleor":
        return {"found": False, "message": _SALEOR_WRITE_MESSAGE}
    return None


def cancel_order(
    order_id: str, buyer_id: str | None
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return _not_found_buyer()

    ensure_seeded()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = _get_order_payload(conn, normalized_order, normalized_buyer)
            if found is None:
                conn.rollback()
                return _not_found_buyer()
            _, order = found
            if order["status"] == "canceled":
                conn.rollback()
                return {
                    "found": True,
                    "already_done": True,
                    "order": order_summary(order),
                    "message": "该订单已经是已取消状态。",
                }
            if order["status"] not in {"pending_payment", "paid"}:
                conn.rollback()
                return {
                    "found": False,
                    "message": "订单已发货或已签收，无法直接取消。可以尝试拦截快递或申请售后。",
                    "order": order_summary(order),
                }
            order["status"] = "canceled"
            order["status_label"] = STATUS_LABELS["canceled"]
            order["canceled_at"] = _iso(_now())
            _append_event(order, "cancel", "买家取消订单，订单已关闭")
            _save_order(conn, order)
            conn.commit()
            return {
                "found": True,
                "order": order_summary(order),
                "message": "订单已取消。",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def update_address(
    order_id: str, buyer_id: str | None, address: str
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    new_address = address.strip()
    if not normalized_buyer or not normalized_order:
        return _not_found_buyer()
    if not new_address:
        return {"found": False, "message": "新地址不能为空。"}

    ensure_seeded()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = _get_order_payload(conn, normalized_order, normalized_buyer)
            if found is None:
                conn.rollback()
                return _not_found_buyer()
            _, order = found
            if order["status"] not in {"pending_payment", "paid"}:
                conn.rollback()
                return {
                    "found": False,
                    "message": "订单已发货，无法修改收货地址。可以尝试联系快递拦截。",
                    "order": order_summary(order),
                }
            old_address = order.get("address_text", "")
            order["address_text"] = new_address
            order["address"] = {
                "province": "",
                "city": "",
                "district": "",
                "detail": new_address,
            }
            _append_event(
                order,
                "update_address",
                f"收货地址由「{old_address}」修改为「{new_address}」",
            )
            _save_order(conn, order)
            conn.commit()
            return {
                "found": True,
                "order": order_summary(order),
                "address_text": new_address,
                "message": "收货地址已修改。",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def intercept_parcel(
    order_id: str, buyer_id: str | None, reason: str = "买家申请拦截"
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return _not_found_buyer()

    ensure_seeded()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = _get_order_payload(conn, normalized_order, normalized_buyer)
            if found is None:
                conn.rollback()
                return _not_found_buyer()
            _, order = found
            if order["status"] == "intercepting":
                conn.rollback()
                return {
                    "found": True,
                    "already_done": True,
                    "order": order_summary(order),
                    "message": "该订单已经提交过拦截申请。",
                }
            if order["status"] not in {"shipped", "in_transit", "exception"}:
                conn.rollback()
                return {
                    "found": False,
                    "message": "当前订单状态不支持拦截快递。已签收订单请申请售后。",
                    "order": order_summary(order),
                }

            order["status"] = "intercepting"
            order["status_label"] = STATUS_LABELS["intercepting"]
            _append_event(order, "intercept", f"提交拦截申请：{reason}")
            _save_order(conn, order)

            shipment_row = conn.execute(
                "SELECT payload FROM shipments WHERE order_id = ?",
                (order["order_id"],),
            ).fetchone()
            shipment = _load(shipment_row["payload"]) if shipment_row else None
            if shipment is not None:
                now_iso = _iso(_now())
                shipment["status"] = "intercepting"
                shipment["status_label"] = STATUS_LABELS["intercepting"]
                shipment["current_node"] = "已提交拦截申请，等待快递处理"
                shipment["updated_at"] = now_iso
                shipment.setdefault("events", []).append(
                    {
                        "time": now_iso,
                        "status": "拦截申请",
                        "description": "买家申请拦截，等待快递处理",
                        "location": shipment.get("current_node", ""),
                    }
                )
                _save_shipment(conn, shipment)

            conn.commit()
            return {
                "found": True,
                "order": order_summary(order),
                "shipment": shipment,
                "message": "已提交快递拦截申请，拦截结果以快递公司为准。",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def create_aftersale(
    order_id: str,
    buyer_id: str | None,
    aftersale_type: str,
    reason: str,
    description: str = "",
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return _not_found_buyer()
    if aftersale_type not in {"退货退款", "仅退款", "换货", "维修"}:
        return {"found": False, "message": "不支持的售后类型。"}

    ensure_seeded()
    with _write_lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = _get_order_payload(conn, normalized_order, normalized_buyer)
            if found is None:
                conn.rollback()
                return _not_found_buyer()
            _, order = found

            existing = conn.execute(
                "SELECT payload FROM aftersales WHERE order_id = ?",
                (order["order_id"],),
            ).fetchone()
            if existing is not None:
                conn.rollback()
                return {
                    "found": True,
                    "already_done": True,
                    "aftersale": _load(existing["payload"]),
                    "message": "该订单已有售后工单，无需重复申请。",
                }

            delivered_at = order.get("delivered_at")
            if order["status"] not in {"delivered", "completed", "refunding"} or not delivered_at:
                conn.rollback()
                return {
                    "found": False,
                    "message": "订单尚未签收，暂不能申请售后。",
                    "order": order_summary(order),
                }

            delivered = datetime.fromisoformat(delivered_at)
            if _now() - delivered > timedelta(days=AFTERSALE_WINDOW_DAYS):
                conn.rollback()
                return {
                    "found": False,
                    "message": f"已超过签收后 {AFTERSALE_WINDOW_DAYS} 天的售后申请期限。",
                    "order": order_summary(order),
                }

            now_iso = _iso(_now())
            aftersale_id = f"AS-{order['order_id'][-8:]}"
            refund_amount = (
                order["payable"]
                if aftersale_type in {"退货退款", "仅退款"}
                else 0
            )
            detail = reason.strip() or "买家申请售后"
            if description.strip():
                detail = f"{detail}；补充说明：{description.strip()}"

            aftersale = {
                "aftersale_id": aftersale_id,
                "order_id": order["order_id"],
                "buyer_id": order["buyer_id"],
                "type": aftersale_type,
                "reason": detail,
                "status": "pending",
                "status_label": "待商家处理",
                "created_at": now_iso,
                "updated_at": now_iso,
                "refund_amount": refund_amount,
                "timeline": [
                    {
                        "time": now_iso,
                        "status": "已提交",
                        "description": "售后申请已提交，等待商家处理",
                    }
                ],
            }

            order["aftersale_id"] = aftersale_id
            if aftersale_type in {"退货退款", "仅退款"}:
                order["status"] = "refunding"
            else:
                order["status"] = "aftersale_processing"
            order["status_label"] = STATUS_LABELS[order["status"]]
            _append_event(
                order,
                "create_aftersale",
                f"创建售后工单 {aftersale_id}（{aftersale_type}）",
            )
            _save_order(conn, order)

            conn.execute(
                "INSERT INTO aftersales "
                "(aftersale_id, order_id, buyer_id, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    aftersale_id,
                    order["order_id"],
                    order["buyer_id"],
                    now_iso,
                    _dump(aftersale),
                ),
            )
            conn.commit()
            return {
                "found": True,
                "aftersale": aftersale,
                "order": order_summary(order),
                "message": "售后工单已创建。",
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

