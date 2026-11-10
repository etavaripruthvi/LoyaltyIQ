"""Customer segmentation views built on the behaviour model, and audience selection for awareness campaigns.

Segments come from analytics (cadence-aware RFM, learned from raw orders). Tiers come from loyalty spend.
Everything here is read-only: it only groups and counts what the model already knows."""
from collections import Counter

from ..settings import load_settings
from . import analytics, loyalty

ORDER = ["Champion", "Loyal", "Promising", "New", "Prospect", "At risk", "Hibernating"]

INFO = {
    "Champion": {"meaning": "Buy often, spend a lot, ordered recently.",
                 "play": "Reward and upsell: early access, premium and complementary products."},
    "Loyal": {"meaning": "Steady repeat buyers who are on their usual rhythm.",
              "play": "Cross-sell into new categories and grow basket size."},
    "Promising": {"meaning": "Several orders but not yet a habit.",
                  "play": "Nudge a second category and the next tier."},
    "New": {"meaning": "First order within the last 30 days.",
            "play": "Introduce popular products and the points programme early."},
    "Prospect": {"meaning": "Registered but never ordered.",
                 "play": "Awareness campaigns on best sellers and a first-order incentive."},
    "At risk": {"meaning": "Normally frequent, now overdue against their own rhythm.",
                "play": "Remind them of what they usually buy before they drift away."},
    "Hibernating": {"meaning": "No order for more than 120 days.",
                    "play": "Win-back with strong deals on products they used to buy."},
}


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def membership(conn, settings=None):
    """customer_id -> {segment, tier}. One pass over the cached model."""
    S = settings or load_settings(conn)
    m = analytics.get_model(conn)
    names = [t["name"] for t in S["loyalty"]["tiers"]]
    bulk = loyalty.tier_names_bulk(conn, S)
    return {cid: {"segment": f["segment"], "tier": names[bulk.get(cid, (0, 0))[0]]} for cid, f in m.feat.items()}, names, m


def summary(conn):
    S = load_settings(conn)
    mem, tier_names, m = membership(conn, S)
    total = len(mem)
    groups = {}
    for cid, x in mem.items():
        groups.setdefault(x["segment"], []).append(cid)
    out = []
    for seg in ORDER + sorted(set(groups) - set(ORDER)):
        ids = groups.get(seg, [])
        feats = [m.feat[i] for i in ids]
        cats = Counter()
        for f in feats:
            for c in f["top_categories"][:2]:
                cats[c["name"]] += 1
        tiers = Counter(mem[i]["tier"] for i in ids)
        traits = Counter(t["label"] for f in feats for t in analytics.shopper_traits(f))
        info = INFO.get(seg, {"meaning": "", "play": ""})
        out.append({
            "segment": seg, "count": len(ids), "share": round(len(ids) / total, 3) if total else 0,
            "meaning": info["meaning"], "play": info["play"],
            "spend_12m_total": round(sum(f["spend_12m"] for f in feats)),
            "spend_12m_avg": round(_avg([f["spend_12m"] for f in feats]) or 0),
            "orders_avg": round(_avg([f["n_orders"] for f in feats]) or 0, 1),
            "aov_avg": round(_avg([f["aov"] for f in feats if f["n_orders"]]) or 0),
            "recency_avg": round(_avg([f["recency_days"] for f in feats]) or 0) if any(f["recency_days"] is not None for f in feats) else None,
            "churn_avg": _avg([f.get("churn_risk") for f in feats]),
            "clv_avg": round(_avg([f.get("clv_12m") for f in feats]) or 0),
            "tiers": {t: tiers.get(t, 0) for t in tier_names},
            "top_categories": [c for c, _ in cats.most_common(3)],
            "top_traits": [t for t, _ in traits.most_common(3)],
        })
    spend_all = sum(s["spend_12m_total"] for s in out) or 1
    for s in out:
        s["spend_share"] = round(s["spend_12m_total"] / spend_all, 3)
    return {"total": total, "tiers": tier_names, "segments": out}


def audience(conn, segments=None, tiers=None, exclude_product=None, settings=None, mem=None):
    """Customer ids matching any chosen segment AND any chosen tier. Empty lists mean everyone.
    exclude_product: leave out people who already bought it (no point advertising what they own)."""
    if mem is None:
        mem = membership(conn, settings)[0]
    segs, trs = set(segments or []), set(tiers or [])
    ids = [cid for cid, x in mem.items() if (not segs or x["segment"] in segs) and (not trs or x["tier"] in trs)]
    if exclude_product and ids:
        bought = {r[0] for r in conn.execute(
            "SELECT DISTINCT o.customer_id FROM orders o JOIN order_items i ON i.order_id=o.id "
            "WHERE i.product_id=? AND o.status IN ('placed','delivered')", (exclude_product,))}
        ids = [i for i in ids if i not in bought]
    return sorted(ids)
