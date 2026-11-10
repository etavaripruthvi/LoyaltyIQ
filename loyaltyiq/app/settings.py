"""Admin-editable business rules. Stored as one JSON row in the database and
deep-merged over these defaults, so new settings never break an old database."""
import copy
import json

DEFAULT_SETTINGS = {
    "loyalty": {
        "points_per_100": 1.0,       # base points earned per Rs 100 of net spend
        "point_value": 1.0,          # Rs value of one point when redeemed
        "min_redeem": 100,           # smallest redemption allowed
        "max_redeem_pct": 20,        # max share of an order that points can pay for
        "expiry_days": 365,          # points expire this long after being earned
        "welcome_bonus": 100,        # bonus on a customer's first order
        "tiers": [
            {"name": "Bronze", "min_spend": 0, "multiplier": 1.0,
             "perks": ["1x points on every order", "Member-only offers"]},
            {"name": "Silver", "min_spend": 25000, "multiplier": 1.25,
             "perks": ["1.25x points", "Early access to sales"]},
            {"name": "Gold", "min_spend": 70000, "multiplier": 1.5,
             "perks": ["1.5x points", "Priority support", "Free delivery"]},
            {"name": "Platinum", "min_spend": 180000, "multiplier": 2.0,
             "perks": ["2x points", "Dedicated support", "Free express delivery", "Launch previews"]},
        ],
    },
    "approval": {
        "mode": "flagged_only",          # "flagged_only" or "all"
        "large_order_threshold": 20000,  # orders at or above this need approval
        "risk_threshold": 40,            # risk score at or above this needs approval
    },
    "offers": {
        "monthly_budget": 25000,         # Rs the agent may spend on personal offers per month
        "per_customer_cap": 500,         # Rs cap on one offer's estimated cost
    },
    "new_account_offer": {
        "enabled": True,              # offer new accounts a discount and extra points on their first order
        "discount_pct": 10,           # % off the first order
        "bonus_points_pct": 5,        # % more points on the first order
        "max_discount": 0,            # Rs cap on the discount, 0 = no cap
    },
    "recommender": {
        "w_cf_item": 0.26, "w_cf_user": 0.10, "w_content": 0.24, "w_popularity": 0.06,
        "w_replenish": 0.22, "w_promo": 0.06, "w_campaign": 0.04, "w_margin": 0.02,
    },
}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_settings(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='settings'").fetchone()
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    if row:
        _merge(merged, json.loads(row[0]))
    return merged


def save_settings(conn, settings):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES('settings', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (json.dumps(settings),),
    )
