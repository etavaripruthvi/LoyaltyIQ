"""Loyalty engine: tiers, earning, redemption, expiry and admin approvals.

Design rules
- Tier is based on *approved* spend in the last 365 days, so redeeming points never
  lowers a tier and rejected/cancelled orders never count.
- Points live in an append-only ledger. Earn-type rows carry a `remaining` balance that is
  burned FIFO (soonest-expiring first) on redemption and zeroed on expiry.
- Points from flagged orders sit as `pending` until an admin approves, adjusts or rejects.
"""
from datetime import timedelta

from ..db import audit, iso, one, parse, rows, utcnow
from ..settings import load_settings

WINDOW_DAYS = 365
EARN_KINDS = "('earn','bonus','refund')"


# ---------- pure helpers (also used by the seeder) ----------
def tier_index(spend, tiers):
    idx = 0
    for i, t in enumerate(tiers):
        if spend >= t["min_spend"]:
            idx = i
    return idx


def order_points(lines, net_paid, subtotal, tier_mult, loyalty, campaigns=(), offer_mult=1.0):
    """Points for an order and a breakdown. `lines` need line_total and category."""
    ppr = loyalty["points_per_100"]
    if subtotal <= 0:
        return 0, {"base": 0, "tier_bonus": 0, "campaign_bonus": 0, "offer_bonus": 0}
    base = net_paid / 100.0 * ppr
    after_tier = base * tier_mult
    after_campaign = 0.0
    for ln in lines:
        share = ln["line_total"] / subtotal * net_paid
        after_campaign += share / 100.0 * ppr * tier_mult * campaign_multiplier(campaigns, ln["category"])
    total = after_campaign * offer_mult
    b = {"base": int(base), "tier_bonus": int(after_tier) - int(base),
         "campaign_bonus": int(after_campaign) - int(after_tier), "offer_bonus": int(total) - int(after_campaign)}
    return int(total), b


def campaign_multiplier(campaigns, category):
    m = 1.0
    for c in campaigns:
        if c["category"] in (None, "", category):
            m = max(m, float(c["multiplier"]))
    return m


# ---------- tiers ----------
def active_campaigns(conn, now=None):
    now_s = iso(now or utcnow())
    return rows(conn, "SELECT * FROM campaigns WHERE active=1 AND starts_at<=? AND ends_at>=?", (now_s, now_s))


def tier_info(conn, cid, settings=None, now=None):
    S = settings or load_settings(conn)
    tiers = S["loyalty"]["tiers"]
    now = now or utcnow()
    orders = rows(conn,
                  "SELECT created_at, total_paid FROM orders WHERE customer_id=? AND status IN ('placed','delivered') "
                  "AND points_status='approved' AND created_at>? ORDER BY created_at",
                  (cid, iso(now - timedelta(days=WINDOW_DAYS))))
    spend = sum(o["total_paid"] for o in orders)
    i = tier_index(spend, tiers)
    cur = tiers[i]
    nxt = tiers[i + 1] if i + 1 < len(tiers) else None
    if nxt:
        span = max(1.0, nxt["min_spend"] - cur["min_spend"])
        progress = min(1.0, max(0.0, (spend - cur["min_spend"]) / span))
    else:
        progress = 1.0
    # When would the tier drop if the customer stopped buying today?
    drop_date, drop_to, retain_gap = None, None, 0.0
    if i > 0:
        running = spend
        for o in orders:
            running -= o["total_paid"]
            if running < cur["min_spend"]:
                drop_date = parse(o["created_at"]) + timedelta(days=WINDOW_DAYS)
                drop_to = tiers[tier_index(max(running, 0), tiers)]["name"]
                retain_gap = round(cur["min_spend"] - running, 0)
                break
    days_to_drop = (drop_date - now).days if drop_date else None
    return {
        "tier": cur["name"], "index": i, "multiplier": cur["multiplier"], "perks": cur.get("perks", []),
        "spend_12m": round(spend, 2), "next_tier": nxt["name"] if nxt else None,
        "next_threshold": nxt["min_spend"] if nxt else None,
        "gap_to_next": round(max(0.0, nxt["min_spend"] - spend), 2) if nxt else 0.0, "progress": round(progress, 4),
        "drop_date": iso(drop_date)[:10] if drop_date else None, "days_to_drop": days_to_drop, "drop_to": drop_to,
        "retain_gap": retain_gap,
        "at_risk": bool(drop_date and days_to_drop is not None and days_to_drop <= 60),
    }


