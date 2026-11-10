"""Hybrid product recommender.

Score = weighted blend of
  cf_item     item-item collaborative filtering: "customers who bought X also bought this"
  cf_user     taste of the 25 most similar customers
  content     match with the customer's category mix, price band and brand-tier preference
  popularity  what is selling now
  replenish   consumables that are due to be re-ordered (learned per customer, per product)
  promo       discounts, scaled by how much this customer shops deals
  campaign    active "Nx points" campaigns
  margin      small business nudge
then re-ranked with business rules: in stock only, never re-recommend durables already owned,
dampen things bought very recently, and cap items per category for variety.
Every recommendation carries a plain-language reason and the signals that produced it."""
from datetime import timedelta

import numpy as np

from ..db import iso, rows, utcnow
from . import categories
from ..settings import DEFAULT_SETTINGS, load_settings
from . import analytics, loyalty

SIGNALS = ["cf_item", "cf_user", "content", "popularity", "replenish", "promo", "campaign", "margin"]
WEIGHT_KEY = {"cf_item": "w_cf_item", "cf_user": "w_cf_user", "content": "w_content", "popularity": "w_popularity",
              "replenish": "w_replenish", "promo": "w_promo", "campaign": "w_campaign", "margin": "w_margin"}


def _due_curve(due):
    """due = days since last purchase / usual reorder interval. Ramps up as the item comes due,
    stays high while it is plausibly due, then fades: a very overdue item has probably been dropped."""
    if due < 0.7:
        return 0.0
    if due < 1.0:
        return (due - 0.7) / 0.3
    if due <= 2.0:
        return 1.0
    return max(0.05, 1.0 - 0.95 * (due - 2.0) / 2.0)


def _norm(v):
    mx = float(np.max(v)) if len(v) else 0.0
    return v / mx if mx > 1e-12 else np.zeros_like(v)


def _signals(m, ci, camp_mult):
    n_p = len(m.prod_ids)
    S = {}
    u = m.M[ci]
    S["cf_item"] = _norm(u @ m.item_sim)
    sims = m.Mn @ m.Mn[ci]
    sims[ci] = -1
    nb = np.argsort(-sims)[:25]
    wts = np.clip(sims[nb], 0, None)
    S["cf_user"] = _norm((wts @ m.M[nb]) / (wts.sum() + 1e-9)) if wts.sum() > 0 else np.zeros(n_p)
    cs = m.cat_share[ci]
    cat_aff = _norm(cs)[m.cat_i]
    mu = m.mu_logp[ci][m.cat_i]
    mu = np.where(np.isnan(mu), np.log(np.maximum(m.price, 1)), mu)
    fit = np.exp(-(np.log(np.maximum(m.price, 1)) - mu) ** 2 / (2 * 0.6 ** 2))
    tier_fit = _norm(m.tier_share[ci])[m.tier_i]
    S["content"] = cat_aff * (0.4 + 0.6 * fit) * (0.5 + 0.5 * tier_fit)
    S["popularity"] = _norm(np.log1p(m.pop_recent))
    rep = np.zeros(n_p)
    for pi, due, _iv, _ago in m.rep.get(ci, []):
        rep[pi] = _due_curve(due)
    S["replenish"] = rep
    S["promo"] = np.clip(m.promo_pct / 0.30, 0, 1) * float(np.clip(m.disc_share[ci] * 1.6, 0.1, 1))
    S["campaign"] = np.array([np.clip((camp_mult.get(m.cat_keys[c], 1.0) - 1.0) / 2.0, 0, 1) for c in m.cat_i])
    S["margin"] = _norm(np.clip(m.margin, 0, None))
    return S


