"""New-account offer: a customer who signs up gets a discount and extra points on their first order, once."""
import sqlite3

import pytest

from app import api, config, db
from tests.conftest import find_product, login


@pytest.fixture(autouse=True)
def _fresh_signup_counter():
    api._REG_HITS.clear()
    yield
    api._REG_HITS.clear()


def signup(app, username, name="Test Newcomer"):
    c = app.test_client()
    r = c.post("/api/register", json={"name": name, "username": username, "password": "pass1", "city": "Pune"})
    assert r.status_code == 201, r.get_json()
    return c


def cart(conn, qty=2, **kw):
    p = find_product(conn, min_price=300, max_price=1400, min_stock=20, **kw)
    return p, [{"product_id": p["id"], "qty": qty}]


def set_offer(admin, **vals):
    r = admin.put("/api/admin/settings", json={"new_account_offer": vals})
    assert r.status_code == 200, r.get_json()


def test_signup_signs_in_and_announces_the_offer(app):
    pub = app.test_client().get("/api/welcome-offer").get_json()
    assert pub == {"enabled": True, "discount_pct": 10, "bonus_points_pct": 5, "max_discount": 0}
    c = signup(app, "naoffer1")
    ov = c.get("/api/customer/overview").get_json()
    assert ov["new_account_offer"]["discount_pct"] == 10 and ov["new_account_offer"]["bonus_points_pct"] == 5
    assert ov["tier"]["tier"] == "Bronze"
    nba = ov["next_best_action"]
    assert nba["code"] == "WELCOME" and "10% off" in nba["message"] and "5% extra points" in nba["message"]


def test_signup_validation(app):
    c = app.test_client()
    assert c.post("/api/register", json={"name": "A", "username": "okname", "password": "pass1"}).status_code == 400
    assert c.post("/api/register", json={"name": "Valid Name", "username": "x!", "password": "pass1"}).status_code == 400
    assert c.post("/api/register", json={"name": "Valid Name", "username": "okname", "password": "123"}).status_code == 400
    assert c.post("/api/register", json={"name": "Valid Name", "username": "admin", "password": "pass1"}).status_code == 400
    signup(app, "dupcheck")
    assert c.post("/api/register", json={"name": "Valid Name", "username": "DupCheck", "password": "pass1"}).status_code == 400
    # the new account signs in again later with the password they chose
    assert app.test_client().post("/api/login", json={"username": "dupcheck", "password": "pass1"}).status_code == 200


def test_first_order_gets_discount_and_extra_points_once(app, conn):
    c = signup(app, "naoffer2")
    p, items = cart(conn)
    q = c.post("/api/cart/quote", json={"items": items}).get_json()
    assert q["new_account_discount"] == round(q["subtotal"] * 0.10, 2) > 0
    assert q["total"] == round(q["subtotal"] - q["new_account_discount"], 2)
    pre = q["points_estimate"] - q["new_account_points"]
    assert q["new_account_points"] == int(pre * 0.05 + 0.5) and q["points_breakdown"]["new_account"] == q["new_account_points"]

    o = c.post("/api/checkout", json={"items": items}).get_json()["order"]
    assert o["total_paid"] == q["total"] and o["new_account_discount"] == q["new_account_discount"]
    assert o["points_earned"] == q["points_estimate"] and o["new_account_points"] == q["new_account_points"]
    assert o["points_status"] == "approved"
    summary = c.get("/api/customer/points").get_json()["summary"]
    assert summary["active"] == o["points_earned"] + q["welcome_bonus"]       # earned points include the 5%; the flat welcome bonus is separate

    q2 = c.post("/api/cart/quote", json={"items": items}).get_json()           # used up: the second order is full price
    assert q2["new_account_offer"] is None and q2["new_account_discount"] == 0 and q2["new_account_points"] == 0 and q2["total"] == q2["subtotal"]
    assert c.get("/api/customer/overview").get_json()["new_account_offer"] is None
    o2 = c.post("/api/checkout", json={"items": items}).get_json()["order"]
    assert o2["new_account_discount"] == 0 and o2["total_paid"] == o2["subtotal"]


def test_existing_customers_do_not_get_it(app, conn):
    c = app.test_client()
    login(c, "user1")
    _, items = cart(conn)
    q = c.post("/api/cart/quote", json={"items": items}).get_json()
    assert q["new_account_offer"] is None and q["new_account_discount"] == 0 and q["total"] == q["subtotal"]
    login(c, "user10")                      # seeded "new customer" persona was not created through sign-up either
    assert c.post("/api/cart/quote", json={"items": items}).get_json()["new_account_discount"] == 0


def test_points_redemption_is_limited_by_the_discounted_total(app, admin, conn):
    c = signup(app, "naoffer3")
    cid = c.get("/api/customer/overview").get_json()["profile"]["id"]
    assert admin.post("/api/admin/customers/%d/bonus" % cid, json={"points": 5000, "reason": "test"}).status_code == 200
    _, items = cart(conn, qty=3)
    q = c.post("/api/cart/quote", json={"items": items}).get_json()
    discounted = round(q["subtotal"] - q["new_account_discount"], 2)
    assert q["max_redeem"] == int(discounted * 20 / 100)                       # 20% of what is actually payable
    q = c.post("/api/cart/quote", json={"items": items, "redeem_points": q["max_redeem"]}).get_json()
    assert q["total"] == round(discounted - q["redeem_value"], 2) > 0


