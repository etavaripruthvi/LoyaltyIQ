"""Admin can add customers, admins and categories without touching code."""
from tests.conftest import login


def test_add_customer_logs_in_and_gets_cold_start(admin, app):
    r = admin.post("/api/admin/customers", json={"name": "Test Newcomer", "city": "Pune", "welcome_points": 100})
    assert r.status_code == 201, r.get_json()
    username = r.get_json()["username"]
    c = app.test_client()
    login(c, username)
    ov = c.get("/api/customer/overview").get_json()
    assert ov["points"]["active"] == 100
    recs = c.get("/api/customer/recommendations").get_json()
    assert len(recs) > 0
    row = [x for x in admin.get("/api/admin/customers?q=%s" % username).get_json()["items"] if x["username"] == username][0]
    assert row["segment"] == "Prospect" and row["persona"] == "Added by admin"
    assert admin.get("/api/admin/customers/%d" % row["id"]).status_code == 200


def test_add_customer_validation(admin):
    assert admin.post("/api/admin/customers", json={"name": "A"}).status_code == 400
    assert admin.post("/api/admin/customers", json={"name": "Valid Name", "username": "admin"}).status_code == 400
    assert admin.post("/api/admin/customers", json={"name": "Valid Name", "email": "nope"}).status_code == 400


def test_add_admin_and_login(admin, app):
    r = admin.post("/api/admin/admins", json={"name": "Second Admin", "username": "ops2", "password": "pass1234"})
    assert r.status_code == 201
    c = app.test_client()
    assert c.post("/api/login", json={"username": "ops2", "password": "pass1234"}).status_code == 200
    assert c.get("/api/admin/overview").status_code == 200
    assert admin.post("/api/admin/admins", json={"name": "Dup", "username": "ops2", "password": "xxxx"}).status_code == 400


def test_customers_cannot_use_admin_endpoints(app):
    c = app.test_client()
    login(c, "user1")
    assert c.post("/api/admin/customers", json={"name": "Nope Nope"}).status_code == 403
    assert c.post("/api/admin/categories", json={"name": "Nope", "emoji": "x"}).status_code == 403


def test_add_category_and_product_in_it(admin, app):
    r = admin.post("/api/admin/categories", json={"name": "Garden Supplies", "emoji": "🌱", "cycle": 60})
    assert r.status_code == 201, r.get_json()
    key = r.get_json()["key"]
    assert admin.post("/api/admin/categories", json={"name": "garden supplies", "emoji": "🌱"}).status_code == 400
    p = admin.post("/api/admin/products", json={"name": "Potting Mix 5kg", "category": key, "price": 349, "stock": 40})
    assert p.status_code == 201, p.get_json()
    cats = admin.get("/api/categories").get_json()
    assert any(c["key"] == key and c["count"] == 1 for c in cats)
    # the recommender and analytics must keep working with the new category in the model
    c = app.test_client()
    login(c, "user2")
    assert c.get("/api/customer/recommendations").status_code == 200
    assert admin.get("/api/admin/overview").status_code == 200