def _cold_signals(m, camp_mult):
    n_p = len(m.prod_ids)
    S = {k: np.zeros(n_p) for k in SIGNALS}
    S["popularity"] = _norm(np.log1p(m.pop_all))
    S["promo"] = np.clip(m.promo_pct / 0.30, 0, 1) * 0.5
    S["campaign"] = np.array([np.clip((camp_mult.get(m.cat_keys[c], 1.0) - 1.0) / 2.0, 0, 1) for c in m.cat_i])
    S["margin"] = _norm(np.clip(m.margin, 0, None))
    return S


def recommend(m, cid, k=12, weights=None, camp_mult=None, ignore_stock=False, exclude_ids=(), explain=True):
    """Return the top-k recommendations for a customer from an analytics Model."""
    W = weights or DEFAULT_SETTINGS["recommender"]
    camp_mult = camp_mult or {}
    ci = m.cidx.get(cid)
    cold = ci is None or m.n_orders[ci] == 0
    S = _cold_signals(m, camp_mult) if cold else _signals(m, ci, camp_mult)
    if cold:
        W = {**W, "w_popularity": 0.6, "w_promo": 0.2, "w_campaign": 0.15, "w_margin": 0.05}
    contrib = {s: W[WEIGHT_KEY[s]] * S[s] for s in SIGNALS}
    score = sum(contrib.values())
    ok = m.active.copy() if ignore_stock else m.in_stock.copy()
    if not cold:
        ok &= ~(m.owned[ci] & ~m.consumable)                         # never re-recommend durables already bought
        recent = m.consumable & (m.last_age[ci] < 10) & (S["replenish"] < 0.3)
        score = np.where(recent, score * 0.3, score)                   # just bought it and not due
    for pid in exclude_ids:
        if pid in m.pidx:
            ok[m.pidx[pid]] = False
    score = np.where(ok, score, -np.inf)
    order = np.argsort(-score)
    chosen, per_cat = [], {}
    cap = max(2, int(np.ceil(k / 3)))
    for pi in order:
        if not np.isfinite(score[pi]) or len(chosen) >= k:
            break
        c = m.cat_i[pi]
        if per_cat.get(c, 0) >= cap:
            continue
        per_cat[c] = per_cat.get(c, 0) + 1
        chosen.append(int(pi))
    if len(chosen) < k:                                                # relax the cap if the pool is thin
        for pi in order:
            if np.isfinite(score[pi]) and int(pi) not in chosen and len(chosen) < k:
                chosen.append(int(pi))
    out = []
    for pi in chosen:
        p = m.products[pi]
        item = {"id": p["id"], "name": p["name"], "emoji": p["emoji"], "unit": p["unit"], "category": p["category"],
                "category_name": m.cat_meta.get(p["category"], {}).get("name", p["category"]), "price": p["price"], "mrp": p["mrp"], "stock": p["stock"],
                "rating": p["rating"], "discount_pct": round(m.promo_pct[pi] * 100), "score": round(float(score[pi]), 4)}
        if explain:
            top = max(SIGNALS, key=lambda s: contrib[s][pi])
            item["reason_code"], item["reason"] = top, _reason(m, ci, pi, top, cold, camp_mult)
            item["signals"] = {s: round(float(contrib[s][pi]), 4) for s in SIGNALS if contrib[s][pi] > 0.0005}
            item["badges"] = _badges(m, pi, camp_mult)
        out.append(item)
    return out


def _badges(m, pi, camp_mult):
    b = []
    if m.promo_pct[pi] > 0:
        b.append("%d%% off" % round(m.promo_pct[pi] * 100))
    mult = camp_mult.get(m.cat_keys[m.cat_i[pi]], 1.0)
    if mult > 1:
        b.append("%gx points" % mult)
    return b


