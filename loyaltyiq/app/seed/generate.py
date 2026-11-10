"""Seed the database: users, customers (10 showcase personas + background shoppers),
12 months of orders, the points ledger, campaigns and a few deliberately suspicious orders."""
import json
import time
from collections import defaultdict
from datetime import timedelta

import numpy as np
from werkzeug.security import generate_password_hash

from .. import config
from ..db import iso, utcnow, audit
from ..services import loyalty, risk
from ..settings import DEFAULT_SETTINGS, save_settings
from .catalog import CAT_KEYS, CAT_META, build_catalog
from .personas import CITIES, FIRST_NAMES, LAST_NAMES, PERSONAS, SHOWCASE_ORDER

HISTORY_DAYS = 365
RECENT_REVIEW_DAYS = 10     # orders newer than this go through live risk screening


class _Catalog:
    def __init__(self, products):
        self.p = products
        self.price = np.array([p["price"] for p in products])
        self.tier = np.array([{"value": 0, "standard": 1, "premium": 2}[p["brand_tier"]] for p in products])
        self.pop = np.array([p["pop"] for p in products])
        self.promo = np.array([1.0 if p["mrp"] > p["price"] else 0.0 for p in products])
        self.consumable = np.array([bool(p["consumable"]) for p in products])
        self.cat = [p["category"] for p in products]
        self.cat_i = np.array([CAT_KEYS.index(c) for c in self.cat])
        self.cat_idx = {c: np.array([i for i, p in enumerate(products) if p["category"] == c]) for c in CAT_KEYS}
        self.cat_med = {c: float(np.median(self.price[self.cat_idx[c]])) for c in CAT_KEYS}
        self.cycle = np.array([CAT_META[p["category"]]["cycle"] or 30 for p in products], dtype=float)


def _profile(key, rng, showcase):
    P = PERSONAS[key]
    j = 0.3 if showcase else 1.0
    cats = np.array([P["cats"].get(c, 0.0) + 0.004 for c in CAT_KEYS]) * rng.lognormal(0, 0.35 * j, len(CAT_KEYS))
    tp = np.array(P["tier_pref"]) * rng.lognormal(0, 0.2 * j, 3)
    return {
        "key": key, "cats": cats / cats.sum(), "tier_pref": tp / tp.sum(),
        "budget": P["budget"] * rng.lognormal(0, 0.18 * j),
        "opm": P["orders_per_month"] * rng.lognormal(0, 0.22 * j),
        "ds": float(np.clip(P["discount_sens"] + rng.normal(0, 0.08 * j), 0, 1)),
        "basket": P["basket"], "repeat": P["repeat"], "qty_extra": P["qty_extra"],
        "redeem_prob": P["redeem_prob"], "return_rate": P["return_rate"], "season": P["season"],
    }


def _simulate_orders(prof, cat, start, end, now, rng, times=None):
    """Return a list of (datetime, {product_idx: qty}) for one customer.
    Order times come from a daily Poisson process, or from `times` when given."""
    w_cache = {}

    def prod_weights(c):
        if c not in w_cache:
            idx = cat.cat_idx[c]
            fit = np.exp(-(np.log(cat.price[idx]) - np.log(cat.cat_med[c] * prof["budget"])) ** 2 / (2 * 0.75 ** 2))
            w = cat.pop[idx] ** 0.6 * fit * prof["tier_pref"][cat.tier[idx]] * (1 + 3.5 * prof["ds"] * cat.promo[idx])
            w_cache[c] = w / w.sum()
        return w_cache[c]

    if times is not None:
        schedule = [(t, 1) for t in times]
    else:
        n_days = max(0, (end - start).days)
        if n_days == 0:
            return []
        days = [start + timedelta(days=i) for i in range(n_days)]
        rate = np.array([prof["opm"] / 30.0 * prof["season"].get(d.month, 1.0) for d in days])
        counts = rng.poisson(np.minimum(rate, 3.0))
        schedule = [(d, int(n)) for d, n in zip(days, counts) if n > 0]
    favs, last, owned, out = [], {}, set(), []
    for d, n in schedule:
        for _ in range(int(n)):
            ts = d if times is not None else d.replace(hour=int(rng.integers(7, 23)), minute=int(rng.integers(0, 60)),
                                                       second=int(rng.integers(0, 60)))
            if ts > now:
                continue
            lines = defaultdict(int)
            for _l in range(max(1, 1 + int(rng.poisson(prof["basket"] - 1)))):
                pi = None
                cand = [p for p in favs if cat.consumable[p]]
                if cand and rng.random() < prof["repeat"]:
                    el = np.array([(ts - last[p]).days / cat.cycle[p] for p in cand])
                    w = np.clip(el, 0.05, 3.0) ** 2 * prof["cats"][cat.cat_i[np.array(cand)]] ** 0.5
                    pi = cand[int(rng.choice(len(cand), p=w / w.sum()))]
                else:
                    c = CAT_KEYS[int(rng.choice(len(CAT_KEYS), p=prof["cats"]))]
                    for _try in range(4):
                        pi = int(cat.cat_idx[c][int(rng.choice(len(cat.cat_idx[c]), p=prod_weights(c)))])
                        if cat.consumable[pi] or pi not in owned:
                            break
                qty = 1 + (int(rng.poisson(prof["qty_extra"])) if cat.consumable[pi] else (1 if rng.random() < 0.02 else 0))
                lines[pi] = min(6, lines[pi] + qty)
            for pi in lines:
                last[pi] = ts
                if pi not in favs:
                    favs.append(pi)
                if not cat.consumable[pi]:
                    owned.add(pi)
            out.append((ts, dict(lines)))
    return out


