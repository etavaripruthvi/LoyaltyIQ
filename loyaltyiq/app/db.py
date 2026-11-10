"""SQLite helpers and schema. One database file is the single source of truth
for both the admin console and the customer portal."""
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','customer')), display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE REFERENCES users(id),
  name TEXT NOT NULL, city TEXT, email TEXT, joined_at TEXT NOT NULL,
  persona TEXT,              -- hidden ground-truth label used only to verify the AI
  is_showcase INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY, sku TEXT UNIQUE, name TEXT NOT NULL, emoji TEXT NOT NULL,
  category TEXT NOT NULL, family TEXT, brand TEXT, brand_tier TEXT, unit TEXT,
  price REAL NOT NULL, mrp REAL NOT NULL, cost REAL NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0, reorder_level INTEGER NOT NULL DEFAULT 10,
  consumable INTEGER NOT NULL DEFAULT 0, rating REAL DEFAULT 4.0,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_products_cat ON products(category, active);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'placed',        -- placed, delivered, cancelled, returned
  subtotal REAL NOT NULL, product_savings REAL NOT NULL DEFAULT 0,
  points_redeemed INTEGER NOT NULL DEFAULT 0, redeem_value REAL NOT NULL DEFAULT 0,
  total_paid REAL NOT NULL,
  points_earned INTEGER NOT NULL DEFAULT 0,
  points_status TEXT NOT NULL DEFAULT 'approved',  -- pending, approved, rejected
  risk_score INTEGER NOT NULL DEFAULT 0, risk_flags TEXT DEFAULT '[]',
  reviewed_by TEXT, reviewed_at TEXT, review_note TEXT, offer_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_orders_cust ON orders(customer_id, created_at);
CREATE INDEX IF NOT EXISTS ix_orders_pending ON orders(points_status, created_at);

CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL,
  unit_price REAL NOT NULL, mrp REAL NOT NULL, category TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS ix_items_prod ON order_items(product_id);

-- Append-only points ledger. 'remaining' tracks unspent points on earn-type rows (FIFO burn).
CREATE TABLE IF NOT EXISTS points_ledger (
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
  order_id INTEGER, kind TEXT NOT NULL,   -- earn, bonus, redeem, expire, reverse, refund
  points INTEGER NOT NULL, remaining INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',  -- pending, active, rejected
  created_at TEXT NOT NULL, expires_at TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS ix_ledger_cust ON points_ledger(customer_id, status);

CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, multiplier REAL NOT NULL,
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
  kind TEXT NOT NULL, multiplier REAL NOT NULL, reason TEXT, cost_est REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT
);

-- Live category list: starts as the built-in 16, the admin can add more.
CREATE TABLE IF NOT EXISTS categories (
  key TEXT PRIMARY KEY, name TEXT NOT NULL, emoji TEXT NOT NULL, color TEXT NOT NULL,
  cycle INTEGER,              -- usual days between purchases for consumables, NULL for durable goods
  position INTEGER NOT NULL DEFAULT 0, builtin INTEGER NOT NULL DEFAULT 0
);

-- Product awareness (advertising) campaigns aimed at behaviour segments and tiers.
CREATE TABLE IF NOT EXISTS ad_campaigns (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
  segments TEXT NOT NULL DEFAULT '[]', tiers TEXT NOT NULL DEFAULT '[]',   -- JSON lists, empty = everyone
  exclude_buyers INTEGER NOT NULL DEFAULT 1,
  headline TEXT NOT NULL, message TEXT DEFAULT '',
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',        -- active, paused
  created_by TEXT, created_at TEXT NOT NULL
);

-- Exposure and response tracking for awareness campaigns. simulated=1 marks demo traffic made by the admin's Simulate button.
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, customer_id INTEGER NOT NULL REFERENCES customers(id),
  kind TEXT NOT NULL,                           -- impression, click, add_to_cart, purchase (purchase only when simulated)
  campaign_id INTEGER, product_id INTEGER, surface TEXT, simulated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_events_camp ON events(campaign_id, kind);
CREATE INDEX IF NOT EXISTS ix_events_cust ON events(customer_id, campaign_id);
"""


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")


def connect(path=None):
    path = path or config.DB_PATH
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# Columns added after the first release. Added in place so existing database files keep working.
NEW_COLUMNS = [
    ("customers", "new_account_offer", "INTEGER NOT NULL DEFAULT 0"),    # 1 = still has the new-account offer
    ("orders", "new_account_discount", "REAL NOT NULL DEFAULT 0"),       # rupees taken off by the offer
    ("orders", "new_account_points", "INTEGER NOT NULL DEFAULT 0"),      # extra points from the offer (already inside points_earned)
]


def ensure_columns(conn):
    for table, col, ddl in NEW_COLUMNS:
        if col not in {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, ddl))


def init_schema(conn):
    conn.executescript(SCHEMA)
    ensure_columns(conn)
    ensure_base_categories(conn)
    conn.commit()


def ensure_base_categories(conn):
    """Insert the built-in categories on a fresh or older database; custom ones are never touched."""
    from .seed.catalog import CATEGORIES
    for i, (key, name, emoji, color, cycle) in enumerate(CATEGORIES):
        conn.execute("INSERT OR IGNORE INTO categories(key, name, emoji, color, cycle, position, builtin) VALUES(?,?,?,?,?,?,1)",
                     (key, name, emoji, color, cycle, i))


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def audit(conn, actor, action, detail=""):
    conn.execute("INSERT INTO audit_log(ts, actor, action, detail) VALUES(?,?,?,?)",
                 (iso(utcnow()), actor, action, detail))


__all__ = ["connect", "init_schema", "rows", "one", "audit", "utcnow", "iso", "parse", "timedelta"]
