"""End-to-end tests through the real HTTP API on a seeded database."""
from datetime import timedelta

from app import db
from app.db import iso, one, rows, utcnow
from app.services import analytics, loyalty
from tests.conftest import find_product, login


# ---------- auth and roles ----------
def test_login_and_roles(client):
    assert client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.get("/api/me").status_code == 401
    me = login(client, "user1")
    assert me["role"] == "customer" and me["customer_id"] == 1 and me["tier"]
    assert client.get("/api/admin/overview").status_code == 403           # customers cannot reach admin
    c2 = client.application.test_client()
    login(c2, "admin")
    assert c2.get("/api/customer/overview").status_code == 403            # admin has no customer account
    assert c2.get("/api/admin/overview").status_code == 200


def test_demo_logins_list_ten_personas(client):
    d = client.get("/api/demo-logins").get_json()
    assert d[0]["username"] == "admin" and len(d) == 11


# ---------- catalogue ----------
def test_catalogue_is_large_and_searchable(client):
    login(client, "user2")
    cats = client.get("/api/categories").get_json()
    assert len(cats) >= 16 and sum(c["count"] for c in cats) >= 1000
    r = client.get("/api/products?q=rice").get_json()
    assert r["total"] > 5 and all("rice" in (p["name"] + p["family"]).lower() for p in r["items"])
    r = client.get("/api/products?category=electronics&sort=price_desc").get_json()
    prices = [p["price"] for p in r["items"]]
    assert prices == sorted(prices, reverse=True) and r["items"][0]["emoji"]


# ---------- checkout, stock, points ----------
def test_checkout_updates_stock_orders_and_points(client, conn):
    login(client, "user4")
    p = find_product(conn, "dairy", min_stock=50)
    before = one(conn, "SELECT stock FROM products WHERE id=?", (p["id"],))["stock"]
    pts_before = client.get("/api/customer/points").get_json()["summary"]["active"]
    q = client.post("/api/cart/quote", json={"items": [{"product_id": p["id"], "qty": 3}]}).get_json()
    assert q["subtotal"] == round(p["price"] * 3, 2) and q["points_estimate"] >= 0
    r = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 3}]})
    assert r.status_code == 200, r.get_json()
    o = r.get_json()["order"]
    assert o["status"] == "placed" and o["points_status"] == "approved"      # small order: auto-approved
    assert one(conn, "SELECT stock FROM products WHERE id=?", (p["id"],))["stock"] == before - 3
    pts_after = client.get("/api/customer/points").get_json()["summary"]["active"]
    assert pts_after == pts_before + o["points_earned"]
    assert any(x["id"] == o["id"] for x in client.get("/api/customer/orders").get_json())


def test_cannot_oversell_or_buy_empty_cart(client, conn):
    login(client, "user5")
    p = find_product(conn, "books", min_stock=5)
    r = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": p["stock"] + 1}]})
    assert r.status_code == 400 and "left" in r.get_json()["error"].lower()
    assert client.post("/api/checkout", json={"items": []}).status_code == 400
    conn.execute("UPDATE products SET stock=0 WHERE id=?", (p["id"],))
    conn.commit()
    r = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 1}]})
    assert r.status_code == 400 and "out of stock" in r.get_json()["error"].lower()


def test_large_order_goes_to_approval_queue_then_admin_approves(client, admin, conn):
    login(client, "user6")
    p = find_product(conn, "electronics", min_price=15000, min_stock=3)
    items = [{"product_id": p["id"], "qty": 2}]
    q = client.post("/api/cart/quote", json={"items": items}).get_json()
    assert q["may_need_review"] is True
    o = client.post("/api/checkout", json={"items": items}).get_json()["order"]
    assert o["points_status"] == "pending" and any(f["code"] == "LARGE_ORDER" for f in o["flags"])
    pts = client.get("/api/customer/points").get_json()["summary"]
    assert pts["pending"] >= o["points_earned"] > 0
    queue = admin.get("/api/admin/approvals").get_json()
    row = next(x for x in queue["items"] if x["id"] == o["id"])
    assert row["risk_score"] >= 40 and row["customer"]
    active_before = pts["active"]
    assert admin.post("/api/admin/approvals/%d" % o["id"], json={"action": "approve", "points": 10, "note": "Checked"}).status_code == 200
    after = client.get("/api/customer/points").get_json()["summary"]
    assert after["active"] == active_before + 10 and after["pending"] < pts["pending"]       # adjusted to 10 pts
    assert admin.post("/api/admin/approvals/%d" % o["id"], json={"action": "approve"}).status_code == 400   # already decided
    hist = admin.get("/api/admin/approvals?status=history").get_json()["items"]
    assert any(x["id"] == o["id"] and x["points_status"] == "approved" for x in hist)


