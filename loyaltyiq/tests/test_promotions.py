"""Segmentation and product awareness campaigns."""
from app.db import one
from tests.conftest import login


def _product(admin, category=None):
    items = admin.get("/api/admin/products?stock=&category=%s" % (category or "")).get_json()["items"]
    return [p for p in items if p["stock"] > 5][0]


def test_segments_summary(admin):
    s = admin.get("/api/admin/segments").get_json()
    assert s["total"] >= 160 and [t for t in s["tiers"]] == ["Bronze", "Silver", "Gold", "Platinum"]
    assert sum(x["count"] for x in s["segments"]) == s["total"]
    assert abs(sum(x["share"] for x in s["segments"]) - 1) < 0.01
    champ = [x for x in s["segments"] if x["segment"] == "Champion"][0]
    assert champ["count"] > 0 and champ["spend_12m_avg"] > 0 and sum(champ["tiers"].values()) == champ["count"]


def test_preview_and_validation(admin):
    p = _product(admin)
    r = admin.post("/api/admin/promotions/preview", json={"product_id": p["id"], "segments": ["Champion", "Loyal"]}).get_json()
    assert r["audience"] > 0 and {x["segment"] for x in r["by_segment"]} <= {"Champion", "Loyal"}
    assert admin.post("/api/admin/promotions/preview", json={"product_id": p["id"], "segments": ["Nope"]}).status_code == 400
    assert admin.post("/api/admin/promotions/preview", json={"segments": ["Loyal"]}).status_code == 400
    assert admin.post("/api/admin/promotions/preview", json={"product_id": p["id"], "days": 500}).status_code == 400
    assert admin.post("/api/admin/promotions/preview", json={"product_id": p["id"], "tiers": ["Diamond"]}).status_code == 400


def test_campaign_lifecycle_and_tracking(admin, app):
    p = _product(admin)
    r = admin.post("/api/admin/promotions", json={"product_id": p["id"], "segments": ["Champion", "Loyal", "Promising"], "headline": "Try this", "days": 10, "exclude_buyers": False})
    assert r.status_code == 201, r.get_json()
    camp = r.get_json()
    assert camp["status"] == "active" and camp["audience"] > 0
    # pick a customer inside the audience
    aud = [c for c in admin.get("/api/admin/customers?segment=Champion").get_json()["items"]][0]
    cu = app.test_client()
    login(cu, aud["username"])
    promos = cu.get("/api/customer/promotions").get_json()
    assert any(x["campaign_id"] == camp["id"] for x in promos)
    assert cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "impression"}).get_json()["recorded"] is True
    assert cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "impression"}).get_json()["recorded"] is False  # de-duplicated
    assert cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "click"}).get_json()["recorded"] is True
    assert cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "bogus"}).status_code == 400
    live = admin.get("/api/admin/promotions/%d" % camp["id"]).get_json()["live"]
    assert live["reached"] == 1 and live["clickers"] == 1 and live["impressions"] == 1 and live["ctr"] == 1.0
    # a customer outside the audience sees nothing and cannot log events
    out = [c for c in admin.get("/api/admin/customers?segment=Hibernating").get_json()["items"]][0]
    ou = app.test_client()
    login(ou, out["username"])
    assert not any(x["campaign_id"] == camp["id"] for x in ou.get("/api/customer/promotions").get_json())
    assert ou.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "click"}).get_json()["recorded"] is False
    # pause hides it
    assert admin.post("/api/admin/promotions/%d/status" % camp["id"], json={"status": "paused"}).get_json()["status"] == "paused"
    assert not any(x["campaign_id"] == camp["id"] for x in cu.get("/api/customer/promotions").get_json())
    assert admin.post("/api/admin/promotions/%d/status" % camp["id"], json={"status": "active"}).get_json()["status"] == "active"
    assert admin.post("/api/admin/promotions/%d/status" % camp["id"], json={"status": "ended"}).get_json()["status"] == "ended"
    assert admin.post("/api/admin/promotions/%d/status" % camp["id"], json={"status": "active"}).status_code == 400


def test_exclude_buyers_and_attribution(admin, app, conn):
    # a Loyal customer who has bought a product; advertising that product with exclude_buyers hides it from them
    row = one(conn, "SELECT o.customer_id cid, i.product_id pid FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.status='delivered' LIMIT 1")
    r = admin.post("/api/admin/promotions/preview", json={"product_id": row["pid"]}).get_json()
    assert r["already_bought"] > 0 and r["audience"] == r["matching"] - r["already_bought"]


def test_simulation_is_separate_from_live(admin):
    p = _product(admin)
    camp = admin.post("/api/admin/promotions", json={"product_id": p["id"], "segments": ["Champion", "Loyal", "At risk"], "days": 14}).get_json()
    r = admin.post("/api/admin/promotions/%d/simulate" % camp["id"])
    assert r.status_code == 200
    d = r.get_json()
    assert d["simulated"]["reached"] > 0 and d["simulated"]["clickers"] >= d["simulated"]["buyers"] >= 0
    assert d["live"]["reached"] == 0 and d["live"]["buyers"] == 0
    again = admin.post("/api/admin/promotions/%d/simulate" % camp["id"]).get_json()
    assert again["simulated"] == d["simulated"]  # deterministic and replaced, not stacked
    assert admin.delete("/api/admin/promotions/%d/simulated" % camp["id"]).get_json()["simulated"]["reached"] == 0
    assert admin.delete("/api/admin/promotions/%d" % camp["id"]).status_code == 200
    assert admin.get("/api/admin/promotions/%d" % camp["id"]).status_code == 404


def test_real_purchase_is_attributed(admin, app):
    from tests.conftest import find_product
    prod = _product(admin)
    camp = admin.post("/api/admin/promotions", json={"product_id": prod["id"], "segments": ["Champion"], "days": 10, "exclude_buyers": False}).get_json()
    c = admin.get("/api/admin/customers?segment=Champion").get_json()["items"][0]
    cu = app.test_client()
    login(cu, c["username"])
    cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "impression"})
    cu.post("/api/customer/events", json={"campaign_id": camp["id"], "kind": "click"})
    r = cu.post("/api/checkout", json={"items": [{"product_id": prod["id"], "qty": 1}]})
    assert r.status_code in (200, 201), r.get_json()
    live = admin.get("/api/admin/promotions/%d" % camp["id"]).get_json()["live"]
    assert live["buyers"] == 1 and live["units"] == 1 and live["revenue"] >= round(prod["price"]) - 1 and live["conversion"] == 1.0
