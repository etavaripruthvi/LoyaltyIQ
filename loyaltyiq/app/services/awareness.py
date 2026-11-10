"""Product awareness (advertising) campaigns aimed at chosen customer segments and tiers.

Flow: the admin picks a product, the segments/tiers to reach and a headline. Matching customers see a
'Featured for you' card in their portal. Impressions, clicks and add-to-carts are logged as events and any real
order for the product after a customer's first exposure is attributed to the campaign (7-day grace after it ends).

The admin can also press Simulate to fill a campaign with clearly labelled illustrative traffic (events.simulated=1),
so the report can be explored on a demo database with no real shoppers. Simulated and live numbers are never mixed."""
import json
import random
from datetime import timedelta

from ..db import audit, iso, one, parse, rows, utcnow
from ..settings import load_settings
from . import analytics, loyalty, segments, store

ATTRIBUTION_GRACE_DAYS = 7
KINDS = ("impression", "click", "add_to_cart")

# Illustrative response rates for Simulate. Real numbers always come from tracked events.
BASE_CTR = {"Champion": 0.14, "Loyal": 0.11, "Promising": 0.08, "New": 0.09, "Prospect": 0.05, "At risk": 0.06, "Hibernating": 0.03}


def _jlist(v):
    try:
        return list(json.loads(v)) if v else []
    except (TypeError, ValueError):
        return []


def _status(c, now):
    if c["status"] == "paused":
        return "paused"
    if parse(c["ends_at"]) <= now:
        return "ended"
    if parse(c["starts_at"]) > now:
        return "scheduled"
    return "active"


def _clean_list(value, allowed, label):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("%s must be a list" % label)
    bad = [v for v in value if v not in allowed]
    if bad:
        raise ValueError("Unknown %s: %s" % (label, ", ".join(map(str, bad))))
    return list(dict.fromkeys(value))


def validate(conn, d):
    S = load_settings(conn)
    tier_names = [t["name"] for t in S["loyalty"]["tiers"]]
    all_segments = segments.ORDER
    try:
        pid = int(d.get("product_id"))
    except (TypeError, ValueError):
        raise ValueError("Choose a product to advertise") from None
    prod = one(conn, "SELECT id, name, emoji, category, price, mrp, stock, active FROM products WHERE id=?", (pid,))
    if not prod:
        raise ValueError("That product does not exist")
    if not prod["active"]:
        raise ValueError("That product is switched off in the catalogue")
    segs = _clean_list(d.get("segments"), all_segments, "segment")
    trs = _clean_list(d.get("tiers"), tier_names, "tier")
    try:
        days = int(d.get("days", 14))
    except (TypeError, ValueError):
        raise ValueError("Duration must be a number of days") from None
    if days < 1 or days > 90:
        raise ValueError("Duration must be between 1 and 90 days")
    name = str(d.get("name", "")).strip() or "%s awareness" % prod["name"]
    headline = str(d.get("headline", "")).strip() or "Have you tried %s?" % prod["name"]
    message = str(d.get("message", "")).strip()
    if len(name) > 80 or len(headline) > 90 or len(message) > 240:
        raise ValueError("Name up to 80, headline up to 90 and message up to 240 characters")
    return {"product": prod, "segments": segs, "tiers": trs, "days": days, "name": name, "headline": headline, "message": message,
            "exclude_buyers": 0 if d.get("exclude_buyers") in (False, 0, "0", "false") else 1}


def _fit(m, ids, category):
    """Share of the audience whose two favourite categories include the advertised one."""
    hit = n = 0
    for cid in ids:
        f = m.feat.get(cid)
        if not f or not f["n_orders"]:
            continue
        n += 1
        hit += any(c["category"] == category for c in f["top_categories"][:2])
    return round(hit / n, 3) if n else None