def test_admin_can_reject_and_points_never_count(client, admin, conn):
    login(client, "user7")
    p = find_product(conn, "electronics", min_price=15000, min_stock=3)
    o = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 2}]}).get_json()["order"]
    spend_before = client.get("/api/customer/points").get_json()["tier"]["spend_12m"]
    assert admin.post("/api/admin/approvals/%d" % o["id"], json={"action": "reject", "note": "Suspicious"}).status_code == 200
    assert one(conn, "SELECT points_status s FROM orders WHERE id=?", (o["id"],))["s"] == "rejected"
    summary = client.get("/api/customer/points").get_json()
    assert summary["tier"]["spend_12m"] == spend_before           # pending/rejected orders never count towards the tier
    assert not any(x["order_id"] == o["id"] and x["status"] == "active" and x["kind"] == "earn" for x in summary["ledger"])


def test_cancel_restocks_and_reverses_points_and_refunds_redeemed(client, conn):
    login(client, "user2")                                            # Pranav: lots of points
    p = find_product(conn, "kitchen", min_price=1000, max_price=9000, min_stock=10)
    bal = client.get("/api/customer/points").get_json()["summary"]["active"]
    assert bal >= 200
    stock0 = one(conn, "SELECT stock FROM products WHERE id=?", (p["id"],))["stock"]
    q = client.post("/api/cart/quote", json={"items": [{"product_id": p["id"], "qty": 2}], "redeem_points": 100}).get_json()
    assert q["redeem_value"] == 100 and q["total"] == round(q["subtotal"] - 100, 2)
    o = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 2}], "redeem_points": 100}).get_json()["order"]
    mid = client.get("/api/customer/points").get_json()["summary"]["active"]
    assert mid == bal - 100 + o["points_earned"] and o["points_redeemed"] == 100
    r = client.post("/api/customer/orders/%d/cancel" % o["id"])
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    assert one(conn, "SELECT stock FROM products WHERE id=?", (p["id"],))["stock"] == stock0
    end = client.get("/api/customer/points").get_json()["summary"]["active"]
    assert end == bal                                               # earned points reversed, redeemed points refunded
    assert client.post("/api/customer/orders/%d/cancel" % o["id"]).status_code == 400   # cannot cancel twice


def test_redemption_rules(client, conn):
    login(client, "user2")
    p = find_product(conn, "home", min_price=200, max_price=800, min_stock=10)
    items = [{"product_id": p["id"], "qty": 1}]
    assert client.post("/api/cart/quote", json={"items": items, "redeem_points": 50}).status_code == 400    # below minimum
    assert client.post("/api/cart/quote", json={"items": items, "redeem_points": 100000}).status_code == 400  # above balance/cap


def test_fifo_expiry_and_ledger(conn):
    cid = 8
    base = loyalty.points_summary(conn, cid)["active"]
    loyalty.credit_points(conn, cid, None, 500, "active", utcnow() - timedelta(days=400), "old", 365, kind="bonus")
    loyalty.credit_points(conn, cid, None, 300, "active", utcnow() - timedelta(days=10), "fresh", 365, kind="bonus")
    conn.commit()
    s = loyalty.points_summary(conn, cid)                              # sweep expires the 400-day-old batch
    assert s["active"] == base + 300
    assert one(conn, "SELECT COUNT(*) n FROM points_ledger WHERE customer_id=? AND kind='expire' AND points=-500", (cid,))["n"] == 1
    loyalty.redeem_points(conn, cid, 150, None)
    conn.commit()
    assert loyalty.points_summary(conn, cid)["active"] == base + 150


# ---------- tiers ----------
def test_tier_math():
    tiers = [{"min_spend": 0}, {"min_spend": 100}, {"min_spend": 500}]
    assert [loyalty.tier_index(x, tiers) for x in (0, 99, 100, 499, 500, 9999)] == [0, 0, 1, 1, 2, 2]
    LY = {"points_per_100": 1.0}
    pts, b = loyalty.order_points([{"line_total": 1000.0, "category": "x"}], 1000.0, 1000.0, 1.5, LY)
    assert pts == 15 and b["base"] == 10 and b["tier_bonus"] == 5
    pts, b = loyalty.order_points([{"line_total": 1000.0, "category": "x"}], 1000.0, 1000.0, 1.0, LY, [{"category": "x", "multiplier": 2.0}])
    assert pts == 20 and b["campaign_bonus"] == 10


def test_tier_uses_only_approved_spend(conn):
    ti = loyalty.tier_info(conn, 2)
    assert ti["tier"] == "Platinum" and ti["progress"] == 1.0 and ti["next_tier"] is None
    assert loyalty.tier_info(conn, 10)["tier"] == "Bronze"