def seed_database(conn, now=None, seed=None, n_background=None, verbose=False):
    t0 = time.time()
    seed = config.SEED if seed is None else seed
    n_background = config.N_BACKGROUND_CUSTOMERS if n_background is None else n_background
    rng = np.random.default_rng(seed)
    now = now or utcnow()
    S = json.loads(json.dumps(DEFAULT_SETTINGS))
    LY = S["loyalty"]
    save_settings(conn, S)

    # ---- catalogue ----
    products = build_catalog(rng)
    conn.executemany(
        "INSERT INTO products(id, sku, name, emoji, category, family, brand, brand_tier, unit, price, mrp, cost, stock, reorder_level,"
        " consumable, rating, active, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        [(i + 1, p["sku"], p["name"], p["emoji"], p["category"], p["family"], p["brand"], p["brand_tier"], p["unit"], p["price"],
          p["mrp"], p["cost"], p["stock"], p["reorder_level"], p["consumable"], p["rating"], iso(now - timedelta(days=400)))
         for i, p in enumerate(products)])
    cat = _Catalog(products)

    # ---- users and customers ----
    pw = generate_password_hash(config.DEMO_PASSWORD)
    admin_pw = pw if config.ADMIN_PASSWORD == config.DEMO_PASSWORD else generate_password_hash(config.ADMIN_PASSWORD)
    conn.execute("INSERT INTO users(id, username, password_hash, role, display_name) VALUES(1,'admin',?, 'admin','Store Admin')", (admin_pw,))
    plan = [(k, True) for k in SHOWCASE_ORDER]
    keys = list(PERSONAS)
    wts = np.array([PERSONAS[k]["weight"] for k in keys], dtype=float)
    for _ in range(n_background):
        plan.append((keys[int(rng.choice(len(keys), p=wts / wts.sum()))], False))

    customers = []
    for n, (key, showcase) in enumerate(plan, start=1):
        P = PERSONAS[key]
        uid, username = n + 1, "user%d" % n
        name = P["name"] if showcase else "%s %s" % (FIRST_NAMES[int(rng.integers(len(FIRST_NAMES)))], LAST_NAMES[int(rng.integers(len(LAST_NAMES)))])
        if key == "newbie":
            join = now - timedelta(days=int(rng.integers(*P["join_days"])) if not showcase else 14)
        elif not showcase and rng.random() < 0.12:
            join = now - timedelta(days=int(rng.integers(60, 300)))
        else:
            join = now - timedelta(days=int(rng.integers(380, 800)))
        conn.execute("INSERT INTO users(id, username, password_hash, role, display_name) VALUES(?,?,?, 'customer',?)", (uid, username, pw, name))
        conn.execute("INSERT INTO customers(id, user_id, name, city, email, joined_at, persona, is_showcase) VALUES(?,?,?,?,?,?,?,?)",
                     (n, uid, name, CITIES[int(rng.integers(len(CITIES)))], "%s@example.com" % username, iso(join), key, int(showcase)))
        customers.append({"id": n, "key": key, "showcase": showcase, "join": join})

    # ---- simulate raw orders ----
    raw = {}
    for c in customers:
        prof = _profile(c["key"], rng, c["showcase"])
        P = PERSONAS[c["key"]]
        start = max(c["join"], now - timedelta(days=HISTORY_DAYS))
        if c["key"] == "newbie":
            jd = (now - c["join"]).days
            n_ord = 1 if c["showcase"] else int(rng.integers(1, 3))
            times = sorted(c["join"] + timedelta(days=int(rng.integers(0, max(2, jd - 1))), hours=int(rng.integers(1, 10)))
                           for _ in range(n_ord))
            orders = _simulate_orders(prof, cat, c["join"], now, now, rng, times=times)
        else:
            end = now
            if c["key"] == "lapsed":
                end = now - timedelta(days=150 if c["showcase"] else int(rng.integers(*P["lapse_days"])))
            orders = _simulate_orders(prof, cat, start, end, now, rng)
            if c["showcase"] and c["key"] in ("deal_hunter", "premium", "parent", "fitness", "trendy", "student", "techie"):
                if not orders or (now - max(o[0] for o in orders)).days > 9:   # keep steady personas visibly active
                    tops = sorted(now - timedelta(days=float(rng.uniform(0.5, 6))) for _ in range(1 + int(prof["opm"] > 2)))
                    orders += _simulate_orders(prof, cat, start, now, now, rng, times=tops)
        raw[c["id"]] = {"prof": prof, "orders": orders}

    _inject_suspicious(raw, customers, cat, now, rng)

    # ---- price the orders, run the loyalty ledger ----
    tiers = LY["tiers"]
    order_rows, item_rows, ledger_rows = [], [], []
    oid = 0
    for c in customers:
        prof, orders = raw[c["id"]]["prof"], sorted(raw[c["id"]]["orders"], key=lambda x: x[0])
        stack, hist, welcome_given = [], [], (now - c["join"]).days > HISTORY_DAYS + 5

        def expire_until(ts):
            for e in stack:
                if e["remaining"] > 0 and e["expires"] <= ts and e["status"] == "active":
                    ledger_rows.append({"cid": c["id"], "oid": None, "kind": "expire", "points": -e["remaining"], "remaining": 0,
                                        "status": "active", "created": e["expires"], "expires": None, "note": "Points expired"})
                    e["remaining"] = 0

        for ts, lines in orders:
            oid += 1
            expire_until(ts)
            li = [(pi, q) for pi, q in lines.items()]
            subtotal = sum(cat.price[pi] * q for pi, q in li)
            savings = sum((cat.p[pi]["mrp"] - cat.p[pi]["price"]) * q for pi, q in li)
            age = (now - ts).days
            status = "placed" if age <= 2 else "delivered"
            if rng.random() < 0.015:
                status = "cancelled"
            elif age >= 10 and rng.random() < prof["return_rate"]:
                status = "returned"
            # redemption
            redeem = 0
            bal = sum(e["remaining"] for e in stack if e["status"] == "active")
            if status in ("placed", "delivered") and bal >= LY["min_redeem"] and subtotal >= 300 and rng.random() < prof["redeem_prob"]:
                cap = min(bal, int(subtotal * LY["max_redeem_pct"] / 100.0 / LY["point_value"]))
                if cap >= LY["min_redeem"]:
                    redeem = max(LY["min_redeem"], int(rng.uniform(0.5, 1.0) * cap) // 10 * 10)
                    redeem = min(redeem, cap)
            paid = round(subtotal - redeem * LY["point_value"], 2)
            spend12 = sum(a for t, a in hist if t > ts - timedelta(days=HISTORY_DAYS))
            ti = loyalty.tier_index(spend12, tiers)
            pts, _b = loyalty.order_points([{"line_total": cat.price[pi] * q, "category": cat.cat[pi]} for pi, q in li],
                                           paid, subtotal, tiers[ti]["multiplier"], LY)
            order_rows.append((oid, c["id"], iso(ts), status, subtotal, savings, redeem, redeem * LY["point_value"], paid, pts,
                               "approved", 0, "[]"))
            for pi, q in li:
                item_rows.append((oid, pi + 1, q, cat.price[pi], cat.p[pi]["mrp"], cat.cat[pi]))
            if not welcome_given and status in ("placed", "delivered"):
                welcome_given = True
                e = {"cid": c["id"], "oid": oid, "kind": "bonus", "points": LY["welcome_bonus"], "remaining": LY["welcome_bonus"],
                     "status": "active", "created": ts, "expires": ts + timedelta(days=LY["expiry_days"]), "note": "Welcome bonus"}
                ledger_rows.append(e)
                stack.append(e)
            if redeem:
                need = redeem
                for e in sorted([e for e in stack if e["remaining"] > 0 and e["status"] == "active"], key=lambda x: x["expires"]):
                    take = min(need, e["remaining"])
                    e["remaining"] -= take
                    need -= take
                    if need <= 0:
                        break
                ledger_rows.append({"cid": c["id"], "oid": oid, "kind": "redeem", "points": -redeem, "remaining": 0, "status": "active",
                                    "created": ts, "expires": None, "note": "Redeemed at checkout"})
            if status in ("placed", "delivered"):
                e = {"cid": c["id"], "oid": oid, "kind": "earn", "points": pts, "remaining": pts, "status": "active", "created": ts,
                     "expires": ts + timedelta(days=LY["expiry_days"]), "note": "Order points (%s tier)" % tiers[ti]["name"]}
                ledger_rows.append(e)
                stack.append(e)
                hist.append((ts, paid))
            else:
                ledger_rows.append({"cid": c["id"], "oid": oid, "kind": "earn", "points": pts, "remaining": 0, "status": "active",
                                    "created": ts, "expires": ts + timedelta(days=LY["expiry_days"]), "note": "Order points"})
                ledger_rows.append({"cid": c["id"], "oid": oid, "kind": "reverse", "points": -pts, "remaining": 0, "status": "active",
                                    "created": ts + timedelta(days=3), "expires": None, "note": "Order %s" % status})
        expire_until(now)

    conn.executemany("INSERT INTO orders(id, customer_id, created_at, status, subtotal, product_savings, points_redeemed, redeem_value,"
                     " total_paid, points_earned, points_status, risk_score, risk_flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", order_rows)
    conn.executemany("INSERT INTO order_items(order_id, product_id, qty, unit_price, mrp, category) VALUES(?,?,?,?,?,?)", item_rows)
    conn.executemany(
        "INSERT INTO points_ledger(customer_id, order_id, kind, points, remaining, status, created_at, expires_at, note) VALUES(?,?,?,?,?,?,?,?,?)",
        [(r["cid"], r["oid"], r["kind"], r["points"], r["remaining"], r["status"], iso(r["created"]),
          iso(r["expires"]) if r["expires"] else None, r["note"]) for r in ledger_rows])

    # ---- campaigns ----
    conn.executemany("INSERT INTO campaigns(name, category, multiplier, starts_at, ends_at, active) VALUES(?,?,?,?,?,1)", [
        ("Staples bonanza: 2x points", "staples", 2.0, iso(now - timedelta(days=5)), iso(now + timedelta(days=21))),
        ("Gadget week: 1.5x points", "electronics", 1.5, iso(now - timedelta(days=2)), iso(now + timedelta(days=12))),
        ("Festive snacks: 3x points", "snacks", 3.0, iso(now - timedelta(days=5)), iso(now + timedelta(days=30))),
    ])

    # ---- live risk screening of recent orders -> approvals queue ----
    recent = [r[0] for r in conn.execute("SELECT id FROM orders WHERE created_at>? AND status IN ('placed','delivered')",
                                         (iso(now - timedelta(days=RECENT_REVIEW_DAYS)),))]
    pending = 0
    for o_id in recent:
        res = risk.screen(conn, o_id, S)
        risk.save(conn, o_id, res)
        if res["needs_approval"]:
            pending += 1
            conn.execute("UPDATE orders SET points_status='pending' WHERE id=?", (o_id,))
            conn.execute("UPDATE points_ledger SET status='pending', remaining=0 WHERE order_id=? AND kind='earn'", (o_id,))
    audit(conn, "system", "seed", "Seeded %d products, %d customers, %d orders" % (len(products), len(customers), len(order_rows)))
    conn.commit()
    stats = {"products": len(products), "customers": len(customers), "orders": len(order_rows), "pending": pending,
             "seconds": round(time.time() - t0, 1)}
    if verbose:
        print("Seeded:", stats)
    return stats


def _inject_suspicious(raw, customers, cat, now, rng):
    """Add a few deliberately risky recent orders so the approvals queue has real work in it."""
    def pick(key, pred=lambda c: True):
        pool = [c for c in customers if c["key"] == key and not c["showcase"] and pred(c)]
        return pool[int(rng.integers(len(pool)))] if pool else None

    def find(name_part, tier=None):
        for i, p in enumerate(cat.p):
            if name_part in p["family"] and (tier is None or p["brand_tier"] == tier):
                return i

    c = pick("parent")
    if c:  # burst: four orders in under a day
        for h in (21, 14, 8, 3):
            lines = {int(cat.cat_idx["staples"][int(rng.integers(len(cat.cat_idx["staples"])))]): 2,
                     int(cat.cat_idx["snacks"][int(rng.integers(len(cat.cat_idx["snacks"])))]): 3}
            raw[c["id"]]["orders"].append((now - timedelta(hours=h), lines))
    c = pick("techie")
    if c:  # bulk quantity
        raw[c["id"]]["orders"].append((now - timedelta(days=2, hours=3), {find("Power Bank", "standard"): 12, find("Fast Charger", "standard"): 8}))
    c = pick("newbie")
    if c:  # new account, very high value
        raw[c["id"]]["orders"].append((now - timedelta(days=1, hours=5), {find("Laptop", "premium"): 2, find("Smart TV", "premium"): 1}))
    c = pick("deal_hunter", lambda x: len(raw[x["id"]]["orders"]) >= 8)
    if c:  # far above this customer's normal basket
        raw[c["id"]]["orders"].append((now - timedelta(days=3, hours=2), {find("Smartphone", "premium"): 1, find("Smartwatch", "standard"): 1}))
