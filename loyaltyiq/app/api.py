"""JSON API for the admin console and the customer portal. One database, one set of services."""
import json
import time
from collections import Counter, defaultdict
from datetime import timedelta
from functools import wraps

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import config, db
from .db import audit, iso, one, rows, utcnow
from .seed.personas import PERSONAS
from .services import agent, analytics, loyalty, recommender, store
from .services import awareness, segments as segsvc
from .services import categories as catsvc
from .settings import DEFAULT_SETTINGS, load_settings, save_settings

bp = Blueprint("api", __name__, url_prefix="/api")


def err(msg, code=400):
    return jsonify({"error": msg}), code


def persona_label(key):
    """Admin-added customers have no simulated persona."""
    return PERSONAS[key]["label"] if key in PERSONAS else "Added by admin"


def usernames(conn):
    return {r["cid"]: r["username"] for r in rows(conn, "SELECT c.id cid, u.username FROM customers c JOIN users u ON u.id=c.user_id")}


@bp.before_request
def _open():
    g.db = db.connect()
    g.user, g.cid = None, None
    uid = session.get("uid")
    if uid:
        g.user = one(g.db, "SELECT id, username, role, display_name FROM users WHERE id=?", (uid,))
        if g.user and g.user["role"] == "customer":
            c = one(g.db, "SELECT id FROM customers WHERE user_id=?", (uid,))
            g.cid = c["id"] if c else None