def test_cap_and_switch_in_rules(app, admin, conn):
    try:
        set_offer(admin, max_discount=50)
        c = signup(app, "naoffer4")
        _, items = cart(conn, qty=3)
        q = c.post("/api/cart/quote", json={"items": items}).get_json()
        assert q["subtotal"] > 500 and q["new_account_discount"] == 50 and q["total"] == round(q["subtotal"] - 50, 2)

        set_offer(admin, max_discount=0, discount_pct=7.5, bonus_points_pct=0)
        q = c.post("/api/cart/quote", json={"items": items}).get_json()
        assert q["new_account_discount"] == round(q["subtotal"] * 7.5 / 100.0, 2) and q["new_account_points"] == 0

        set_offer(admin, enabled=False)                                         # switched off: nobody gets it, not even earlier sign-ups
        assert c.post("/api/cart/quote", json={"items": items}).get_json()["new_account_discount"] == 0
        assert app.test_client().get("/api/welcome-offer").get_json()["enabled"] is False
        late = signup(app, "naoffer5")
        set_offer(admin, enabled=True, discount_pct=10, bonus_points_pct=5)
        assert late.post("/api/cart/quote", json={"items": items}).get_json()["new_account_discount"] == 0   # signed up while it was off
    finally:
        set_offer(admin, enabled=True, discount_pct=10, bonus_points_pct=5, max_discount=0)


def test_rules_validation(admin):
    assert admin.put("/api/admin/settings", json={"new_account_offer": {"discount_pct": 80}}).status_code == 400
    assert admin.put("/api/admin/settings", json={"new_account_offer": {"bonus_points_pct": 150}}).status_code == 400
    assert admin.put("/api/admin/settings", json={"new_account_offer": {"discount_pct": -1}}).status_code == 400
    assert admin.get("/api/admin/settings").get_json()["settings"]["new_account_offer"]["discount_pct"] == 10


def test_admin_added_customer_gets_it_too(app, admin, conn):
    r = admin.post("/api/admin/customers", json={"name": "Added By Admin"})
    c = app.test_client()
    login(c, r.get_json()["username"])
    _, items = cart(conn)
    assert c.post("/api/cart/quote", json={"items": items}).get_json()["new_account_discount"] > 0


def test_cancelling_reverses_points_but_does_not_give_the_offer_back(app, conn):
    c = signup(app, "naoffer6")
    _, items = cart(conn)
    welcome = c.post("/api/cart/quote", json={"items": items}).get_json()["welcome_bonus"]
    o = c.post("/api/checkout", json={"items": items}).get_json()["order"]
    assert c.post("/api/customer/orders/%d/cancel" % o["id"]).status_code == 200
    assert c.get("/api/customer/points").get_json()["summary"]["active"] == welcome      # order points (with the 5%) are reversed
    q = c.post("/api/cart/quote", json={"items": items}).get_json()
    assert q["new_account_discount"] == 0 and q["welcome_bonus"] == 0                    # neither the offer nor the welcome bonus can be earned twice


def test_large_first_order_still_goes_to_review_and_extra_points_wait_with_it(app, admin, conn):
    c = signup(app, "naoffer7")
    p = find_product(conn, min_price=2500, max_price=9000, min_stock=40)
    items = [{"product_id": p["id"], "qty": -(-9500 // int(p["price"]))}]         # about Rs 9,500, still Rs 8,500+ after the 10% discount
    q = c.post("/api/cart/quote", json={"items": items}).get_json()
    o = c.post("/api/checkout", json={"items": items}).get_json()["order"]
    assert o["points_status"] == "pending" and o["points_earned"] == q["points_estimate"]      # new-account points are inside the pending credit
    assert c.get("/api/customer/points").get_json()["summary"]["active"] == q["welcome_bonus"]
    admin.post("/api/admin/approvals/%d" % o["id"], json={"action": "approve"})


def test_signup_is_rate_limited(app, monkeypatch):
    monkeypatch.setattr(config, "REGISTER_LIMIT_PER_HOUR", 2)
    signup(app, "ratelimit1")
    signup(app, "ratelimit2")
    r = app.test_client().post("/api/register", json={"name": "Third Try", "username": "ratelimit3", "password": "pass1"})
    assert r.status_code == 429


def test_old_database_files_gain_the_new_columns(tmp_path):
    f = sqlite3.connect(tmp_path / "old.db")
    f.executescript("CREATE TABLE customers(id INTEGER PRIMARY KEY); CREATE TABLE orders(id INTEGER PRIMARY KEY);")
    db.ensure_columns(f)
    db.ensure_columns(f)                                                         # safe to run again
    assert "new_account_offer" in {r[1] for r in f.execute("PRAGMA table_info(customers)")}
    assert {"new_account_discount", "new_account_points"} <= {r[1] for r in f.execute("PRAGMA table_info(orders)")}
