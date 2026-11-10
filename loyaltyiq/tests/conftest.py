import os
import tempfile

# Must be set before the app package is imported: smaller, isolated database for tests.
_tmp = tempfile.mkdtemp(prefix="loyaltyiq_test_")
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "test.db")
os.environ["N_CUSTOMERS"] = "150"

import pytest  # noqa: E402

from app import create_app, db  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return create_app({"TESTING": True})


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username, password="1234"):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.get_json()
    return r.get_json()


@pytest.fixture()
def admin(app):
    c = app.test_client()
    login(c, "admin")
    return c


@pytest.fixture()
def conn(app):
    c = db.connect()
    yield c
    c.close()


def find_product(conn, category=None, min_price=0, max_price=1e9, min_stock=20, consumable=None):
    sql = "SELECT * FROM products WHERE active=1 AND stock>=? AND price>=? AND price<=?"
    args = [min_stock, min_price, max_price]
    if category:
        sql += " AND category=?"
        args.append(category)
    if consumable is not None:
        sql += " AND consumable=?"
        args.append(consumable)
    r = conn.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
    assert r, "no product found"
    return dict(r)
