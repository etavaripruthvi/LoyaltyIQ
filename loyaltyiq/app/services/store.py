"""Storefront: product search, price quotes, checkout and order status changes.
Checkout is one SQLite transaction: stock, order, points and risk screening succeed or fail together."""
import json
from datetime import timedelta

from ..db import audit, iso, one, rows, utcnow
from . import categories as cats
from ..settings import load_settings
from . import loyalty, risk

PUBLIC_COLS = "id, sku, name, emoji, category, family, brand, brand_tier, unit, price, mrp, stock, rating, consumable, active"
SORTS = {
    "relevance": "(stock>0) DESC, rating DESC, id",
    "price_asc": "price ASC", "price_desc": "price DESC", "discount": "(mrp-price)/mrp DESC",
    "rating": "rating DESC", "name": "name ASC",
}


class StoreError(Exception):
    pass


def product_view(p, meta=None):
    meta = meta or {}
    p = dict(p)
    p["discount_pct"] = round((p["mrp"] - p["price"]) / p["mrp"] * 100) if p["mrp"] > p["price"] else 0
    p["category_name"] = meta.get(p["category"], {}).get("name", p["category"])
    p["color"] = meta.get(p["category"], {}).get("color", "#eee")
    p["in_stock"] = p["stock"] > 0
    p["low_stock"] = 0 < p["stock"] <= 5
    return p


def categories(conn):
    counts = {r["category"]: r["n"] for r in rows(conn, "SELECT category, COUNT(*) n FROM products WHERE active=1 GROUP BY category")}
    keys, meta = cats.load(conn)
    return [dict(meta[k], count=counts.get(k, 0)) for k in keys]