def preview(conn, d):
    v = validate(conn, d)
    mem, _names, m = segments.membership(conn)
    ids = segments.audience(conn, v["segments"], v["tiers"], v["product"]["id"] if v["exclude_buyers"] else None, mem=mem)
    everyone = segments.audience(conn, v["segments"], v["tiers"], mem=mem)
    by = {}
    for cid in ids:
        by[mem[cid]["segment"]] = by.get(mem[cid]["segment"], 0) + 1
    return {"audience": len(ids), "matching": len(everyone), "already_bought": len(everyone) - len(ids), "of_customers": len(mem),
            "by_segment": [{"segment": s, "count": by[s]} for s in segments.ORDER if s in by],
            "category_fit": _fit(m, ids, v["product"]["category"]),
            "product": v["product"]}


def create(conn, d, actor):
    v = validate(conn, d)
    n = len(segments.audience(conn, v["segments"], v["tiers"], v["product"]["id"] if v["exclude_buyers"] else None))
    if n == 0:
        raise ValueError("No customers match these filters, so nobody would see the campaign")
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO ad_campaigns(name, product_id, segments, tiers, exclude_buyers, headline, message, starts_at, ends_at, status, created_by, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?, 'active',?,?)",
        (v["name"], v["product"]["id"], json.dumps(v["segments"]), json.dumps(v["tiers"]), v["exclude_buyers"], v["headline"], v["message"],
         iso(now), iso(now + timedelta(days=v["days"])), actor, iso(now)))
    audit(conn, actor, "awareness_create", "%s (id %d) -> %d customers" % (v["name"], cur.lastrowid, n))
    return cur.lastrowid


def set_status(conn, camp_id, status, actor):
    c = one(conn, "SELECT * FROM ad_campaigns WHERE id=?", (camp_id,))
    if not c:
        raise LookupError("Not found")
    now = utcnow()
    if status == "active":
        if parse(c["ends_at"]) <= now:
            raise ValueError("This campaign has ended. Create a new one to run it again")
        conn.execute("UPDATE ad_campaigns SET status='active' WHERE id=?", (camp_id,))
    elif status == "paused":
        conn.execute("UPDATE ad_campaigns SET status='paused' WHERE id=?", (camp_id,))
    elif status == "ended":
        conn.execute("UPDATE ad_campaigns SET status='active', ends_at=? WHERE id=?", (iso(now), camp_id))
    else:
        raise ValueError("Status must be active, paused or ended")
    audit(conn, actor, "awareness_" + status, "campaign %d" % camp_id)


def _blank():
    return {"impressions": 0, "reached": 0, "clicks": 0, "clickers": 0, "add_to_carts": 0, "carters": 0, "buyers": 0, "units": 0, "revenue": 0.0}


def _rates(b):
    b["ctr"] = round(b["clickers"] / b["reached"], 3) if b["reached"] else None
    b["cart_rate"] = round(b["carters"] / b["clickers"], 3) if b["clickers"] else None
    b["conversion"] = round(b["buyers"] / b["reached"], 3) if b["reached"] else None
    b["revenue"] = round(b["revenue"])
    return b


