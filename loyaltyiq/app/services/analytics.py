"""Behaviour analytics. Everything is learned from raw orders; the hidden persona label is never used.

build_model() turns the order history into:
  - per-customer features (frequency, basket, discount affinity, seasonality, category mix ...)
  - RFM segments, a churn-risk classifier (gradient boosting, checked on a later time slice) and a 12-month value estimate
  - the matrices the recommender needs (user-item weights, item-item similarity, replenishment cycles)
"""
import threading
import time
from collections import defaultdict
from datetime import timedelta

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from ..db import iso, one, rows, utcnow
from . import categories

TIER_IDX = {"value": 0, "standard": 1, "premium": 2}
CHURN_CUTOFFS = (90, 120, 150, 180, 210)     # days ago; label = no order in the 90 days after the cutoff
VALID = "('placed','delivered')"


class Model:
    pass


def _q(x, reverse=False):
    """1-5 quintile score by rank."""
    if len(x) == 0:
        return np.array([])
    pct = (rankdata(-x if reverse else x, method="average") - 1) / max(len(x) - 1, 1)
    return 1 + np.minimum(4, np.floor(pct * 5)).astype(int)


def _segment(f, mon, n, first_age, recency, overdue):
    """Cadence-aware RFM: 'overdue' = days since last order / the customer's own usual gap."""
    if n == 0:
        return "Prospect"
    if first_age <= 30 and n <= 2:
        return "New"
    if recency > 120:
        return "Hibernating"
    if overdue >= 2 and recency > 30 and n >= 4:
        return "At risk"
    if f >= 4 and mon >= 4 and overdue < 1.5:
        return "Champion"
    if n >= 6 and overdue < 2:
        return "Loyal"
    return "Promising"


def _churn_feats(ages, amts, months, tenure, c):
    mask = ages >= c
    if not mask.any():
        return None
    a, am, mo = ages[mask] - c, amts[mask], months[mask]
    rec = a.min()
    w1, w2 = a <= 90, (a > 90) & (a <= 180)
    gaps = np.diff(np.sort(a))
    mean_gap = float(gaps.mean()) if len(gaps) else 90.0
    s1, s2 = am[w1].sum(), am[w2].sum()
    return [rec, int(w1.sum()), int(w2.sum()), np.log1p(s1), np.log1p(s1) - np.log1p(s2), min(mean_gap, 200.0),
            min(rec / max(mean_gap, 7.0), 10.0), float(np.isin(mo, (10, 11)).mean()), np.log1p(len(a)), tenure - c]


def _train_churn(ages_by_c, amts_by_c, months_by_c, tenure):
    X, y, grp = [], [], []
    for c in CHURN_CUTOFFS:
        for ci in ages_by_c:
            f = _churn_feats(ages_by_c[ci], amts_by_c[ci], months_by_c[ci], tenure[ci], c)
            if f is None or f[0] > 200:
                continue
            ages = ages_by_c[ci]
            active = bool(((ages < c) & (ages >= c - 90)).any())
            X.append(f)
            y.append(0 if active else 1)
            grp.append(c)
    X, y, grp = np.array(X), np.array(y), np.array(grp)
    metrics = {"auc": None, "n_samples": int(len(y)), "churn_rate": round(float(y.mean()), 3) if len(y) else None}
    if len(y) < 40 or y.min() == y.max():
        return None, metrics
    train, test = grp >= 150, grp <= 120
    if test.sum() > 20 and y[train].min() != y[train].max() and y[test].min() != y[test].max():
        clf = GradientBoostingClassifier(n_estimators=60, max_depth=2, random_state=0).fit(X[train], y[train])
        metrics["auc"] = round(float(roc_auc_score(y[test], clf.predict_proba(X[test])[:, 1])), 3)
    clf = GradientBoostingClassifier(n_estimators=60, max_depth=2, random_state=0).fit(X, y)
    return clf, metrics