def list_products(conn, category=None, q=None, sort="relevance", page=1, page_size=24, promo=False, in_stock=False):
    where, args = ["active=1"], []
    if category:
        where.append("category=?")
        args.append(category)
    if q:
        for term in q.split():
            where.append("(name LIKE ? OR family LIKE ? OR brand LIKE ? OR category LIKE ?)")
            args += ["%" + term + "%"] * 4
    if promo:
        where.append("mrp>price")
    if in_stock:
        where.append("stock>0")
    w = " AND ".join(where)
    total = one(conn, "SELECT COUNT(*) n FROM products WHERE " + w, args)["n"]
    page = max(1, int(page))
    items = rows(conn, "SELECT " + PUBLIC_COLS + " FROM products WHERE " + w + " ORDER BY " + SORTS.get(sort, SORTS["relevance"]) +
                 " LIMIT ? OFFSET ?", args + [page_size, (page - 1) * page_size])
    meta = cats.load(conn)[1]
    return {"items": [product_view(i, meta) for i in items], "total": total, "page": page, "pages": max(1, -(-total // page_size))}


def get_products(conn, ids):
    ids = list(dict.fromkeys(int(i) for i in ids))
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    meta = cats.load(conn)[1]
    return [product_view(p, meta) for p in rows(conn, "SELECT " + PUBLIC_COLS + " FROM products WHERE id IN (%s)" % ph, ids)]


def _lines(conn, items):
    """Validate a cart and return priced lines."""
    merged = {}
    for it in items or []:
        pid, qty = int(it["product_id"]), int(it["qty"])
        if qty < 1:
            raise StoreError("Quantity must be at least 1")
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise StoreError("Your cart is empty")
    prods = {p["id"]: p for p in get_products(conn, merged)}
    lines = []
    for pid, qty in merged.items():
        p = prods.get(pid)
        if not p or not p["active"]:
            raise StoreError("A product in your cart is no longer available")
        if qty > p["stock"]:
            raise StoreError("Only %d left of %s" % (p["stock"], p["name"]) if p["stock"] else "%s is out of stock" % p["name"])
        lines.append({"product_id": pid, "name": p["name"], "emoji": p["emoji"], "unit": p["unit"], "qty": qty, "unit_price": p["price"],
                      "mrp": p["mrp"], "category": p["category"], "line_total": round(p["price"] * qty, 2)})
    return lines


def new_account_offer(conn, cid, settings=None):
    """The new-account offer if this customer still has it, otherwise None. One use per account."""
    W = (settings or load_settings(conn))["new_account_offer"]
    if not W["enabled"] or (W["discount_pct"] <= 0 and W["bonus_points_pct"] <= 0):
        return None
    c = one(conn, "SELECT new_account_offer FROM customers WHERE id=?", (cid,))
    if not c or not c["new_account_offer"] or one(conn, "SELECT 1 x FROM orders WHERE customer_id=? LIMIT 1", (cid,)):
        return None
    return {"discount_pct": W["discount_pct"], "bonus_points_pct": W["bonus_points_pct"], "max_discount": W["max_discount"]}


def quote(conn, cid, items, redeem_points=0, settings=None):
    S = settings or load_settings(conn)
    LY = S["loyalty"]
    lines = _lines(conn, items)
    subtotal = round(sum(l["line_total"] for l in lines), 2)
    savings = round(sum((l["mrp"] - l["unit_price"]) * l["qty"] for l in lines), 2)
    summary = loyalty.points_summary(conn, cid)
    tier = loyalty.tier_info(conn, cid, S)
    na = new_account_offer(conn, cid, S)
    na_discount = 0.0
    if na and na["discount_pct"] > 0:
        na_discount = round(subtotal * na["discount_pct"] / 100.0, 2)
        if na["max_discount"] > 0:
            na_discount = min(na_discount, float(na["max_discount"]))
    after_discount = round(subtotal - na_discount, 2)
    max_by_rule = int(after_discount * LY["max_redeem_pct"] / 100.0 / LY["point_value"])
    max_redeem = max(0, min(summary["active"], max_by_rule))
    if max_redeem < LY["min_redeem"]:
        max_redeem = 0
    redeem_points = int(redeem_points or 0)
    if redeem_points:
        if redeem_points < LY["min_redeem"]:
            raise StoreError("Minimum redemption is %d points" % LY["min_redeem"])
        if redeem_points > max_redeem:
            raise StoreError("You can redeem at most %d points on this order" % max_redeem)
    redeem_value = round(redeem_points * LY["point_value"], 2)
    paid = round(after_discount - redeem_value, 2)
    offer = active_offer(conn, cid)
    pts, breakdown = loyalty.order_points(lines, paid, subtotal, tier["multiplier"], LY, loyalty.active_campaigns(conn),
                                          offer["multiplier"] if offer else 1.0)
    na_points = 0
    if na and na["bonus_points_pct"] > 0:
        na_points = int(pts * na["bonus_points_pct"] / 100.0 + 0.5)
        pts += na_points
    breakdown["new_account"] = na_points
    welcome = 0
    if not one(conn, "SELECT 1 x FROM orders WHERE customer_id=? LIMIT 1", (cid,)):   # any order counts, so cancelling cannot earn it twice
        welcome = LY["welcome_bonus"]
    needs_review = S["approval"]["mode"] == "all" or paid >= S["approval"]["large_order_threshold"]
    return {"lines": lines, "subtotal": subtotal, "product_savings": savings, "redeem_points": redeem_points, "redeem_value": redeem_value,
            "total": paid, "new_account_offer": na, "new_account_discount": na_discount, "new_account_points": na_points,
            "points_estimate": pts, "points_breakdown": breakdown, "welcome_bonus": welcome,
            "tier": tier["tier"], "multiplier": tier["multiplier"], "max_redeem": max_redeem, "points_available": summary["active"],
            "offer": offer, "may_need_review": needs_review}


def active_offer(conn, cid):
    return one(conn, "SELECT id, kind, multiplier, reason, expires_at FROM offers WHERE customer_id=? AND status='active' AND expires_at>? "
                     "ORDER BY multiplier DESC LIMIT 1", (cid, iso(utcnow())))


def checkout(conn, cid, items, redeem_points=0):
    S = load_settings(conn)
    LY = S["loyalty"]
    q = quote(conn, cid, items, redeem_points, S)
    now = utcnow()
    conn.commit()   # close any implicit transaction left by the read/sweep steps above
    conn.execute("BEGIN IMMEDIATE")
    try:
        for l in q["lines"]:   # atomic stock decrement; fails if someone else bought the last unit
            cur = conn.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=? AND active=1", (l["qty"], l["product_id"], l["qty"]))
            if cur.rowcount != 1:
                raise StoreError("%s just sold out. Please update your cart." % l["name"])
        offer = q["offer"]
        cur = conn.execute(
            "INSERT INTO orders(customer_id, created_at, status, subtotal, product_savings, points_redeemed, redeem_value, total_paid,"
            " points_earned, points_status, offer_id, new_account_discount, new_account_points) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, iso(now), "placed", q["subtotal"], q["product_savings"], q["redeem_points"], q["redeem_value"], q["total"],
             q["points_estimate"], "approved", offer["id"] if offer else None, q["new_account_discount"], q["new_account_points"]))
        if q["new_account_offer"]:   # use it up inside the transaction, so a double click cannot apply it twice
            if conn.execute("UPDATE customers SET new_account_offer=0 WHERE id=? AND new_account_offer=1", (cid,)).rowcount != 1:
                raise StoreError("Your new-account offer was just used on another order. Please review your cart and try again.")
        oid = cur.lastrowid
        conn.executemany("INSERT INTO order_items(order_id, product_id, qty, unit_price, mrp, category) VALUES(?,?,?,?,?,?)",
                         [(oid, l["product_id"], l["qty"], l["unit_price"], l["mrp"], l["category"]) for l in q["lines"]])
        if q["redeem_points"]:
            loyalty.redeem_points(conn, cid, q["redeem_points"], oid, now)
        # welcome bonus on the very first order (never needs approval)
        if q["welcome_bonus"]:
            loyalty.credit_points(conn, cid, oid, q["welcome_bonus"], "active", now, "Welcome bonus", LY["expiry_days"], kind="bonus")
        # screen the order, then credit points as active (auto-approved) or pending (admin queue)
        res = risk.screen(conn, oid, S)
        risk.save(conn, oid, res)
        status = "pending" if res["needs_approval"] else "active"
        loyalty.credit_points(conn, cid, oid, q["points_estimate"], status, now,
                              "Order points (%s tier)" % q["tier"] + (" - awaiting approval" if status == "pending" else ""),
                              LY["expiry_days"])
        conn.execute("UPDATE orders SET points_status=? WHERE id=?", ("pending" if status == "pending" else "approved", oid))
        if offer:
            conn.execute("UPDATE offers SET status='used' WHERE id=?", (offer["id"],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    from . import analytics
    analytics.mark_dirty()
    return get_order(conn, oid)


def get_order(conn, oid, cid=None):
    o = one(conn, "SELECT * FROM orders WHERE id=?" + (" AND customer_id=?" if cid else ""), (oid, cid) if cid else (oid,))
    if not o:
        return None
    o["flags"] = json.loads(o.pop("risk_flags") or "[]")
    o["items"] = rows(conn, "SELECT oi.product_id, oi.qty, oi.unit_price, oi.mrp, p.name, p.emoji, p.unit FROM order_items oi "
                            "JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?", (oid,))
    return o


def customer_orders(conn, cid, limit=100):
    ids = [r["id"] for r in rows(conn, "SELECT id FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT ?", (cid, limit))]
    return [get_order(conn, i) for i in ids]


def set_order_status(conn, oid, new_status, actor, customer_id=None):
    """placed->delivered/cancelled, delivered->returned. Restocks and reverses points on cancel/return."""
    o = one(conn, "SELECT * FROM orders WHERE id=?", (oid,))
    if not o or (customer_id is not None and o["customer_id"] != customer_id):
        raise StoreError("Order not found")
    allowed = {"placed": {"delivered", "cancelled"}, "delivered": {"returned"}}
    if new_status not in allowed.get(o["status"], set()):
        raise StoreError("Cannot change an order from %s to %s" % (o["status"], new_status))
    if customer_id is not None and new_status != "cancelled":
        raise StoreError("Customers can only cancel orders that have not been delivered")
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (new_status, oid))
        if new_status in ("cancelled", "returned"):
            for it in rows(conn, "SELECT product_id, qty FROM order_items WHERE order_id=?", (oid,)):
                conn.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], it["product_id"]))
            loyalty.reverse_order(conn, oid, "Order %s" % new_status, actor)
        audit(conn, actor, "order_" + new_status, "order %d" % oid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    from . import analytics
    analytics.mark_dirty()
    return get_order(conn, oid)