# ---------- admin data management ----------
def test_admin_product_management(admin, client, conn):
    r = admin.post("/api/admin/products", json={"name": "Test Mango Pickle", "category": "staples", "price": 120, "stock": 40})
    assert r.status_code == 201
    pid = r.get_json()["id"]
    assert admin.post("/api/admin/products", json={"name": "x", "category": "nope", "price": 1}).status_code == 400
    assert admin.put("/api/admin/products/%d" % pid, json={"price": 150, "mrp": 120}).status_code == 400   # mrp < price
    r = admin.put("/api/admin/products/%d" % pid, json={"price": 99, "mrp": 120, "stock": 7})
    assert r.get_json()["price"] == 99 and r.get_json()["stock"] == 7
    assert admin.post("/api/admin/products/%d/restock" % pid, json={"qty": 10}).get_json()["stock"] == 17
    login(client, "user1")
    found = client.get("/api/products?q=Mango Pickle").get_json()
    assert found["total"] == 1 and found["items"][0]["discount_pct"] == 18
    admin.put("/api/admin/products/%d" % pid, json={"active": False})
    assert client.get("/api/products?q=Mango Pickle").get_json()["total"] == 0           # deactivated items disappear
    assert client.get("/api/admin/products").status_code == 403


def test_settings_change_alters_approval_behaviour(client, admin, conn):
    assert admin.put("/api/admin/settings", json={"approval": {"mode": "bogus"}}).status_code == 400
    assert admin.put("/api/admin/settings", json={"loyalty": {"tiers": [{"name": "A", "min_spend": 5}, {"name": "B", "min_spend": 10}]}}).status_code == 400
    assert admin.put("/api/admin/settings", json={"approval": {"mode": "all"}}).status_code == 200
    try:
        login(client, "user8")
        p = find_product(conn, "snacks", max_price=100, min_stock=10)
        o = client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 1}]}).get_json()["order"]
        assert o["points_status"] == "pending"                   # even a tiny order is queued in "all" mode
        admin.post("/api/admin/approvals/%d" % o["id"], json={"action": "approve"})
    finally:
        admin.put("/api/admin/settings", json={"approval": {"mode": "flagged_only"}})


def test_admin_bonus_requires_reason_and_credits(admin, client):
    assert admin.post("/api/admin/customers/9/bonus", json={"points": 50, "reason": ""}).status_code == 400
    before = loyalty.points_summary(db.connect(), 9)["active"]
    assert admin.post("/api/admin/customers/9/bonus", json={"points": 50, "reason": "Service recovery"}).status_code == 200
    assert loyalty.points_summary(db.connect(), 9)["active"] == before + 50


def test_campaign_multiplies_points(client, admin, conn):
    admin.post("/api/admin/campaigns", json={"name": "Books 4x", "category": "books", "multiplier": 4, "days": 3})
    login(client, "user3")
    p = find_product(conn, "books", min_price=300, max_price=900, min_stock=10)
    q = client.post("/api/cart/quote", json={"items": [{"product_id": p["id"], "qty": 4}]}).get_json()
    assert q["points_breakdown"]["campaign_bonus"] > 0
    for c in admin.get("/api/admin/campaigns").get_json():
        if c["name"] == "Books 4x":
            admin.put("/api/admin/campaigns/%d" % c["id"], json={"active": False})


# ---------- the AI ----------
def test_recommendations_reflect_each_persona(client):
    # The seed data shifts a little with the calendar (festive seasons), so compare against the categories each persona
    # was built to shop in (anything with at least 5% of their basket) instead of a hand-picked list.
    from app.seed.personas import PERSONAS
    by_user = {p["showcase_user"]: p for p in PERSONAS.values() if p.get("showcase_user")}
    expect = {uid: {c for c, w in by_user[uid]["cats"].items() if w >= 0.05} for uid in (3, 4, 5, 8)}
    for uid, cats in expect.items():
        login(client, "user%d" % uid)
        recs = client.get("/api/customer/recommendations?k=12").get_json()
        share = sum(1 for r in recs if r["category"] in cats) / len(recs)
        assert share >= 0.5, (uid, share)
        assert all(r["reason"] and r["stock"] > 0 for r in recs)


def test_recommendations_skip_owned_durables_and_out_of_stock(client, conn):
    login(client, "user3")
    owned = {r["product_id"] for r in rows(conn, "SELECT oi.product_id FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id "
                                                 "WHERE o.customer_id=3 AND o.status IN ('placed','delivered') AND p.consumable=0")}
    recs = client.get("/api/customer/recommendations?k=30").get_json()
    assert not owned & {r["id"] for r in recs}