def build_model(conn, as_of=None, churn=None):
    """Build the full analytical snapshot as of `as_of`. `churn` = (clf, metrics) to reuse a trained model."""
    as_of = as_of or utcnow()
    asof_s = iso(as_of)
    m = Model()
    m.as_of = as_of
    # ---- products ----
    prods = rows(conn, "SELECT id, name, emoji, category, brand_tier, unit, price, mrp, cost, stock, consumable, active, rating FROM products ORDER BY id")
    n_p = len(prods)
    m.products = prods
    m.prod_ids = np.array([p["id"] for p in prods])
    m.pidx = {int(p["id"]): i for i, p in enumerate(prods)}
    m.cat_keys, m.cat_meta = categories.load(conn)
    cmap = {c: i for i, c in enumerate(m.cat_keys)}
    m.cat_i = np.array([cmap.get(p["category"], 0) for p in prods])
    m.tier_i = np.array([TIER_IDX.get(p["brand_tier"], 1) for p in prods])
    m.price = np.array([p["price"] for p in prods], dtype=float)
    m.promo_pct = np.array([(p["mrp"] - p["price"]) / p["mrp"] if p["mrp"] > 0 else 0 for p in prods])
    m.margin = np.array([(p["price"] - p["cost"]) / p["price"] if p["price"] > 0 else 0 for p in prods])
    m.consumable = np.array([bool(p["consumable"]) for p in prods])
    m.in_stock = np.array([p["stock"] > 0 and p["active"] == 1 for p in prods])
    m.active = np.array([p["active"] == 1 for p in prods])
    # ---- customers ----
    custs = rows(conn, "SELECT id, joined_at FROM customers ORDER BY id")
    n_c = len(custs)
    m.cust_ids = [c["id"] for c in custs]
    m.cidx = {c["id"]: i for i, c in enumerate(custs)}
    asof64 = np.datetime64(asof_s.replace(" ", "T"))
    joined = np.array([c["joined_at"].replace(" ", "T") for c in custs], dtype="datetime64[s]")
    m.tenure = (asof64 - joined) / np.timedelta64(1, "D")
    # ---- orders and lines ----
    orders = conn.execute("SELECT id, customer_id, created_at, total_paid FROM orders WHERE status IN " + VALID +
                          " AND created_at<=? ORDER BY created_at", (asof_s,)).fetchall()
    o_id = np.array([r[0] for r in orders], dtype=int)
    o_c = np.array([m.cidx[r[1]] for r in orders], dtype=int)
    o_ts = np.array([r[2].replace(" ", "T") for r in orders], dtype="datetime64[s]")
    o_amt = np.array([r[3] for r in orders], dtype=float)
    o_age = (asof64 - o_ts) / np.timedelta64(1, "D")
    o_month = o_ts.astype("datetime64[M]").astype(int) % 12 + 1
    opos = {int(i): k for k, i in enumerate(o_id)}
    lines = conn.execute("SELECT oi.order_id, oi.product_id, oi.qty, oi.unit_price, oi.mrp FROM order_items oi JOIN orders o ON o.id=oi.order_id "
                         "WHERE o.status IN " + VALID + " AND o.created_at<=?", (asof_s,)).fetchall()
    l_o = np.array([opos[r[0]] for r in lines], dtype=int)
    l_p = np.array([m.pidx[r[1]] for r in lines], dtype=int)
    l_q = np.array([r[2] for r in lines], dtype=float)
    l_price = np.array([r[3] for r in lines], dtype=float)
    l_mrp = np.array([r[4] for r in lines], dtype=float)
    l_c, l_age = o_c[l_o], o_age[l_o]
    sp = l_price * l_q

    M = np.zeros((n_c, n_p))
    np.add.at(M, (l_c, l_p), np.log1p(l_q) * np.power(0.5, l_age / 180.0))
    owned = np.zeros((n_c, n_p), dtype=bool)
    owned[l_c, l_p] = True
    last_age = np.full((n_c, n_p), np.inf)
    np.minimum.at(last_age, (l_c, l_p), l_age)
    cat_spend = np.zeros((n_c, len(m.cat_keys)))
    np.add.at(cat_spend, (l_c, m.cat_i[l_p]), sp)
    tier_spend = np.zeros((n_c, 3))
    np.add.at(tier_spend, (l_c, m.tier_i[l_p]), sp)
    logp = np.zeros((n_c, len(m.cat_keys)))
    np.add.at(logp, (l_c, m.cat_i[l_p]), sp * np.log(np.maximum(l_price, 1)))
    with np.errstate(invalid="ignore", divide="ignore"):
        m.mu_logp = logp / cat_spend            # NaN where the customer never bought the category
    tot_spend = cat_spend.sum(axis=1)
    disc_spend = np.zeros(n_c)
    np.add.at(disc_spend, l_c, sp * (l_mrp > l_price))
    m.M, m.owned, m.last_age = M, owned, last_age
    m.cat_share = cat_spend / np.maximum(tot_spend[:, None], 1)
    m.tier_share = tier_spend / np.maximum(tot_spend[:, None], 1)
    m.disc_share = disc_spend / np.maximum(tot_spend, 1)
    m.pop_recent = np.bincount(l_p[l_age <= 30], minlength=n_p).astype(float)
    m.pop_all = np.bincount(l_p[l_age <= 180], minlength=n_p).astype(float)
    # item-item cosine similarity
    co = M.T @ M
    d = np.sqrt(np.diag(co)) + 1e-9
    sim = co / np.outer(d, d)
    np.fill_diagonal(sim, 0)
    m.item_sim = sim
    norms = np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    m.Mn = M / norms
    # ---- replenishment cycles: consumables bought 2+ times ----
    m.rep = defaultdict(list)
    idx = np.where(m.consumable[l_p])[0]
    if len(idx):
        idx = idx[np.lexsort((l_age[idx], l_p[idx], l_c[idx]))]
        cs, ps, as_ = l_c[idx], l_p[idx], l_age[idx]
        start = 0
        for i in range(1, len(idx) + 1):
            if i == len(idx) or cs[i] != cs[start] or ps[i] != ps[start]:
                if i - start >= 2:
                    ages = np.unique(as_[start:i])
                    if len(ages) >= 2:
                        interval = float(np.median(np.diff(ages)))
                        if interval >= 2:
                            m.rep[int(cs[start])].append((int(ps[start]), float(ages[0] / interval), interval, float(ages[0])))
                start = i
    # ---- per-customer features ----
    by_c = defaultdict(list)
    for k, c in enumerate(o_c):
        by_c[int(c)].append(k)
    lpo = np.bincount(l_o, minlength=len(o_id))
    ret = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT customer_id, SUM(status='returned'), COUNT(*) FROM orders WHERE created_at<=? GROUP BY customer_id", (asof_s,))}
    m.n_orders = np.zeros(n_c, dtype=int)
    feats, ages_by, amts_by, mon_by = {}, {}, {}, {}
    for ci, cid in enumerate(m.cust_ids):
        ix = np.array(by_c.get(ci, []), dtype=int)
        f = {"customer_id": cid, "tenure_days": float(m.tenure[ci])}
        if len(ix):
            ages, amts, mo = o_age[ix], o_amt[ix], o_month[ix]
            ages_by[ci], amts_by[ci], mon_by[ci] = ages, amts, mo
            in12 = ages <= 365
            n12 = int(in12.sum())
            gaps = np.diff(np.sort(ages))
            r = ret.get(cid, (0, 0))
            tot = max(tot_spend[ci], 1)
            top = np.argsort(-cat_spend[ci])[:3]
            f.update(n_orders=n12, spend_12m=float(amts[in12].sum()), aov=float(amts[in12].mean()) if n12 else 0.0,
                     recency_days=float(ages.min()), first_order_age=float(ages.max()),
                     median_gap=float(np.median(gaps)) if len(gaps) else None,
                     orders_90=int((ages <= 90).sum()), spend_90=float(amts[ages <= 90].sum()),
                     spend_prev90=float(amts[(ages > 90) & (ages <= 180)].sum()), spend_180=float(amts[ages <= 180].sum()),
                     festival_share=float(np.isin(mo[in12], (10, 11)).mean()) if n12 else 0.0,
                     discount_share=float(disc_spend[ci] / tot), premium_share=float(tier_spend[ci, 2] / tot),
                     lines_per_order=float(lpo[ix].mean()),
                     return_rate=float(r[0] / r[1]) if r[1] else 0.0,
                     top_categories=[{"category": m.cat_keys[j], "name": m.cat_meta[m.cat_keys[j]]["name"], "share": round(float(cat_spend[ci, j] / tot), 3)}
                                     for j in top if cat_spend[ci, j] > 0])
            m.n_orders[ci] = n12
        else:
            f.update(n_orders=0, spend_12m=0.0, aov=0.0, recency_days=None, first_order_age=None, median_gap=None, orders_90=0,
                     spend_90=0.0, spend_prev90=0.0, spend_180=0.0, festival_share=0.0, discount_share=0.0, premium_share=0.0,
                     lines_per_order=0.0, return_rate=0.0, top_categories=[])
        feats[cid] = f
    m.feat = feats
    # ---- RFM segments ----
    act = [cid for cid in m.cust_ids if feats[cid]["n_orders"] > 0]
    if act:
        R = np.array([feats[c]["recency_days"] for c in act])
        F = np.array([feats[c]["n_orders"] for c in act], dtype=float)
        Mo = np.array([feats[c]["spend_12m"] for c in act])
        rs, fs, ms = _q(R, reverse=True), _q(F), _q(Mo)
        for k, cid in enumerate(act):
            fc = feats[cid]
            overdue = fc["recency_days"] / max(fc["median_gap"] or 30.0, 7.0)
            fc.update(rfm=[int(rs[k]), int(fs[k]), int(ms[k])], overdue_ratio=round(float(overdue), 2),
                      segment=_segment(fs[k], ms[k], fc["n_orders"], fc["first_order_age"], fc["recency_days"], overdue))
    for cid in m.cust_ids:
        feats[cid].setdefault("rfm", [0, 0, 0])
        feats[cid].setdefault("segment", "Prospect")
    # ---- churn model ----
    if churn is None:
        tenure_by = {ci: float(m.tenure[ci]) for ci in ages_by}
        churn = _train_churn(ages_by, amts_by, mon_by, tenure_by)
    m.churn_clf, m.churn_metrics = churn
    for ci, cid in enumerate(m.cust_ids):
        f = feats[cid]
        if ci not in ages_by:
            f.update(churn_risk=None, clv_12m=0.0)
            continue
        x = _churn_feats(ages_by[ci], amts_by[ci], mon_by[ci], float(m.tenure[ci]), 0)
        if m.churn_clf is not None and x is not None:
            p = float(m.churn_clf.predict_proba([x])[0][1])
        else:
            p = float(min(1.0, (f["recency_days"] or 0) / 180.0))
        if f["festival_share"] >= 0.5 and as_of.month not in (10, 11, 12):
            p *= 0.6        # business rule: seasonal buyers are quiet off-season, not lost
        f["churn_risk"] = round(p, 3)
        months = max(1.0, min(6.0, f["tenure_days"] / 30.0))
        f["clv_12m"] = round(f["spend_180"] / months * 12.0 * (1 - p), 0)
    return m