@bp.teardown_app_request
def _close(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        return fn(*a, **k) if g.user else err("Please log in", 401)
    return w


def admin_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not g.user:
            return err("Please log in", 401)
        return fn(*a, **k) if g.user["role"] == "admin" else err("Admin access required", 403)
    return w


def customer_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not g.user:
            return err("Please log in", 401)
        return fn(*a, **k) if g.cid else err("Customer access required", 403)
    return w


def body():
    return request.get_json(silent=True) or {}


# ============ auth ============
def _me():
    u = g.user
    out = {"username": u["username"], "role": u["role"], "name": u["display_name"], "customer_id": g.cid}
    if g.cid:
        t = loyalty.tier_info(g.db, g.cid)
        p = loyalty.points_summary(g.db, g.cid)
        out.update(tier=t["tier"], points=p["active"], pending_points=p["pending"])
    return out


@bp.post("/login")
def login():
    d = body()
    u = one(g.db, "SELECT * FROM users WHERE username=?", (str(d.get("username", "")).strip().lower(),))
    if not u or not check_password_hash(u["password_hash"], str(d.get("password", ""))):
        return err("Wrong username or password", 401)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    g.user = u
    c = one(g.db, "SELECT id FROM customers WHERE user_id=?", (u["id"],))
    g.cid = c["id"] if c else None
    g.user["display_name"] = u["display_name"]
    return jsonify(_me())


_REG_HITS = {}   # address -> times of recent sign-ups (in memory; the app runs one worker)


def _register_allowed():
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")
    now = time.time()
    hits = [t for t in _REG_HITS.get(ip, []) if now - t < 3600]
    _REG_HITS[ip] = hits
    return ip, len(hits) < config.REGISTER_LIMIT_PER_HOUR


@bp.get("/welcome-offer")
def welcome_offer_public():
    """What a new account gets. Public, so the sign-up form can show it."""
    W = load_settings(g.db)["new_account_offer"]
    on = bool(W["enabled"]) and (W["discount_pct"] > 0 or W["bonus_points_pct"] > 0)
    return jsonify({"enabled": on, "discount_pct": W["discount_pct"], "bonus_points_pct": W["bonus_points_pct"], "max_discount": W["max_discount"]})


@bp.post("/register")
def register():
    """Self sign-up for a new customer. They start with no history, get the new-account offer and are signed in."""
    d = body()
    name = str(d.get("name", "")).strip()
    username = str(d.get("username", "")).strip().lower()
    pw = str(d.get("password", ""))
    if len(name) < 2 or len(name) > 60:
        return err("Name must be 2 to 60 characters")
    if len(username) < 3 or len(username) > 24 or not username.replace("_", "").isalnum():
        return err("Username must be 3 to 24 letters, numbers or underscores")
    if len(pw) < 4:
        return err("Password needs at least 4 characters")
    if one(g.db, "SELECT 1 x FROM users WHERE username=?", (username,)):
        return err("That username is already taken")
    ip, ok = _register_allowed()
    if not ok:
        return err("Too many accounts created from this connection. Please try again later.", 429)
    offer = 1 if load_settings(g.db)["new_account_offer"]["enabled"] else 0
    uid = g.db.execute("INSERT INTO users(username, password_hash, role, display_name) VALUES(?,?, 'customer',?)",
                       (username, generate_password_hash(pw), name)).lastrowid
    cid = g.db.execute("INSERT INTO customers(user_id, name, city, email, joined_at, persona, is_showcase, new_account_offer) VALUES(?,?,?,?,?, 'manual', 0, ?)",
                       (uid, name, str(d.get("city", "")).strip() or None, "%s@example.com" % username, iso(utcnow()), offer)).lastrowid
    audit(g.db, username, "register", "customer %d" % cid)
    g.db.commit()
    _REG_HITS.setdefault(ip, []).append(time.time())
    analytics.mark_dirty()
    session.clear()
    session["uid"] = uid
    session.permanent = True
    g.user = one(g.db, "SELECT * FROM users WHERE id=?", (uid,))
    g.cid = cid
    return jsonify(_me()), 201


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
@login_required
def me():
    return jsonify(_me())


@bp.get("/demo-logins")
def demo_logins():
    """Convenience list for the login page: the admin and the ten showcase personas."""
    # "quick" means the one-click card can sign in with the published demo password.
    out = [{"username": "admin", "name": "Store Admin", "label": "Admin console", "blurb": "Manage products, stock, rules and approvals.",
            "quick": config.ADMIN_PASSWORD == "1234"}]
    for key, P in sorted(PERSONAS.items(), key=lambda kv: kv[1]["showcase_user"]):
        out.append({"username": "user%d" % P["showcase_user"], "name": P["name"], "label": P["label"], "blurb": P["blurb"],
                    "quick": config.DEMO_PASSWORD == "1234"})
    return jsonify(out)


# ============ shop ============
@bp.get("/categories")
@login_required
def categories():
    return jsonify(store.categories(g.db))


@bp.get("/products")
@login_required
def products():
    a = request.args
    return jsonify(store.list_products(g.db, a.get("category") or None, (a.get("q") or "").strip() or None, a.get("sort", "relevance"),
                                       a.get("page", 1), 24, a.get("promo") == "1", a.get("in_stock") == "1"))


@bp.post("/cart/quote")
@customer_required
def cart_quote():
    d = body()
    try:
        return jsonify(store.quote(g.db, g.cid, d.get("items"), d.get("redeem_points", 0)))
    except store.StoreError as e:
        return err(str(e))


@bp.post("/checkout")
@customer_required
def checkout():
    d = body()
    try:
        order = store.checkout(g.db, g.cid, d.get("items"), d.get("redeem_points", 0))
    except (store.StoreError, ValueError) as e:
        return err(str(e))
    return jsonify({"order": order, "tier": loyalty.tier_info(g.db, g.cid), "points": loyalty.points_summary(g.db, g.cid)})


# ============ customer portal ============
@bp.get("/customer/overview")
@customer_required
def customer_overview():
    cid = g.cid
    c = one(g.db, "SELECT id, name, city, joined_at FROM customers WHERE id=?", (cid,))
    S = load_settings(g.db)
    a = agent.analyze(g.db, cid, k=12)
    f = dict(a["features"])
    f.pop("top_categories", None)
    return jsonify({
        "profile": {**c, "username": g.user["username"]}, "tier": a["tier"], "points": a["points"], "insights": analytics.customer_insights(g.db, cid),
        "traits": a["traits"], "next_best_action": a["next_best_action"], "actions": a["actions"][:4],
        "active_offer": store.active_offer(g.db, cid), "campaigns": loyalty.active_campaigns(g.db), "new_account_offer": store.new_account_offer(g.db, cid, S),
        "tiers": S["loyalty"]["tiers"], "rules": {k: S["loyalty"][k] for k in ("points_per_100", "point_value", "min_redeem", "max_redeem_pct", "expiry_days")},
        "behaviour": {k: f.get(k) for k in ("n_orders", "aov", "median_gap", "recency_days", "discount_share")},
    })


@bp.get("/customer/orders")
@customer_required
def customer_orders():
    return jsonify(store.customer_orders(g.db, g.cid))


@bp.post("/customer/orders/<int:oid>/cancel")
@customer_required
def customer_cancel(oid):
    try:
        return jsonify(store.set_order_status(g.db, oid, "cancelled", g.user["username"], customer_id=g.cid))
    except store.StoreError as e:
        return err(str(e))


@bp.get("/customer/points")
@customer_required
def customer_points():
    return jsonify({"summary": loyalty.points_summary(g.db, g.cid), "tier": loyalty.tier_info(g.db, g.cid),
                    "ledger": loyalty.ledger(g.db, g.cid, 80), "campaigns": loyalty.active_campaigns(g.db),
                    "tiers": load_settings(g.db)["loyalty"]["tiers"]})


@bp.get("/customer/recommendations")
@customer_required
def customer_recs():
    k = min(int(request.args.get("k", 12)), 40)
    return jsonify(recommender.for_customer(g.db, g.cid, k=k))


@bp.get("/customer/promotions")
@customer_required
def customer_promotions():
    return jsonify(awareness.for_customer(g.db, g.cid))


@bp.post("/customer/events")
@customer_required
def customer_event():
    d = body()
    try:
        ok = awareness.record(g.db, g.cid, int(d.get("campaign_id", 0)), str(d.get("kind", "")), d.get("surface", "home"))
    except (ValueError, TypeError):
        return err("Invalid event")
    except LookupError:
        return err("Not found", 404)
    g.db.commit()
    return jsonify({"ok": True, "recorded": ok})


@bp.post("/customer/offers/activate")
@customer_required
def activate_offer():
    try:
        return jsonify(agent.activate_offer(g.db, g.cid, str(body().get("code", ""))))
    except ValueError as e:
        return err(str(e))


@bp.post("/customer/chat")
@customer_required
def customer_chat():
    return jsonify(agent.chat(g.db, g.cid, str(body().get("message", ""))[:300]))


# ============ admin: dashboard ============
@bp.get("/admin/overview")
@admin_required
def admin_overview():
    S = load_settings(g.db)
    m = analytics.get_model(g.db)
    bulk = loyalty.tier_names_bulk(g.db, S)
    names = [t["name"] for t in S["loyalty"]["tiers"]]
    tiers = Counter(names[bulk.get(cid, (0, 0))[0]] for cid in m.cust_ids)
    segs = Counter(f["segment"] for f in m.feat.values())
    high_churn = [f for f in m.feat.values() if (f.get("churn_risk") or 0) >= 0.5 and f["n_orders"] >= 3]
    out = analytics.admin_overview(g.db)
    out.update(tier_distribution=[{"tier": n, "count": tiers.get(n, 0)} for n in names],
               segments=[{"segment": s, "count": c} for s, c in segs.most_common()],
               high_churn_count=len(high_churn), value_at_risk=round(sum(f["clv_12m"] for f in high_churn)),
               points=loyalty.liability(g.db, S), agent=agent.portfolio(g.db), churn_model=m.churn_metrics,
               campaigns=loyalty.active_campaigns(g.db), settings_mode=S["approval"]["mode"])
    return jsonify(out)


@bp.get("/admin/model-quality")
@admin_required
def model_quality():
    cache = getattr(bp, "_eval_cache", None)
    if cache and time.time() - cache[0] < 300 and not request.args.get("refresh"):
        return jsonify(cache[1])
    ev = recommender.evaluate(g.db)
    m = analytics.get_model(g.db)
    out = {"recommender": ev, "churn": m.churn_metrics, "evaluated_at": iso(utcnow())}
    bp._eval_cache = (time.time(), out)
    return jsonify(out)


@bp.get("/admin/personas")
@admin_required
def admin_personas():
    """Ground-truth persona vs what the AI inferred from raw orders, to prove the behaviours are recoverable."""
    m = analytics.get_model(g.db)
    S = load_settings(g.db)
    bulk = loyalty.tier_names_bulk(g.db, S)
    names = [t["name"] for t in S["loyalty"]["tiers"]]
    groups = defaultdict(list)
    for r in rows(g.db, "SELECT id, persona FROM customers"):
        groups[r["persona"]].append(r["id"])
    out = []
    for key, P in sorted(PERSONAS.items(), key=lambda kv: kv[1]["showcase_user"]):
        ids = [i for i in groups.get(key, []) if m.feat[i]["n_orders"] > 0]
        feats = [m.feat[i] for i in ids]

        def avg(k):
            v = [f[k] for f in feats if f.get(k) is not None]
            return round(sum(v) / len(v), 3) if v else None
        cats = Counter()
        for f in feats:
            for c in f["top_categories"][:1]:
                cats[c["name"]] += 1
        traits = Counter(t["label"] for f in feats for t in analytics.shopper_traits(f))
        out.append({"key": key, "label": P["label"], "name": P["name"], "username": "user%d" % P["showcase_user"], "blurb": P["blurb"],
                    "customers": len(groups.get(key, [])), "avg_orders_12m": avg("n_orders"), "avg_order_value": avg("aov"),
                    "avg_spend_12m": avg("spend_12m"), "discount_share": avg("discount_share"), "premium_share": avg("premium_share"),
                    "festival_share": avg("festival_share"), "churn_risk": avg("churn_risk"), "return_rate": avg("return_rate"),
                    "top_categories": [c for c, _ in cats.most_common(2)], "inferred_traits": [t for t, _ in traits.most_common(3)],
                    "tiers": dict(Counter(names[bulk.get(i, (0, 0))[0]] for i in groups.get(key, [])))})
    return jsonify(out)


# ============ admin: approvals ============
def _approval_row(o, tier_by_cust, S):
    items = rows(g.db, "SELECT p.name, p.emoji, oi.qty FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=? LIMIT 6", (o["id"],))
    ti = tier_by_cust.get(o["customer_id"], (0, 0))[0]
    o["flags"] = json.loads(o.pop("risk_flags") or "[]")
    o["items"] = items
    o["tier"] = S["loyalty"]["tiers"][ti]["name"]
    o["suggestion"] = "approve" if o["risk_score"] < 40 else ("review" if o["risk_score"] < 70 else "hold")
    return o


@bp.get("/admin/approvals")
@admin_required
def approvals():
    S = load_settings(g.db)
    tiers = loyalty.tier_names_bulk(g.db, S)
    hist = request.args.get("status") == "history"
    cond = "o.points_status<>'pending' AND o.reviewed_by IS NOT NULL" if hist else "o.points_status='pending'"
    order = "o.reviewed_at DESC" if hist else "o.risk_score DESC, o.created_at DESC"
    data = rows(g.db, "SELECT o.id, o.customer_id, c.name customer, o.created_at, o.status, o.subtotal, o.total_paid, o.points_redeemed, o.points_earned, "
                      "o.points_status, o.risk_score, o.risk_flags, o.reviewed_by, o.reviewed_at, o.review_note FROM orders o JOIN customers c ON c.id=o.customer_id "
                      "WHERE " + cond + " ORDER BY " + order + " LIMIT 120")
    return jsonify({"items": [_approval_row(o, tiers, S) for o in data], "mode": S["approval"]["mode"],
                    "threshold": S["approval"]["large_order_threshold"], "risk_threshold": S["approval"]["risk_threshold"]})


def _decide(oid, action, points=None, note=""):
    actor = g.user["username"]
    if action == "approve":
        loyalty.approve_order(g.db, oid, actor, points, note)
    elif action == "reject":
        loyalty.reject_order(g.db, oid, actor, note)
    else:
        raise ValueError("Unknown action")


@bp.post("/admin/approvals/<int:oid>")
@admin_required
def approval_decide(oid):
    d = body()
    try:
        _decide(oid, d.get("action"), d.get("points"), str(d.get("note", ""))[:200])
        g.db.commit()
    except ValueError as e:
        g.db.rollback()
        return err(str(e))
    analytics.mark_dirty()
    return jsonify({"ok": True})


@bp.post("/admin/approvals/bulk")
@admin_required
def approval_bulk():
    d = body()
    done, failed = 0, 0
    for oid in d.get("order_ids", [])[:200]:
        try:
            _decide(int(oid), d.get("action"), None, str(d.get("note", ""))[:200])
            done += 1
        except ValueError:
            failed += 1
    g.db.commit()
    analytics.mark_dirty()
    return jsonify({"done": done, "failed": failed})


# ============ admin: orders ============
@bp.get("/admin/orders")
@admin_required
def admin_orders():
    a = request.args
    where, args = ["1=1"], []
    if a.get("status"):
        where.append("o.status=?")
        args.append(a["status"])
    if a.get("q"):
        q = a["q"].strip()
        where.append("(c.name LIKE ? OR CAST(o.id AS TEXT)=?)")
        args += ["%" + q + "%", q]
    page = max(1, int(a.get("page", 1)))
    w = " AND ".join(where)
    total = one(g.db, "SELECT COUNT(*) n FROM orders o JOIN customers c ON c.id=o.customer_id WHERE " + w, args)["n"]
    data = rows(g.db, "SELECT o.id, o.customer_id, c.name customer, o.created_at, o.status, o.total_paid, o.points_earned, o.points_status, o.risk_score "
                      "FROM orders o JOIN customers c ON c.id=o.customer_id WHERE " + w + " ORDER BY o.created_at DESC LIMIT 30 OFFSET ?", args + [(page - 1) * 30])
    return jsonify({"items": data, "total": total, "page": page, "pages": max(1, -(-total // 30))})


@bp.get("/admin/orders/<int:oid>")
@admin_required
def admin_order(oid):
    o = store.get_order(g.db, oid)
    return jsonify(o) if o else err("Not found", 404)


@bp.post("/admin/orders/<int:oid>/status")
@admin_required
def admin_order_status(oid):
    try:
        return jsonify(store.set_order_status(g.db, oid, str(body().get("status")), g.user["username"]))
    except store.StoreError as e:
        return err(str(e))


# ============ admin: products ============
def _product_payload(d, partial=False):
    out = {}
    for k in ("name", "emoji", "category", "brand", "unit", "family", "brand_tier"):
        if k in d:
            out[k] = str(d[k]).strip()
    for k in ("price", "mrp", "cost"):
        if k in d:
            out[k] = float(d[k])
            if out[k] < 0:
                raise ValueError("%s cannot be negative" % k)
    for k in ("stock", "reorder_level"):
        if k in d:
            out[k] = int(d[k])
            if out[k] < 0:
                raise ValueError("%s cannot be negative" % k)
    for k in ("active", "consumable"):
        if k in d:
            out[k] = 1 if d[k] else 0
    if "category" in out and out["category"] not in catsvc.load(g.db)[1]:
        raise ValueError("Unknown category")
    if "brand_tier" in out and out["brand_tier"] not in ("value", "standard", "premium"):
        raise ValueError("brand_tier must be value, standard or premium")
    if "name" in out and not out["name"]:
        raise ValueError("Name is required")
    if "price" in out and "mrp" in out and out["mrp"] < out["price"]:
        raise ValueError("MRP cannot be lower than the selling price")
    return out


@bp.get("/admin/products")
@admin_required
def admin_products():
    a = request.args
    where, args = ["1=1"], []
    if a.get("category"):
        where.append("category=?")
        args.append(a["category"])
    if a.get("q"):
        where.append("(name LIKE ? OR sku LIKE ?)")
        args += ["%" + a["q"].strip() + "%"] * 2
    if a.get("stock") == "low":
        where.append("stock>0 AND stock<=reorder_level")
    elif a.get("stock") == "out":
        where.append("stock=0")
    page = max(1, int(a.get("page", 1)))
    w = " AND ".join(where)
    total = one(g.db, "SELECT COUNT(*) n FROM products WHERE " + w, args)["n"]
    data = rows(g.db, "SELECT * FROM products WHERE " + w + " ORDER BY id LIMIT 40 OFFSET ?", args + [(page - 1) * 40])
    return jsonify({"items": data, "total": total, "page": page, "pages": max(1, -(-total // 40))})


@bp.post("/admin/products")
@admin_required
def admin_product_create():
    try:
        p = _product_payload(body())
        for k in ("name", "category", "price"):
            if k not in p:
                raise ValueError("%s is required" % k)
        cmeta = catsvc.load(g.db)[1][p["category"]]
        p.setdefault("emoji", cmeta["emoji"])
        p.setdefault("mrp", p["price"])
        p.setdefault("cost", round(p["price"] * 0.75, 2))
        p.setdefault("stock", 0)
        p.setdefault("brand", "House Brand")
        p.setdefault("brand_tier", "standard")
        p.setdefault("unit", "Standard")
        p.setdefault("family", p["name"])
        p.setdefault("consumable", 1 if cmeta["cycle"] else 0)
        p.setdefault("reorder_level", 10)
        p.setdefault("active", 1)
    except (ValueError, TypeError) as e:
        return err(str(e))
    nxt = one(g.db, "SELECT COALESCE(MAX(id),0)+1 n FROM products")["n"]
    cols = list(p) + ["sku", "created_at", "rating"]
    vals = list(p.values()) + ["SKU%05d" % nxt, iso(utcnow()), 4.0]
    cur = g.db.execute("INSERT INTO products(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), vals)
    audit(g.db, g.user["username"], "product_create", "%s (id %d)" % (p["name"], cur.lastrowid))
    g.db.commit()
    analytics.mark_dirty()
    return jsonify(one(g.db, "SELECT * FROM products WHERE id=?", (cur.lastrowid,))), 201


@bp.put("/admin/products/<int:pid>")
@admin_required
def admin_product_update(pid):
    cur = one(g.db, "SELECT * FROM products WHERE id=?", (pid,))
    if not cur:
        return err("Not found", 404)
    try:
        p = _product_payload(body())
        price, mrp = p.get("price", cur["price"]), p.get("mrp", cur["mrp"])
        if mrp < price:
            if "mrp" not in p:
                p["mrp"] = price
            else:
                raise ValueError("MRP cannot be lower than the selling price")
    except (ValueError, TypeError) as e:
        return err(str(e))
    if p:
        g.db.execute("UPDATE products SET %s WHERE id=?" % ",".join("%s=?" % k for k in p), list(p.values()) + [pid])
        audit(g.db, g.user["username"], "product_update", "id %d: %s" % (pid, json.dumps(p)))
        g.db.commit()
        analytics.mark_dirty()
    return jsonify(one(g.db, "SELECT * FROM products WHERE id=?", (pid,)))


@bp.post("/admin/products/<int:pid>/restock")
@admin_required
def admin_restock(pid):
    qty = int(body().get("qty", 0))
    if qty <= 0:
        return err("Enter a positive quantity")
    g.db.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, pid))
    audit(g.db, g.user["username"], "restock", "product %d +%d" % (pid, qty))
    g.db.commit()
    analytics.mark_dirty()
    return jsonify(one(g.db, "SELECT * FROM products WHERE id=?", (pid,)))


# ============ admin: customers ============
@bp.get("/admin/customers")
@admin_required
def admin_customers():
    a = request.args
    S = load_settings(g.db)
    m = analytics.get_model(g.db)
    bulk = loyalty.tier_names_bulk(g.db, S)
    tnames = [t["name"] for t in S["loyalty"]["tiers"]]
    pts = {r["customer_id"]: r["v"] for r in g.db.execute(
        "SELECT customer_id, SUM(remaining) v FROM points_ledger WHERE status='active' AND kind IN ('earn','bonus','refund') GROUP BY customer_id").fetchall()}
    q = (a.get("q") or "").strip().lower()
    unames = usernames(g.db)
    items = []
    for c in rows(g.db, "SELECT id, name, city, joined_at, persona, is_showcase FROM customers"):
        f = m.feat[c["id"]]
        tier = tnames[bulk.get(c["id"], (0, 0))[0]]
        if q and q not in c["name"].lower() and q != unames.get(c["id"], "").lower():
            continue
        if a.get("tier") and a["tier"] != tier:
            continue
        if a.get("segment") and a["segment"] != f["segment"]:
            continue
        items.append({"id": c["id"], "username": unames.get(c["id"], ""), "name": c["name"], "city": c["city"], "tier": tier, "points": int(pts.get(c["id"], 0)),
                      "segment": f["segment"], "orders_12m": f["n_orders"], "spend_12m": round(f["spend_12m"]), "recency_days": round(f["recency_days"]) if f["recency_days"] is not None else None,
                      "churn_risk": f.get("churn_risk"), "clv_12m": f["clv_12m"], "persona": persona_label(c["persona"]), "is_showcase": c["is_showcase"]})
    key = {"spend": lambda x: -x["spend_12m"], "churn": lambda x: -(x["churn_risk"] or 0), "clv": lambda x: -x["clv_12m"], "points": lambda x: -x["points"],
           "name": lambda x: x["name"]}.get(a.get("sort", "id"), lambda x: x["id"])
    items.sort(key=key)
    page = max(1, int(a.get("page", 1)))
    return jsonify({"items": items[(page - 1) * 30: page * 30], "total": len(items), "page": page, "pages": max(1, -(-len(items) // 30)),
                    "tiers": tnames, "segments": sorted({f["segment"] for f in m.feat.values()})})


@bp.get("/admin/customers/<int:cid>")
@admin_required
def admin_customer(cid):
    c = one(g.db, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c:
        return err("Not found", 404)
    a = agent.analyze(g.db, cid, k=8)
    c["username"] = usernames(g.db).get(cid, "")
    c["persona_label"] = persona_label(c["persona"])
    return jsonify({"customer": c, "analysis": a, "insights": analytics.customer_insights(g.db, cid), "orders": store.customer_orders(g.db, cid, 15),
                    "ledger": loyalty.ledger(g.db, cid, 40), "offers": rows(g.db, "SELECT * FROM offers WHERE customer_id=? ORDER BY id DESC LIMIT 5", (cid,))})


@bp.put("/admin/customers/<int:cid>")
@admin_required
def admin_customer_update(cid):
    d = body()
    name, city = str(d.get("name", "")).strip(), str(d.get("city", "")).strip()
    if not name:
        return err("Name is required")
    g.db.execute("UPDATE customers SET name=?, city=? WHERE id=?", (name, city, cid))
    g.db.execute("UPDATE users SET display_name=? WHERE id=(SELECT user_id FROM customers WHERE id=?)", (name, cid))
    audit(g.db, g.user["username"], "customer_update", "customer %d" % cid)
    g.db.commit()
    return jsonify({"ok": True})


@bp.post("/admin/customers/<int:cid>/bonus")
@admin_required
def admin_bonus(cid):
    d = body()
    try:
        pts = int(d.get("points", 0))
    except (TypeError, ValueError):
        return err("Points must be a number")
    if pts <= 0 or pts > 10000:
        return err("Enter between 1 and 10,000 points")
    if not str(d.get("reason", "")).strip():
        return err("A reason is required for manual bonus points")
    loyalty.grant_bonus(g.db, cid, pts, str(d["reason"]).strip()[:200], g.user["username"])
    g.db.commit()
    return jsonify({"ok": True, "points": loyalty.points_summary(g.db, cid)})


@bp.post("/admin/customers")
@admin_required
def admin_customer_create():
    """Add a customer account by hand. They start with no history, so they appear as New and the agent uses cold-start picks."""
    d = body()
    name, city, email = str(d.get("name", "")).strip(), str(d.get("city", "")).strip(), str(d.get("email", "")).strip()
    if len(name) < 2 or len(name) > 60:
        return err("Name must be 2 to 60 characters")
    if email and ("@" not in email or len(email) > 80):
        return err("Enter a valid email address or leave it empty")
    nxt = one(g.db, "SELECT COALESCE(MAX(id),0)+1 n FROM customers")["n"]
    username = str(d.get("username", "")).strip().lower() or "user%d" % nxt
    if not username.replace("_", "").isalnum() or len(username) > 24:
        return err("Username can only use letters, numbers and underscores (24 characters max)")
    if one(g.db, "SELECT 1 x FROM users WHERE username=?", (username,)):
        return err("That username is already taken")
    pw = str(d.get("password", "")) or config.DEMO_PASSWORD
    if len(pw) < 4:
        return err("Password needs at least 4 characters")
    cur = g.db.execute("INSERT INTO users(username, password_hash, role, display_name) VALUES(?,?, 'customer',?)", (username, generate_password_hash(pw), name))
    offer = 1 if load_settings(g.db)["new_account_offer"]["enabled"] else 0
    cid = g.db.execute("INSERT INTO customers(user_id, name, city, email, joined_at, persona, is_showcase, new_account_offer) VALUES(?,?,?,?,?, 'manual', 0, ?)",
                       (cur.lastrowid, name, city or None, email or "%s@example.com" % username, iso(utcnow()), offer)).lastrowid
    welcome = int(d.get("welcome_points", 0) or 0)
    if welcome:
        if welcome < 0 or welcome > 10000:
            g.db.rollback()
            return err("Welcome points must be between 0 and 10,000")
        loyalty.grant_bonus(g.db, cid, welcome, "Welcome bonus", g.user["username"])
    audit(g.db, g.user["username"], "customer_create", "%s (id %d)" % (username, cid))
    g.db.commit()
    analytics.mark_dirty()
    return jsonify({"ok": True, "id": cid, "username": username, "password_note": "default password" if not d.get("password") else "custom password"}), 201


@bp.post("/admin/customers/<int:cid>/password")
@admin_required
def admin_customer_password(cid):
    pw = str(body().get("password", ""))
    if len(pw) < 4:
        return err("Password needs at least 4 characters")
    c = one(g.db, "SELECT user_id FROM customers WHERE id=?", (cid,))
    if not c:
        return err("Not found", 404)
    g.db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), c["user_id"]))
    audit(g.db, g.user["username"], "customer_password", "customer %d" % cid)
    g.db.commit()
    return jsonify({"ok": True})


# ============ admin: admins and categories ============
@bp.get("/admin/admins")
@admin_required
def admin_admins():
    return jsonify(rows(g.db, "SELECT id, username, display_name FROM users WHERE role='admin' ORDER BY id"))


@bp.post("/admin/admins")
@admin_required
def admin_admin_create():
    d = body()
    name, username, pw = str(d.get("name", "")).strip(), str(d.get("username", "")).strip().lower(), str(d.get("password", ""))
    if len(name) < 2 or len(name) > 60:
        return err("Name must be 2 to 60 characters")
    if len(username) < 3 or len(username) > 24 or not username.replace("_", "").isalnum():
        return err("Username must be 3 to 24 letters, numbers or underscores")
    if len(pw) < 4:
        return err("Password needs at least 4 characters")
    if one(g.db, "SELECT 1 x FROM users WHERE username=?", (username,)):
        return err("That username is already taken")
    uid = g.db.execute("INSERT INTO users(username, password_hash, role, display_name) VALUES(?,?, 'admin',?)",
                       (username, generate_password_hash(pw), name)).lastrowid
    audit(g.db, g.user["username"], "admin_create", username)
    g.db.commit()
    return jsonify({"ok": True, "id": uid, "username": username}), 201


@bp.post("/admin/categories")
@admin_required
def admin_category_create():
    d = body()
    try:
        c = catsvc.create(g.db, d.get("name"), d.get("emoji"), d.get("color"), d.get("cycle"))
    except ValueError as e:
        return err(str(e))
    audit(g.db, g.user["username"], "category_create", c["name"])
    g.db.commit()
    analytics.mark_dirty()
    return jsonify(c), 201


# ============ admin: segmentation and product awareness campaigns ============
@bp.get("/admin/segments")
@admin_required
def admin_segments():
    return jsonify(segsvc.summary(g.db))


@bp.get("/admin/promotions")
@admin_required
def admin_promotions():
    return jsonify(awareness.list_all(g.db))


@bp.post("/admin/promotions/preview")
@admin_required
def admin_promotion_preview():
    try:
        return jsonify(awareness.preview(g.db, body()))
    except ValueError as e:
        return err(str(e))


@bp.post("/admin/promotions")
@admin_required
def admin_promotion_create():
    try:
        cid = awareness.create(g.db, body(), g.user["username"])
    except ValueError as e:
        return err(str(e))
    g.db.commit()
    return jsonify(awareness.get(g.db, cid)), 201


@bp.get("/admin/promotions/<int:pid>")
@admin_required
def admin_promotion(pid):
    try:
        return jsonify(awareness.get(g.db, pid))
    except LookupError:
        return err("Not found", 404)


def _promo_action(fn, *args):
    try:
        fn(g.db, *args, g.user["username"])
    except LookupError:
        return err("Not found", 404)
    except ValueError as e:
        return err(str(e))
    g.db.commit()
    return jsonify(awareness.get(g.db, args[0])) if fn is not awareness.remove else jsonify({"ok": True})


@bp.post("/admin/promotions/<int:pid>/status")
@admin_required
def admin_promotion_status(pid):
    try:
        awareness.set_status(g.db, pid, str(body().get("status", "")), g.user["username"])
    except LookupError:
        return err("Not found", 404)
    except ValueError as e:
        return err(str(e))
    g.db.commit()
    return jsonify(awareness.get(g.db, pid))


@bp.post("/admin/promotions/<int:pid>/simulate")
@admin_required
def admin_promotion_simulate(pid):
    return _promo_action(awareness.simulate, pid)


@bp.delete("/admin/promotions/<int:pid>/simulated")
@admin_required
def admin_promotion_clear_sim(pid):
    return _promo_action(awareness.clear_simulated, pid)


@bp.delete("/admin/promotions/<int:pid>")
@admin_required
def admin_promotion_delete(pid):
    return _promo_action(awareness.remove, pid)


# ============ admin: rules, campaigns, audit ============
def _validate_settings(new):
    S = load_settings(g.db)
    for sec, vals in (new or {}).items():
        if sec not in S or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k == "tiers":
                continue
            if k in S[sec]:
                if k == "enabled":
                    S[sec][k] = v in (True, 1, "1", "true", "True")
                elif k == "mode":
                    if v not in ("flagged_only", "all"):
                        raise ValueError("Approval mode must be flagged_only or all")
                    S[sec][k] = v
                else:
                    v = float(v)
                    if v < 0:
                        raise ValueError("%s cannot be negative" % k)
                    S[sec][k] = int(v) if float(S[sec][k]).is_integer() and k not in ("points_per_100", "point_value", "discount_pct", "bonus_points_pct") and not k.startswith("w_") else v
    W = S["new_account_offer"]
    if W["discount_pct"] > 50 or W["bonus_points_pct"] > 100:
        raise ValueError("New-account discount can be at most 50% and extra points at most 100%")
    tiers = (new or {}).get("loyalty", {}).get("tiers")
    if tiers:
        if not 2 <= len(tiers) <= 6:
            raise ValueError("Use between 2 and 6 tiers")
        clean, last = [], -1
        for i, t in enumerate(tiers):
            name, ms, mult = str(t.get("name", "")).strip(), float(t.get("min_spend", 0)), float(t.get("multiplier", 1))
            if not name or ms <= last and i > 0 or (i == 0 and ms != 0) or mult < 1 or mult > 10:
                raise ValueError("Tiers need unique names, a first threshold of 0, rising thresholds and a multiplier of 1 or more")
            clean.append({"name": name, "min_spend": ms, "multiplier": mult, "perks": t.get("perks") or []})
            last = ms
        if len({t["name"] for t in clean}) != len(clean):
            raise ValueError("Tier names must be unique")
        S["loyalty"]["tiers"] = clean
    return S


@bp.get("/admin/settings")
@admin_required
def get_settings():
    return jsonify({"settings": load_settings(g.db), "defaults": DEFAULT_SETTINGS})


@bp.put("/admin/settings")
@admin_required
def put_settings():
    try:
        S = _validate_settings(body())
    except (ValueError, TypeError) as e:
        return err(str(e))
    save_settings(g.db, S)
    audit(g.db, g.user["username"], "settings_update", "Loyalty/approval/offer/recommender settings changed")
    g.db.commit()
    analytics.mark_dirty()
    return jsonify(S)


@bp.post("/admin/settings/reset")
@admin_required
def reset_settings():
    save_settings(g.db, json.loads(json.dumps(DEFAULT_SETTINGS)))
    audit(g.db, g.user["username"], "settings_reset", "")
    g.db.commit()
    return jsonify(load_settings(g.db))


@bp.get("/admin/campaigns")
@admin_required
def get_campaigns():
    return jsonify(rows(g.db, "SELECT * FROM campaigns ORDER BY id DESC"))


@bp.post("/admin/campaigns")
@admin_required
def create_campaign():
    d = body()
    try:
        mult, days = float(d.get("multiplier", 2)), int(d.get("days", 14))
        cat = d.get("category") or None
        if not str(d.get("name", "")).strip() or mult < 1 or mult > 10 or days < 1 or (cat and cat not in catsvc.load(g.db)[1]):
            raise ValueError
    except (TypeError, ValueError):
        return err("Enter a name, a multiplier between 1 and 10, a number of days and a valid category")
    now = utcnow()
    g.db.execute("INSERT INTO campaigns(name, category, multiplier, starts_at, ends_at, active) VALUES(?,?,?,?,?,1)",
                 (str(d["name"]).strip(), cat, mult, iso(now), iso(now + timedelta(days=days))))
    audit(g.db, g.user["username"], "campaign_create", str(d["name"]))
    g.db.commit()
    return jsonify({"ok": True}), 201


@bp.put("/admin/campaigns/<int:cid>")
@admin_required
def toggle_campaign(cid):
    g.db.execute("UPDATE campaigns SET active=? WHERE id=?", (1 if body().get("active") else 0, cid))
    g.db.commit()
    return jsonify({"ok": True})


@bp.get("/admin/offers")
@admin_required
def admin_offers():
    return jsonify({"budget": agent.offer_budget(g.db), "items": rows(
        g.db, "SELECT o.*, c.name customer FROM offers o JOIN customers c ON c.id=o.customer_id ORDER BY o.id DESC LIMIT 50")})


@bp.post("/admin/run-expiry")
@admin_required
def run_expiry():
    n = loyalty.expire_points(g.db)
    audit(g.db, g.user["username"], "run_expiry", "%d batches expired" % n)
    g.db.commit()
    return jsonify({"expired_batches": n})


@bp.get("/admin/audit")
@admin_required
def audit_log():
    return jsonify(rows(g.db, "SELECT * FROM audit_log ORDER BY id DESC LIMIT 80"))


@bp.errorhandler(Exception)
def _unexpected(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return err(e.description, e.code)
    import logging
    logging.getLogger("loyaltyiq").exception("Unhandled error")
    return err("Something went wrong on the server", 500)