def tier_names_bulk(conn, settings=None, now=None):
    """customer_id -> (tier index, spend) for everyone in one query (admin lists)."""
    S = settings or load_settings(conn)
    tiers = S["loyalty"]["tiers"]
    now = now or utcnow()
    out = {}
    for r in conn.execute(
            "SELECT customer_id, SUM(total_paid) s FROM orders WHERE status IN ('placed','delivered') "
            "AND points_status='approved' AND created_at>? GROUP BY customer_id", (iso(now - timedelta(days=WINDOW_DAYS)),)):
        out[r[0]] = (tier_index(r[1], tiers), r[1])
    return out


# ---------- points balance ----------
def expire_points(conn, cid=None, now=None, commit=True):
    now_s = iso(now or utcnow())
    sql = ("SELECT id, customer_id, remaining FROM points_ledger WHERE status='active' AND kind IN " + EARN_KINDS +
           " AND remaining>0 AND expires_at<=?")
    args = [now_s]
    if cid is not None:
        sql += " AND customer_id=?"
        args.append(cid)
    expired = rows(conn, sql, args)
    for r in expired:
        conn.execute("UPDATE points_ledger SET remaining=0 WHERE id=?", (r["id"],))
        conn.execute("INSERT INTO points_ledger(customer_id, kind, points, remaining, status, created_at, note) "
                     "VALUES(?,?,?,?,?,?,?)", (r["customer_id"], "expire", -r["remaining"], 0, "active", now_s, "Points expired"))
    if expired and commit:
        conn.commit()
    return len(expired)


def points_summary(conn, cid, now=None):
    now = now or utcnow()
    expire_points(conn, cid, now)
    now_s = iso(now)
    active = one(conn, "SELECT COALESCE(SUM(remaining),0) v FROM points_ledger WHERE customer_id=? AND status='active' "
                       "AND kind IN " + EARN_KINDS, (cid,))["v"]
    pending = one(conn, "SELECT COALESCE(SUM(points),0) v FROM points_ledger WHERE customer_id=? AND status='pending'", (cid,))["v"]
    soon = one(conn, "SELECT COALESCE(SUM(remaining),0) v, MIN(expires_at) d FROM points_ledger WHERE customer_id=? AND status='active' "
                     "AND kind IN " + EARN_KINDS + " AND remaining>0 AND expires_at<=?", (cid, iso(now + timedelta(days=30))))
    nxt = one(conn, "SELECT MIN(expires_at) d FROM points_ledger WHERE customer_id=? AND status='active' AND kind IN " + EARN_KINDS +
                    " AND remaining>0", (cid,))
    earned = one(conn, "SELECT COALESCE(SUM(points),0) v FROM points_ledger WHERE customer_id=? AND status='active' "
                       "AND kind IN ('earn','bonus','refund','reverse')", (cid,))["v"]
    redeemed = one(conn, "SELECT COALESCE(-SUM(points),0) v FROM points_ledger WHERE customer_id=? AND kind='redeem'", (cid,))["v"]
    return {"active": int(active), "pending": int(pending), "expiring_30d": int(soon["v"]),
            "expiring_30d_date": (soon["d"] or "")[:10] or None, "next_expiry": (nxt["d"] or "")[:10] or None,
            "lifetime_earned": int(earned), "lifetime_redeemed": int(redeemed)}


def ledger(conn, cid, limit=60):
    return rows(conn, "SELECT id, order_id, kind, points, remaining, status, created_at, expires_at, note FROM points_ledger "
                      "WHERE customer_id=? ORDER BY created_at DESC, id DESC LIMIT ?", (cid, limit))


# ---------- writes ----------
def credit_points(conn, cid, order_id, points, status, now, note, expiry_days, kind="earn"):
    conn.execute(
        "INSERT INTO points_ledger(customer_id, order_id, kind, points, remaining, status, created_at, expires_at, note) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (cid, order_id, kind, points, points if status == "active" else 0, status, iso(now),
         iso(now + timedelta(days=expiry_days)), note))


def redeem_points(conn, cid, points, order_id, now=None):
    """Burn points FIFO. Raises ValueError if the balance is insufficient."""
    now = now or utcnow()
    expire_points(conn, cid, now, commit=False)   # never commit mid-checkout
    bal = one(conn, "SELECT COALESCE(SUM(remaining),0) v FROM points_ledger WHERE customer_id=? AND status='active' AND kind IN "
              + EARN_KINDS, (cid,))["v"]
    if points > bal:
        raise ValueError("Not enough points")
    need = points
    for r in rows(conn, "SELECT id, remaining FROM points_ledger WHERE customer_id=? AND status='active' AND kind IN " + EARN_KINDS +
                  " AND remaining>0 ORDER BY expires_at, id", (cid,)):
        take = min(need, r["remaining"])
        conn.execute("UPDATE points_ledger SET remaining=remaining-? WHERE id=?", (take, r["id"]))
        need -= take
        if need <= 0:
            break
    conn.execute("INSERT INTO points_ledger(customer_id, order_id, kind, points, remaining, status, created_at, note) "
                 "VALUES(?,?,?,?,?,?,?,?)", (cid, order_id, "redeem", -points, 0, "active", iso(now), "Redeemed at checkout"))