def _blocks(conn, c, mem, simulated):
    """Totals overall and per segment from events (live or simulated). Live buyers come from real orders."""
    sim = 1 if simulated else 0
    ev = rows(conn, "SELECT customer_id, kind, ts, product_id FROM events WHERE campaign_id=? AND simulated=?", (c["id"], sim))
    per = {}
    first = {}
    for e in ev:
        cid = e["customer_id"]
        b = per.setdefault(cid, {"impression": 0, "click": 0, "add_to_cart": 0, "purchase": 0})
        b[e["kind"]] = b.get(e["kind"], 0) + 1
        if e["kind"] in ("impression", "click"):
            first[cid] = min(first.get(cid, e["ts"]), e["ts"])
    buy = {}
    if simulated:
        price = one(conn, "SELECT price FROM products WHERE id=?", (c["product_id"],))["price"]
        for cid, b in per.items():
            if b["purchase"]:
                buy[cid] = (b["purchase"], b["purchase"] * price)
    elif first:
        end = iso(parse(c["ends_at"]) + timedelta(days=ATTRIBUTION_GRACE_DAYS))
        for r in conn.execute(
                "SELECT o.customer_id, o.created_at, i.qty, i.unit_price FROM orders o JOIN order_items i ON i.order_id=o.id "
                "WHERE i.product_id=? AND o.status IN ('placed','delivered') AND o.created_at<=?", (c["product_id"], end)):
            if r[0] in first and r[1] >= first[r[0]]:
                u, rev = buy.get(r[0], (0, 0.0))
                buy[r[0]] = (u + r[2], rev + r[2] * r[3])
    total, seg = _blank(), {}
    for cid, b in per.items():
        s = mem.get(cid, {}).get("segment", "?")
        for tgt in (total, seg.setdefault(s, _blank())):
            tgt["impressions"] += b["impression"]
            tgt["clicks"] += b["click"]
            tgt["add_to_carts"] += b["add_to_cart"]
            tgt["reached"] += 1 if (b["impression"] or b["click"]) else 0
            tgt["clickers"] += 1 if b["click"] else 0
            tgt["carters"] += 1 if b["add_to_cart"] else 0
    for cid, (u, rev) in buy.items():
        s = mem.get(cid, {}).get("segment", "?")
        for tgt in (total, seg.setdefault(s, _blank())):
            tgt["buyers"] += 1
            tgt["units"] += u
            tgt["revenue"] += rev
    return _rates(total), [dict(segment=s, **_rates(seg[s])) for s in segments.ORDER + ["?"] if s in seg]


def describe(conn, c, mem, now, with_stats=True):
    prod = one(conn, "SELECT id, name, emoji, category, price, mrp, stock FROM products WHERE id=?", (c["product_id"],))
    segs, trs = _jlist(c["segments"]), _jlist(c["tiers"])
    out = {"id": c["id"], "name": c["name"], "headline": c["headline"], "message": c["message"], "product": prod, "segments": segs, "tiers": trs,
           "exclude_buyers": bool(c["exclude_buyers"]), "starts_at": c["starts_at"], "ends_at": c["ends_at"], "status": _status(c, now),
           "created_by": c["created_by"], "audience": len(segments.audience(conn, segs, trs, c["product_id"] if c["exclude_buyers"] else None, mem=mem))}
    if with_stats:
        live, live_seg = _blocks(conn, c, mem, False)
        sim, sim_seg = _blocks(conn, c, mem, True)
        out.update(live=live, live_by_segment=live_seg, simulated=sim, simulated_by_segment=sim_seg)
    return out


def list_all(conn):
    now = utcnow()
    mem = segments.membership(conn)[0]
    return [describe(conn, c, mem, now) for c in rows(conn, "SELECT * FROM ad_campaigns ORDER BY id DESC")]


def get(conn, camp_id):
    c = one(conn, "SELECT * FROM ad_campaigns WHERE id=?", (camp_id,))
    if not c:
        raise LookupError("Not found")
    return describe(conn, c, segments.membership(conn)[0], utcnow())


def remove(conn, camp_id, actor):
    if not one(conn, "SELECT 1 x FROM ad_campaigns WHERE id=?", (camp_id,)):
        raise LookupError("Not found")
    conn.execute("DELETE FROM events WHERE campaign_id=?", (camp_id,))
    conn.execute("DELETE FROM ad_campaigns WHERE id=?", (camp_id,))
    audit(conn, actor, "awareness_delete", "campaign %d" % camp_id)


# ---------- customer side ----------
def _eligible(conn, cid, c, seg, tier, now):
    if _status(c, now) != "active":
        return False
    segs, trs = _jlist(c["segments"]), _jlist(c["tiers"])
    if (segs and seg not in segs) or (trs and tier not in trs):
        return False
    if c["exclude_buyers"] and one(conn, "SELECT 1 x FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.customer_id=? AND i.product_id=? "
                                         "AND o.status IN ('placed','delivered') LIMIT 1", (cid, c["product_id"])):
        return False
    return True