def shopper_traits(f):
    """Plain-language style labels inferred from behaviour (never from the hidden persona)."""
    t = []
    if f["n_orders"] == 0:
        return [{"key": "new", "label": "Just getting started", "detail": "No orders yet"}]
    share = {c["category"]: c["share"] for c in f["top_categories"]}
    if f["discount_share"] >= 0.40:
        t.append(("deal", "Deal seeker", "%d%% of spend is on discounted items" % round(f["discount_share"] * 100), f["discount_share"]))
    if f["premium_share"] >= 0.35:
        t.append(("premium", "Premium taste", "%d%% of spend on premium brands" % round(f["premium_share"] * 100), f["premium_share"]))
    if f["median_gap"] is not None and f["median_gap"] <= 10 and f["n_orders"] >= 20:
        t.append(("regular", "Regular restocker", "Orders about every %d days" % round(f["median_gap"]), 0.9))
    if f["festival_share"] >= 0.45 and f["n_orders"] >= 4:
        t.append(("festive", "Festive shopper", "%d%% of orders in Oct-Nov" % round(f["festival_share"] * 100), f["festival_share"]))
    tech = share.get("electronics", 0) + share.get("mobile", 0) + share.get("games", 0)
    if tech >= 0.45:
        t.append(("tech", "Tech and gaming fan", "%d%% of spend on gadgets and games" % round(tech * 100), tech))
    style = share.get("fashion", 0) + share.get("personal_care", 0)
    if style >= 0.40:
        t.append(("style", "Style seeker", "%d%% of spend on fashion and beauty" % round(style * 100), style))
    if share.get("sports", 0) >= 0.22:
        t.append(("fit", "Fitness focused", "%d%% of spend on sports and fitness" % round(share["sports"] * 100), share["sports"]))
    home = sum(share.get(k, 0) for k in ("staples", "produce", "dairy", "baby", "home", "bakery"))
    if home >= 0.60:
        t.append(("household", "Household planner", "%d%% of spend on daily essentials" % round(home * 100), home))
    if share.get("books", 0) >= 0.22:
        t.append(("books", "Bookworm", "%d%% of spend on books and stationery" % round(share["books"] * 100), share["books"]))
    if f["aov"] >= 8000:
        t.append(("bigticket", "Big-ticket buyer", "Average order Rs %s" % format(int(f["aov"]), ","), 0.8))
    if f["return_rate"] >= 0.18:
        t.append(("returns", "Frequent returner", "%d%% of orders returned" % round(f["return_rate"] * 100), f["return_rate"]))
    if f["recency_days"] is not None and f["recency_days"] > 90 and f["n_orders"] >= 5:
        t.append(("quiet", "Gone quiet", "No order for %d days" % round(f["recency_days"]), 0.95))
    t.sort(key=lambda x: -x[3])
    return [{"key": k, "label": l, "detail": d} for k, l, d, _ in t[:4]]