def test_new_customer_gets_cold_start_recs(client):
    login(client, "user10")
    recs = client.get("/api/customer/recommendations").get_json()
    assert len(recs) == 12 and all(r["reason"] for r in recs)


def test_purchase_changes_recommendations(client, conn):
    login(client, "user3")
    recs = client.get("/api/customer/recommendations?k=12").get_json()
    p = next(r for r in recs if r["stock"] > 2 and r["price"] < 20000 and not conn.execute(
        "SELECT consumable FROM products WHERE id=?", (r["id"],)).fetchone()[0])      # a durable product
    assert client.post("/api/checkout", json={"items": [{"product_id": p["id"], "qty": 1}]}).status_code == 200
    ids = {r["id"] for r in client.get("/api/customer/recommendations?k=40").get_json()}
    assert p["id"] not in ids                                        # bought just now, so never recommended again


def test_agent_win_back_and_offer_guardrails(client, admin):
    login(client, "user9")                                          # Lakshmi: lapsed regular
    ov = client.get("/api/customer/overview").get_json()
    nba = ov["next_best_action"]
    assert nba["code"] == "WIN_BACK" and nba["offer"]["allowed"] and ov["behaviour"]["recency_days"] > 100
    r = client.post("/api/customer/offers/activate", json={"code": "WIN_BACK"})
    assert r.status_code == 200 and r.get_json()["multiplier"] >= 2
    assert client.post("/api/customer/offers/activate", json={"code": "WIN_BACK"}).status_code == 400    # only one active offer
    assert client.get("/api/customer/overview").get_json()["active_offer"]["multiplier"] >= 2
    assert admin.get("/api/admin/offers").get_json()["budget"]["offers_issued"] >= 1


def test_offer_budget_blocks_activation(client, admin):
    admin.put("/api/admin/settings", json={"offers": {"per_customer_cap": 0}})
    try:
        login(client, "user6")
        a = client.get("/api/customer/overview").get_json()["actions"]
        offered = [x for x in a if x.get("offer")]
        for x in offered:
            assert x["offer"]["allowed"] is False and x["offer"]["blocked_reason"]
    finally:
        admin.put("/api/admin/settings", json={"offers": {"per_customer_cap": 500}})


def test_chat_assistant(client):
    login(client, "user2")
    assert "points" in client.post("/api/customer/chat", json={"message": "how many points do I have?"}).get_json()["reply"].lower()
    r = client.post("/api/customer/chat", json={"message": "recommend some headphones"}).get_json()
    assert r["products"] and r["source"] == "rules"
    assert "Platinum" in client.post("/api/customer/chat", json={"message": "what is my tier"}).get_json()["reply"]


# ---------- personas are distinct and recoverable ----------
def test_personas_have_distinct_inferred_behaviour(admin):
    P = {p["key"]: p for p in admin.get("/api/admin/personas").get_json()}
    assert len(P) == 10
    assert P["deal_hunter"]["discount_share"] > 2 * P["premium"]["discount_share"]
    assert P["premium"]["avg_order_value"] > 3 * P["deal_hunter"]["avg_order_value"]
    assert P["festive"]["festival_share"] > 0.35 > P["parent"]["festival_share"]
    assert P["parent"]["avg_orders_12m"] > 2 * P["fitness"]["avg_orders_12m"]
    assert P["lapsed"]["churn_risk"] > 5 * P["parent"]["churn_risk"]
    assert P["trendy"]["return_rate"] > 2 * P["parent"]["return_rate"]
    assert P["student"]["avg_spend_12m"] < P["premium"]["avg_spend_12m"] / 4


def test_recommender_beats_popularity_baseline(admin):
    mq = admin.get("/api/admin/model-quality?refresh=1").get_json()
    rec = mq["recommender"]
    assert rec["customers"] > 40 and rec["hit_rate"] > 1.3 * rec["baseline_hit_rate"] and rec["category_hit_rate"] > 0.8
    assert mq["churn"]["auc"] is None or mq["churn"]["auc"] > 0.7


def test_admin_overview_and_customer_360(admin):
    ov = admin.get("/api/admin/overview").get_json()
    assert ov["customers"] >= 160 and len(ov["tier_distribution"]) == 4 and ov["points"]["liability_rs"] > 0
    assert sum(t["count"] for t in ov["tier_distribution"]) == ov["customers"]
    d = admin.get("/api/admin/customers/9").get_json()
    assert d["customer"]["persona"] == "lapsed" and d["analysis"]["next_best_action"]["code"] == "WIN_BACK"
    lst = admin.get("/api/admin/customers?segment=Hibernating&sort=churn").get_json()
    assert lst["total"] > 0 and all(i["segment"] == "Hibernating" for i in lst["items"])
    assert admin.get("/api/admin/audit").status_code == 200