def for_customer(conn, cid):
    now = utcnow()
    camps = rows(conn, "SELECT * FROM ad_campaigns WHERE status='active' AND starts_at<=? AND ends_at>? ORDER BY id DESC", (iso(now), iso(now)))
    if not camps:
        return []
    seg = analytics.get_model(conn).feat[cid]["segment"]
    tier = loyalty.tier_info(conn, cid)["tier"]
    out = []
    for c in camps:
        if not _eligible(conn, cid, c, seg, tier, now):
            continue
        prod = store.get_products(conn, [c["product_id"]])
        if not prod or prod[0].get("stock", 0) <= 0:
            continue
        out.append({"campaign_id": c["id"], "headline": c["headline"], "message": c["message"], "product": prod[0], "ends_at": c["ends_at"]})
    return out[:3]


def record(conn, cid, camp_id, kind, surface="home"):
    if kind not in KINDS:
        raise ValueError("Unknown event")
    c = one(conn, "SELECT * FROM ad_campaigns WHERE id=?", (camp_id,))
    now = utcnow()
    if not c:
        raise LookupError("Not found")
    seg = analytics.get_model(conn).feat[cid]["segment"]
    if not _eligible(conn, cid, c, seg, loyalty.tier_info(conn, cid)["tier"], now):
        return False
    surface = str(surface or "home")[:20]
    if kind == "impression" and one(conn, "SELECT 1 x FROM events WHERE customer_id=? AND campaign_id=? AND kind='impression' AND simulated=0 AND surface=? AND ts>?",
                                    (cid, camp_id, surface, iso(now - timedelta(hours=6)))):
        return False
    conn.execute("INSERT INTO events(ts, customer_id, kind, campaign_id, product_id, surface, simulated) VALUES(?,?,?,?,?,?,0)",
                 (iso(now), cid, kind, camp_id, c["product_id"], surface))
    return True


# ---------- simulated traffic for demos ----------
def simulate(conn, camp_id, actor):
    c = one(conn, "SELECT * FROM ad_campaigns WHERE id=?", (camp_id,))
    if not c:
        raise LookupError("Not found")
    now = utcnow()
    mem, _n, m = segments.membership(conn)
    ids = segments.audience(conn, _jlist(c["segments"]), _jlist(c["tiers"]), c["product_id"] if c["exclude_buyers"] else None, mem=mem)
    prod = one(conn, "SELECT category FROM products WHERE id=?", (c["product_id"],))
    rng = random.Random(camp_id * 7919)
    start, end = parse(c["starts_at"]), min(now, parse(c["ends_at"]))
    span = max(3600, int((end - start).total_seconds()))
    conn.execute("DELETE FROM events WHERE campaign_id=? AND simulated=1", (camp_id,))
    batch = []

    def at(offset):
        return iso(start + timedelta(seconds=min(span, offset)))
    for cid in ids:
        if rng.random() > 0.85:
            continue
        f = m.feat[cid]
        seg = mem[cid]["segment"]
        fit = any(x["category"] == prod["category"] for x in f["top_categories"][:2])
        t0 = rng.randint(0, span)
        batch.append((at(t0), cid, "impression", camp_id, c["product_id"], "home", 1))
        if rng.random() < min(0.6, BASE_CTR.get(seg, 0.06) * (1.8 if fit else 1.0)):
            t1 = t0 + rng.randint(30, 4 * 3600)
            batch.append((at(t1), cid, "click", camp_id, c["product_id"], "home", 1))
            if rng.random() < (0.45 if fit else 0.3):
                batch.append((at(t1 + 60), cid, "add_to_cart", camp_id, c["product_id"], "home", 1))
                if rng.random() < (0.55 if fit else 0.4):
                    batch.append((at(t1 + 900), cid, "purchase", camp_id, c["product_id"], "home", 1))
    conn.executemany("INSERT INTO events(ts, customer_id, kind, campaign_id, product_id, surface, simulated) VALUES(?,?,?,?,?,?,?)", batch)
    audit(conn, actor, "awareness_simulate", "campaign %d: %d simulated events" % (camp_id, len(batch)))
    return len(batch)


def clear_simulated(conn, camp_id, actor):
    n = conn.execute("DELETE FROM events WHERE campaign_id=? AND simulated=1", (camp_id,)).rowcount
    audit(conn, actor, "awareness_clear_simulated", "campaign %d: %d events" % (camp_id, n))
    return n