def approve_order(conn, order_id, actor, points=None, note=""):
    o = one(conn, "SELECT * FROM orders WHERE id=?", (order_id,))
    if not o or o["points_status"] != "pending":
        raise ValueError("Order is not waiting for approval")
    S = load_settings(conn)
    now = utcnow()
    pts = o["points_earned"] if points is None else max(0, int(points))
    note = note or ("Adjusted from %d to %d points" % (o["points_earned"], pts) if pts != o["points_earned"] else "Approved")
    conn.execute("UPDATE points_ledger SET points=?, remaining=?, status='active', expires_at=?, note=? "
                 "WHERE order_id=? AND kind='earn' AND status='pending'",
                 (pts, pts, iso(now + timedelta(days=S["loyalty"]["expiry_days"])), note, order_id))
    conn.execute("UPDATE orders SET points_status='approved', points_earned=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                 (pts, actor, iso(now), note, order_id))
    audit(conn, actor, "approve_points", "order %d: %d pts. %s" % (order_id, pts, note))
    return pts


def reject_order(conn, order_id, actor, note=""):
    o = one(conn, "SELECT * FROM orders WHERE id=?", (order_id,))
    if not o or o["points_status"] != "pending":
        raise ValueError("Order is not waiting for approval")
    now = iso(utcnow())
    conn.execute("UPDATE points_ledger SET status='rejected', remaining=0, note=? WHERE order_id=? AND kind='earn' AND status='pending'",
                 (note or "Rejected by admin", order_id))
    conn.execute("UPDATE orders SET points_status='rejected', reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                 (actor, now, note or "Rejected by admin", order_id))
    audit(conn, actor, "reject_points", "order %d. %s" % (order_id, note))


def reverse_order(conn, order_id, reason, actor="system"):
    """Undo the points effect of a cancelled or returned order."""
    o = one(conn, "SELECT * FROM orders WHERE id=?", (order_id,))
    S = load_settings(conn)
    now = utcnow()
    earn = one(conn, "SELECT * FROM points_ledger WHERE order_id=? AND kind='earn'", (order_id,))
    if earn:
        if earn["status"] == "pending":
            conn.execute("UPDATE points_ledger SET status='rejected', remaining=0, note=? WHERE id=?", (reason, earn["id"]))
            conn.execute("UPDATE orders SET points_status='rejected', review_note=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                         (reason, actor, iso(now), order_id))
        elif earn["status"] == "active":
            take = min(earn["remaining"], earn["points"])
            conn.execute("UPDATE points_ledger SET remaining=remaining-? WHERE id=?", (take, earn["id"]))
            conn.execute("INSERT INTO points_ledger(customer_id, order_id, kind, points, remaining, status, created_at, note) "
                         "VALUES(?,?,?,?,?,?,?,?)", (o["customer_id"], order_id, "reverse", -take, 0, "active", iso(now),
                                                     reason + (" (part already spent)" if take < earn["points"] else "")))
    if o["points_redeemed"] > 0:
        credit_points(conn, o["customer_id"], order_id, o["points_redeemed"], "active", now, "Refund: " + reason,
                      S["loyalty"]["expiry_days"], kind="refund")


def grant_bonus(conn, cid, points, note, actor):
    S = load_settings(conn)
    credit_points(conn, cid, None, int(points), "active", utcnow(), note or "Admin bonus", S["loyalty"]["expiry_days"], kind="bonus")
    audit(conn, actor, "grant_bonus", "customer %d: %d pts. %s" % (cid, points, note))


def liability(conn, settings=None):
    S = settings or load_settings(conn)
    r = one(conn, "SELECT COALESCE(SUM(remaining),0) v FROM points_ledger WHERE status='active' AND kind IN " + EARN_KINDS)
    pend = one(conn, "SELECT COALESCE(SUM(points),0) v FROM points_ledger WHERE status='pending'")
    soon = one(conn, "SELECT COALESCE(SUM(remaining),0) v FROM points_ledger WHERE status='active' AND kind IN " + EARN_KINDS +
                     " AND expires_at<=?", (iso(utcnow() + timedelta(days=30)),))
    pv = S["loyalty"]["point_value"]
    return {"active_points": int(r["v"]), "liability_rs": round(r["v"] * pv, 2), "pending_points": int(pend["v"]),
            "expiring_30d_points": int(soon["v"])}
