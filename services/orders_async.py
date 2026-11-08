from __future__ import annotations

import asyncio
from typing import Any

from core.config import get_settings
from core.db import get_async_pool
from services import orders as sync_orders
from services.orders import (
    AFTERSALE_WINDOW_DAYS,
    PAYMENT_METHODS,
    SCHEMA,
    STATUS_LABELS,
    OrderDataError,
    _append_event,
    _dump,
    _iso,
    _load,
    _normalize_buyer_id,
    _normalize_order_id,
    _now,
    _order_provider,
    _read_json,
    _saleor_write_guard,
    _shipment_with_items,
    order_summary,
)

_seeded = False
_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _lock(name: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), name)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _q(sql: str) -> str:
    return sql.replace("?", "%s")


async def available() -> bool:
    if (get_settings().orders_backend or "sqlite").strip().lower() != "postgres":
        return False
    return await get_async_pool() is not None


async def _seed_async(conn: Any) -> None:
    now = _iso(_now())
    for buyer in _read_json("buyers.json")["buyers"]:
        await conn.execute(
            _q("INSERT INTO buyers (buyer_id, payload) VALUES (?, ?)"),
            (buyer["buyer_id"], _dump(buyer)),
        )
    for order in _read_json("orders.json")["orders"]:
        await conn.execute(
            _q(
                "INSERT INTO orders "
                "(order_id, buyer_id, status, created_at, payload, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            ),
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
        await conn.execute(
            _q(
                "INSERT INTO shipments "
                "(tracking_no, order_id, updated_at, payload) "
                "VALUES (?, ?, ?, ?)"
            ),
            (
                shipment["tracking_no"],
                shipment["order_id"],
                shipment["updated_at"],
                _dump(shipment),
            ),
        )
    for aftersale in _read_json("aftersales.json")["aftersales"]:
        await conn.execute(
            _q(
                "INSERT INTO aftersales "
                "(aftersale_id, order_id, buyer_id, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (
                aftersale["aftersale_id"],
                aftersale["order_id"],
                aftersale["buyer_id"],
                aftersale["updated_at"],
                _dump(aftersale),
            ),
        )
    coupon_file = sync_orders.ORDER_DATA_DIR / "coupons.json"
    coupons = (
        _read_json("coupons.json")["coupons"] if coupon_file.exists() else []
    )
    for coupon in coupons:
        await conn.execute(
            _q(
                "INSERT INTO coupons "
                "(coupon_id, buyer_id, status, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (
                coupon["coupon_id"],
                coupon["buyer_id"],
                coupon["status"],
                coupon["valid_to"],
                _dump(coupon),
            ),
        )


async def ensure_seeded() -> None:
    global _seeded
    if _seeded:
        return
    async with _lock("seed"):
        if _seeded:
            return
        pool = await get_async_pool()
        if pool is None:
            raise OrderDataError("异步订单数据库不可用")
        async with pool.connection() as conn:
            for statement in SCHEMA.split(";"):
                statement = statement.strip()
                if statement:
                    await conn.execute(statement)
            cursor: Any = await conn.execute(
                _q("SELECT COUNT(*) AS total FROM orders")
            )
            row = await cursor.fetchone()
            count = int(row["total"]) if row else 0
            if count == 0:
                for table in (
                    "buyers",
                    "orders",
                    "shipments",
                    "aftersales",
                    "coupons",
                ):
                    await conn.execute(f"DELETE FROM {table}")
                await _seed_async(conn)
            await conn.commit()
        _seeded = True


async def get_buyer(buyer_id: str | None) -> dict[str, Any] | None:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return None
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(
            _q("SELECT payload FROM buyers WHERE buyer_id = ?"),
            (normalized,),
        )
        row = await cursor.fetchone()
    return _load(row["payload"]) if row else None


async def list_orders(
    buyer_id: str | None, *, limit: int = 5, status: str | None = None
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_orders

        orders = await sync_orders.run_async(
            list_saleor_orders, normalized, limit
        )
        return [
            order_summary(order)
            for order in orders
            if status is None or order.get("status") == status
        ]
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    query = _q("SELECT payload FROM orders WHERE buyer_id = ?")
    params: list[Any] = [normalized]
    if status:
        query += _q(" AND status = ?")
        params.append(status)
    query += _q(" ORDER BY created_at DESC LIMIT ?")
    params.append(limit)
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [order_summary(_load(row["payload"])) for row in rows]


async def _get_order_payload(
    conn: Any, order_id: str, buyer_id: str
) -> tuple[Any, dict[str, Any]] | None:
    cursor: Any = await conn.execute(
        _q("SELECT * FROM orders WHERE order_id = ? AND buyer_id = ?"),
        (order_id, buyer_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return row, _load(row["payload"])


async def get_order(
    order_id: str | None, buyer_id: str | None
) -> dict[str, Any] | None:
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return None
    if _order_provider(normalized_buyer) == "saleor":
        from services.saleor_orders import get_saleor_order

        return await sync_orders.run_async(
            get_saleor_order, normalized_order, normalized_buyer
        )
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        found = await _get_order_payload(
            conn, normalized_order, normalized_buyer
        )
    return found[1] if found else None


async def list_shipments(
    buyer_id: str | None, *, limit: int = 5
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_shipments

        return await sync_orders.run_async(
            list_saleor_shipments, normalized, limit
        )
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(
            _q(
                "SELECT s.payload FROM shipments s "
                "JOIN orders o ON o.order_id = s.order_id "
                "WHERE o.buyer_id = ? ORDER BY s.updated_at DESC LIMIT ?"
            ),
            (normalized, limit),
        )
        rows = await cursor.fetchall()
    return [_load(row["payload"]) for row in rows]


async def get_shipment(
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

        return await sync_orders.run_async(
            get_saleor_shipment,
            normalized,
            order_id=order_id,
            tracking_no=tracking_no,
        )
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        if tracking_no:
            cursor: Any = await conn.execute(
                _q(
                    "SELECT s.payload, o.order_id FROM shipments s "
                    "JOIN orders o ON o.order_id = s.order_id "
                    "WHERE s.tracking_no = ? AND o.buyer_id = ?"
                ),
                (tracking_no.strip().upper(), normalized),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await conn.execute(
                _q("SELECT payload FROM orders WHERE order_id = ?"),
                (row["order_id"],),
            )
            order_row = await cursor.fetchone()
            return _shipment_with_items(
                _load(row["payload"]), _load(order_row["payload"])
            )
        if order_id:
            cursor = await conn.execute(
                _q(
                    "SELECT s.payload FROM shipments s "
                    "JOIN orders o ON o.order_id = s.order_id "
                    "WHERE o.order_id = ? AND o.buyer_id = ?"
                ),
                (_normalize_order_id(order_id), normalized),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            cursor = await conn.execute(
                _q("SELECT payload FROM orders WHERE order_id = ?"),
                (_normalize_order_id(order_id),),
            )
            order_row = await cursor.fetchone()
            return _shipment_with_items(
                _load(row["payload"]), _load(order_row["payload"])
            )
    return None


async def get_aftersale(
    order_id: str | None, buyer_id: str | None
) -> dict[str, Any] | None:
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return None
    if _order_provider(normalized_buyer) == "saleor":
        from services.saleor_orders import get_saleor_aftersale

        return await sync_orders.run_async(
            get_saleor_aftersale, normalized_order, normalized_buyer
        )
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(
            _q(
                "SELECT a.payload FROM aftersales a "
                "JOIN orders o ON o.order_id = a.order_id "
                "WHERE a.order_id = ? AND o.buyer_id = ?"
            ),
            (normalized_order, normalized_buyer),
        )
        row = await cursor.fetchone()
    return _load(row["payload"]) if row else None


async def list_aftersales(
    buyer_id: str | None, *, limit: int = 5
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    if _order_provider(normalized) == "saleor":
        from services.saleor_orders import list_saleor_aftersales

        return await sync_orders.run_async(
            list_saleor_aftersales, normalized, limit
        )
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(
            _q(
                "SELECT payload FROM aftersales WHERE buyer_id = ? "
                "ORDER BY updated_at DESC LIMIT ?"
            ),
            (normalized, limit),
        )
        rows = await cursor.fetchall()
    return [_load(row["payload"]) for row in rows]


async def list_payment_methods(
    buyer_id: str | None = None, *, order_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "methods": [dict(item) for item in PAYMENT_METHODS],
        "installment_available": True,
        "cod_available": False,
    }
    if order_id and buyer_id:
        order = await get_order(order_id, buyer_id)
        if order is not None:
            payload["current_order"] = {
                "order_id": order["order_id"],
                "status": order["status"],
                "status_label": order["status_label"],
                "payment_method": order.get("payment_method"),
            }
    return payload


async def list_coupons(
    buyer_id: str | None, *, active_only: bool = True, limit: int = 10
) -> list[dict[str, Any]]:
    normalized = _normalize_buyer_id(buyer_id)
    if not normalized:
        return []
    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    query = _q("SELECT payload FROM coupons WHERE buyer_id = ?")
    params: list[Any] = [normalized]
    if active_only:
        query += " AND status = 'active'"
    query += _q(" ORDER BY updated_at DESC LIMIT ?")
    params.append(limit)
    async with pool.connection() as conn:
        cursor: Any = await conn.execute(query, params)
        rows = await cursor.fetchall()
    return [_load(row["payload"]) for row in rows]


async def _save_order(conn: Any, order: dict[str, Any]) -> None:
    order["updated_at"] = _iso(_now())
    await conn.execute(
        _q(
            "UPDATE orders SET status = ?, payload = ?, updated_at = ? "
            "WHERE order_id = ?"
        ),
        (
            order["status"],
            _dump(order),
            order["updated_at"],
            order["order_id"],
        ),
    )


async def _save_shipment(conn: Any, shipment: dict[str, Any]) -> None:
    await conn.execute(
        _q(
            "UPDATE shipments SET payload = ?, updated_at = ? "
            "WHERE tracking_no = ?"
        ),
        (_dump(shipment), shipment["updated_at"], shipment["tracking_no"]),
    )


async def cancel_order(
    order_id: str, buyer_id: str | None
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return sync_orders._not_found_buyer()

    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with _lock("write"):
        async with pool.connection() as conn:
            try:
                await conn.execute("BEGIN")
                found = await _get_order_payload(
                    conn, normalized_order, normalized_buyer
                )
                if found is None:
                    await conn.rollback()
                    return sync_orders._not_found_buyer()
                _, order = found
                if order["status"] == "canceled":
                    await conn.rollback()
                    return {
                        "found": True,
                        "already_done": True,
                        "order": order_summary(order),
                        "message": "该订单已经是已取消状态。",
                    }
                if order["status"] not in {"pending_payment", "paid"}:
                    await conn.rollback()
                    return {
                        "found": False,
                        "message": (
                            "订单已发货或已签收，无法直接取消。"
                            "可以尝试拦截快递或申请售后。"
                        ),
                        "order": order_summary(order),
                    }
                order["status"] = "canceled"
                order["status_label"] = STATUS_LABELS["canceled"]
                order["canceled_at"] = _iso(_now())
                _append_event(order, "cancel", "买家取消订单，订单已关闭")
                await _save_order(conn, order)
                await conn.commit()
                return {
                    "found": True,
                    "order": order_summary(order),
                    "message": "订单已取消。",
                }
            except Exception:
                await conn.rollback()
                raise


async def update_address(
    order_id: str, buyer_id: str | None, address: str
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    new_address = address.strip()
    if not normalized_buyer or not normalized_order:
        return sync_orders._not_found_buyer()
    if not new_address:
        return {"found": False, "message": "新地址不能为空。"}

    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with _lock("write"):
        async with pool.connection() as conn:
            try:
                await conn.execute("BEGIN")
                found = await _get_order_payload(
                    conn, normalized_order, normalized_buyer
                )
                if found is None:
                    await conn.rollback()
                    return sync_orders._not_found_buyer()
                _, order = found
                if order["status"] not in {"pending_payment", "paid"}:
                    await conn.rollback()
                    return {
                        "found": False,
                        "message": (
                            "订单已发货，无法修改收货地址。"
                            "可以尝试联系快递拦截。"
                        ),
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
                await _save_order(conn, order)
                await conn.commit()
                return {
                    "found": True,
                    "order": order_summary(order),
                    "address_text": new_address,
                    "message": "收货地址已修改。",
                }
            except Exception:
                await conn.rollback()
                raise


async def intercept_parcel(
    order_id: str, buyer_id: str | None, reason: str = "买家申请拦截"
) -> dict[str, Any]:
    guard = _saleor_write_guard(buyer_id)
    if guard is not None:
        return guard
    normalized_buyer = _normalize_buyer_id(buyer_id)
    normalized_order = _normalize_order_id(order_id)
    if not normalized_buyer or not normalized_order:
        return sync_orders._not_found_buyer()

    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with _lock("write"):
        async with pool.connection() as conn:
            try:
                await conn.execute("BEGIN")
                found = await _get_order_payload(
                    conn, normalized_order, normalized_buyer
                )
                if found is None:
                    await conn.rollback()
                    return sync_orders._not_found_buyer()
                _, order = found
                if order["status"] == "intercepting":
                    await conn.rollback()
                    return {
                        "found": True,
                        "already_done": True,
                        "order": order_summary(order),
                        "message": "该订单已经提交过拦截申请。",
                    }
                if order["status"] not in {
                    "shipped",
                    "in_transit",
                    "exception",
                }:
                    await conn.rollback()
                    return {
                        "found": False,
                        "message": (
                            "当前订单状态不支持拦截快递。"
                            "已签收订单请申请售后。"
                        ),
                        "order": order_summary(order),
                    }

                order["status"] = "intercepting"
                order["status_label"] = STATUS_LABELS["intercepting"]
                _append_event(order, "intercept", f"提交拦截申请：{reason}")
                await _save_order(conn, order)

                cursor: Any = await conn.execute(
                    _q("SELECT payload FROM shipments WHERE order_id = ?"),
                    (order["order_id"],),
                )
                shipment_row = await cursor.fetchone()
                shipment = (
                    _load(shipment_row["payload"]) if shipment_row else None
                )
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
                    await _save_shipment(conn, shipment)

                await conn.commit()
                return {
                    "found": True,
                    "order": order_summary(order),
                    "shipment": shipment,
                    "message": "已提交快递拦截申请，拦截结果以快递公司为准。",
                }
            except Exception:
                await conn.rollback()
                raise


async def create_aftersale(
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
        return sync_orders._not_found_buyer()
    if aftersale_type not in {"退货退款", "仅退款", "换货", "维修"}:
        return {"found": False, "message": "不支持的售后类型。"}

    await ensure_seeded()
    pool = await get_async_pool()
    assert pool is not None
    async with _lock("write"):
        async with pool.connection() as conn:
            try:
                await conn.execute("BEGIN")
                found = await _get_order_payload(
                    conn, normalized_order, normalized_buyer
                )
                if found is None:
                    await conn.rollback()
                    return sync_orders._not_found_buyer()
                _, order = found

                cursor: Any = await conn.execute(
                    _q("SELECT payload FROM aftersales WHERE order_id = ?"),
                    (order["order_id"],),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    await conn.rollback()
                    return {
                        "found": True,
                        "already_done": True,
                        "aftersale": _load(existing["payload"]),
                        "message": "该订单已有售后工单，无需重复申请。",
                    }

                delivered_at = order.get("delivered_at")
                if (
                    order["status"]
                    not in {"delivered", "completed", "refunding"}
                    or not delivered_at
                ):
                    await conn.rollback()
                    return {
                        "found": False,
                        "message": "订单尚未签收，暂不能申请售后。",
                        "order": order_summary(order),
                    }

                from datetime import datetime, timedelta

                delivered = datetime.fromisoformat(delivered_at)
                if _now() - delivered > timedelta(
                    days=AFTERSALE_WINDOW_DAYS
                ):
                    await conn.rollback()
                    return {
                        "found": False,
                        "message": (
                            f"已超过签收后 {AFTERSALE_WINDOW_DAYS} 天"
                            "的售后申请期限。"
                        ),
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
                await _save_order(conn, order)

                await conn.execute(
                    _q(
                        "INSERT INTO aftersales "
                        "(aftersale_id, order_id, buyer_id, updated_at, "
                        "payload) VALUES (?, ?, ?, ?, ?)"
                    ),
                    (
                        aftersale_id,
                        order["order_id"],
                        order["buyer_id"],
                        now_iso,
                        _dump(aftersale),
                    ),
                )
                await conn.commit()
                return {
                    "found": True,
                    "aftersale": aftersale,
                    "order": order_summary(order),
                    "message": "售后工单已创建。",
                }
            except Exception:
                await conn.rollback()
                raise