# ---------- shared, lazily rebuilt model ----------
class _Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.model = None
        self.dirty = True
        self.churn = None
        self.churn_at = 0.0

    def get(self, conn):
        with self.lock:
            if self.model is None or self.dirty:
                reuse = self.churn if (self.churn and time.time() - self.churn_at < 900) else None
                self.model = build_model(conn, churn=reuse)
                if reuse is None:
                    self.churn = (self.model.churn_clf, self.model.churn_metrics)
                    self.churn_at = time.time()
                self.dirty = False
            return self.model


STORE = _Store()


def mark_dirty():
    STORE.dirty = True


def reset():
    STORE.model, STORE.dirty, STORE.churn = None, True, None


def get_model(conn):
    return STORE.get(conn)


# ---------- SQL aggregates for the dashboards ----------
def customer_insights(conn, cid, now=None):
    now = now or utcnow()
    cmeta = categories.load(conn)[1]
    since = iso(now - timedelta(days=365))
    monthly = rows(conn, "SELECT substr(created_at,1,7) ym, ROUND(SUM(total_paid)) spend, COUNT(*) orders FROM orders WHERE customer_id=? "
                         "AND status IN " + VALID + " AND created_at>? GROUP BY ym ORDER BY ym", (cid, since))
    by_month = {r["ym"]: r for r in monthly}
    series, y, mth = [], now.year, now.month
    for i in range(11, -1, -1):
        yy, mm = y, mth - i
        while mm <= 0:
            mm += 12
            yy -= 1
        key = "%04d-%02d" % (yy, mm)
        series.append({"month": key, "spend": by_month.get(key, {}).get("spend", 0), "orders": by_month.get(key, {}).get("orders", 0)})
    cats = rows(conn, "SELECT oi.category, ROUND(SUM(oi.unit_price*oi.qty)) spend FROM order_items oi JOIN orders o ON o.id=oi.order_id "
                      "WHERE o.customer_id=? AND o.status IN " + VALID + " AND o.created_at>? GROUP BY oi.category ORDER BY spend DESC", (cid, since))
    for c in cats:
        meta = cmeta.get(c["category"], {})
        c.update(name=meta.get("name", c["category"]), emoji=meta.get("emoji", ""), color=meta.get("color", "#ddd"))
    top = rows(conn, "SELECT p.id, p.name, p.emoji, p.unit, SUM(oi.qty) qty, ROUND(SUM(oi.unit_price*oi.qty)) spend FROM order_items oi "
                     "JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE o.customer_id=? AND o.status IN " + VALID +
                     " GROUP BY p.id ORDER BY qty DESC, spend DESC LIMIT 5", (cid,))
    tot = one(conn, "SELECT COUNT(*) orders, COALESCE(SUM(total_paid),0) spend, COALESCE(SUM(product_savings),0) deal_savings, "
                    "COALESCE(SUM(redeem_value),0) points_savings FROM orders WHERE customer_id=? AND status IN " + VALID + " AND created_at>?", (cid, since))
    tot["aov"] = round(tot["spend"] / tot["orders"]) if tot["orders"] else 0
    return {"monthly": series, "categories": cats, "top_products": top, "totals": tot}