def _reason(m, ci, pi, code, cold, camp_mult):
    cat_name = m.cat_meta[m.cat_keys[m.cat_i[pi]]]["name"]
    if cold or ci is None:
        return {"campaign": "Earn bonus points on %s right now" % cat_name, "promo": "Great price today"}.get(code, "Popular with shoppers right now")
    if code == "replenish":
        for p, _due, iv, ago in m.rep.get(ci, []):
            if p == pi:
                return "Time to restock: you usually reorder about every %d days (last bought %d days ago)" % (round(iv), round(ago))
    if code == "cf_item":
        src = int(np.argmax(m.M[ci] * m.item_sim[:, pi]))
        if m.M[ci, src] > 0:
            return "Customers who bought %s also bought this" % m.products[src]["name"]
    if code == "cf_user":
        return "Popular with shoppers whose taste is like yours"
    if code == "content":
        return "Matches your interest in %s" % cat_name
    if code == "promo":
        return "%d%% off, and you tend to shop deals" % round(m.promo_pct[pi] * 100)
    if code == "campaign":
        return "%gx points on %s this week" % (camp_mult.get(m.cat_keys[m.cat_i[pi]], 1.0), cat_name)
    if code == "popularity":
        return "Trending now across the store"
    return "A good fit for you"


def campaign_map(conn):
    out = {}
    for c in loyalty.active_campaigns(conn):
        cats = [c["category"]] if c["category"] else categories.load(conn)[0]
        for k in cats:
            out[k] = max(out.get(k, 1.0), float(c["multiplier"]))
    return out


def for_customer(conn, cid, k=12, exclude_ids=()):
    S = load_settings(conn)
    m = analytics.get_model(conn)
    return recommend(m, cid, k=k, weights=S["recommender"], camp_mult=campaign_map(conn), exclude_ids=exclude_ids)


# ---------- offline evaluation ----------
def evaluate(conn, k=10, holdout_days=45, weights=None):
    """Train on everything before the cutoff, then check whether the top-k contains what
    customers actually bought afterwards. Compared with a "most popular items" baseline."""
    W = weights or load_settings(conn)["recommender"]
    cutoff = utcnow() - timedelta(days=holdout_days)
    m = analytics.build_model(conn, as_of=cutoff, churn=(None, {}))
    test = {}
    for r in conn.execute("SELECT o.customer_id, oi.product_id FROM order_items oi JOIN orders o ON o.id=oi.order_id "
                          "WHERE o.created_at>=? AND o.status IN ('placed','delivered')", (iso(cutoff),)):
        test.setdefault(r[0], set()).add(r[1])
    pop_top = [int(i) for i in np.argsort(-m.pop_all)[:k]]
    pop_ids = {int(m.prod_ids[i]) for i in pop_top}
    pop_cats = {int(m.cat_i[i]) for i in pop_top}
    hit = prec = rec = cat_hit = base_hit = base_cat = 0.0
    n, seen = 0, set()
    for cid, bought in test.items():
        ci = m.cidx.get(cid)
        if ci is None or m.n_orders[ci] < 3:
            continue
        recs = recommend(m, cid, k=k, weights=W, ignore_stock=True, explain=False)
        ids = {r["id"] for r in recs}
        cats = {m.cat_keys.index(r["category"]) for r in recs}
        bcats = {int(m.cat_i[m.pidx[b]]) for b in bought if b in m.pidx}
        h = len(ids & bought)
        hit += h > 0
        prec += h / k
        rec += h / max(len(bought), 1)
        cat_hit += bool(cats & bcats)
        base_hit += bool(pop_ids & bought)
        base_cat += bool(pop_cats & bcats)
        seen |= ids
        n += 1
    if n == 0:
        return {"customers": 0}
    return {"k": k, "holdout_days": holdout_days, "customers": n,
            "hit_rate": round(hit / n, 3), "precision": round(prec / n, 3), "recall": round(rec / n, 3),
            "category_hit_rate": round(cat_hit / n, 3), "baseline_hit_rate": round(base_hit / n, 3),
            "baseline_category_hit_rate": round(base_cat / n, 3),
            "catalogue_coverage": round(len(seen) / len(m.prod_ids), 3),
            "lift_vs_popularity": round((hit / n) / max(base_hit / n, 1e-9), 1)}