def admin_overview(conn, now=None):
    now = now or utcnow()
    cmeta = categories.load(conn)[1]
    d30, d60 = iso(now - timedelta(days=30)), iso(now - timedelta(days=60))
    cur = one(conn, "SELECT COALESCE(SUM(total_paid),0) rev, COUNT(*) orders, COUNT(DISTINCT customer_id) buyers FROM orders WHERE status IN " + VALID + " AND created_at>?", (d30,))
    prev = one(conn, "SELECT COALESCE(SUM(total_paid),0) rev, COUNT(*) orders FROM orders WHERE status IN " + VALID + " AND created_at>? AND created_at<=?", (d60, d30))
    revenue_month = rows(conn, "SELECT substr(created_at,1,7) ym, ROUND(SUM(total_paid)) revenue, COUNT(*) orders FROM orders WHERE status IN " + VALID +
                               " AND created_at>? GROUP BY ym ORDER BY ym", (iso(now - timedelta(days=365)),))
    cat_rev = rows(conn, "SELECT oi.category, ROUND(SUM(oi.unit_price*oi.qty)) revenue FROM order_items oi JOIN orders o ON o.id=oi.order_id "
                         "WHERE o.status IN " + VALID + " AND o.created_at>? GROUP BY oi.category ORDER BY revenue DESC", (d30,))
    for c in cat_rev:
        meta = cmeta.get(c["category"], {})
        c.update(name=meta.get("name", c["category"]), emoji=meta.get("emoji", ""), color=meta.get("color", "#ddd"))
    top = rows(conn, "SELECT p.id, p.name, p.emoji, SUM(oi.qty) qty, ROUND(SUM(oi.unit_price*oi.qty)) revenue FROM order_items oi JOIN orders o ON o.id=oi.order_id "
                     "JOIN products p ON p.id=oi.product_id WHERE o.status IN " + VALID + " AND o.created_at>? GROUP BY p.id ORDER BY revenue DESC LIMIT 6", (d30,))
    stock = one(conn, "SELECT SUM(stock=0 AND active=1) out_of_stock, SUM(stock>0 AND stock<=reorder_level AND active=1) low_stock, COUNT(*) products FROM products")
    pend = one(conn, "SELECT COUNT(*) n, COALESCE(SUM(points_earned),0) pts FROM orders WHERE points_status='pending' AND status IN " + VALID)
    return {
        "revenue_30d": cur["rev"], "revenue_prev_30d": prev["rev"], "orders_30d": cur["orders"], "orders_prev_30d": prev["orders"],
        "active_buyers_30d": cur["buyers"], "aov_30d": round(cur["rev"] / cur["orders"]) if cur["orders"] else 0,
        "revenue_by_month": revenue_month, "revenue_by_category": cat_rev, "top_products": top,
        "out_of_stock": stock["out_of_stock"] or 0, "low_stock": stock["low_stock"] or 0, "products": stock["products"],
        "pending_approvals": pend["n"], "pending_points": pend["pts"],
        "customers": one(conn, "SELECT COUNT(*) n FROM customers")["n"],
    }
