"""The loyalty agent.

For one customer it gathers signals with a small set of "tools" (profile and behaviour analytics,
loyalty status, recommendations), proposes candidate actions, scores them and returns a ranked
list. The top one is the next-best-action. Any personal offer is checked against admin-set budget
guardrails before it can be activated.

The reasoning is deterministic, so it works offline. If ANTHROPIC_API_KEY is set, the chat
assistant also asks Claude to phrase its answer, using the same facts as context."""
from datetime import timedelta

from .. import config
from ..db import iso, one, rows, utcnow
from . import categories
from ..settings import load_settings
from . import analytics, loyalty, recommender, store

CATEGORY_WORDS = {
    "grocer": "staples", "staple": "staples", "rice": "staples", "dal": "staples", "fruit": "produce", "vegetable": "produce",
    "veg": "produce", "milk": "dairy", "dairy": "dairy", "egg": "dairy", "snack": "snacks", "drink": "snacks", "chocolate": "snacks",
    "bread": "bakery", "bakery": "bakery", "beauty": "personal_care", "skin": "personal_care", "shampoo": "personal_care",
    "clean": "home", "household": "home", "baby": "baby", "kid": "baby", "pet": "pet", "dog": "pet", "cat food": "pet",
    "kitchen": "kitchen", "cook": "kitchen", "electronic": "electronics", "laptop": "electronics", "tv": "electronics",
    "headphone": "electronics", "phone": "mobile", "charger": "mobile", "game": "games", "toy": "games", "gaming": "games",
    "sport": "sports", "fitness": "sports", "gym": "sports", "protein": "sports", "fashion": "fashion", "cloth": "fashion",
    "shoe": "fashion", "book": "books", "stationery": "books", "notebook": "books",
}


# ---------- offers and guardrails ----------
def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0)


def _offer(conn, S, f, tier, mult, days, reason):
    pts_per_order = max(f["aov"], 500) / 100.0 * S["loyalty"]["points_per_100"] * tier["multiplier"]
    cost = round(pts_per_order * (mult - 1.0) * S["loyalty"]["point_value"], 2)
    now = utcnow()
    used = one(conn, "SELECT COALESCE(SUM(cost_est),0) v FROM offers WHERE created_at>=?", (iso(_month_start(now)),))["v"]
    cap = S["offers"]["per_customer_cap"]
    budget = S["offers"]["monthly_budget"]
    allowed, blocked = True, None
    if cost > cap:
        allowed, blocked = False, "Estimated cost Rs %d is above the per-offer cap of Rs %d" % (cost, cap)
    elif used + cost > budget:
        allowed, blocked = False, "Monthly offer budget of Rs %s is used up" % format(int(budget), ",")
    return {"kind": "points_multiplier", "multiplier": mult, "days": days, "cost_est": cost, "reason": reason,
            "allowed": allowed, "blocked_reason": blocked}


def activate_offer(conn, cid, code):
    if one(conn, "SELECT 1 x FROM offers WHERE customer_id=? AND status='active' AND expires_at>?", (cid, iso(utcnow()))):
        raise ValueError("You already have an active offer. Use it on your next order first.")
    action = next((a for a in analyze(conn, cid)["actions"] if a["code"] == code and a.get("offer")), None)
    if not action:
        raise ValueError("That offer is no longer available")
    o = action["offer"]
    if not o["allowed"]:
        raise ValueError(o["blocked_reason"] or "Offer unavailable")
    now = utcnow()
    cur = conn.execute("INSERT INTO offers(customer_id, kind, multiplier, reason, cost_est, created_at, expires_at, status) VALUES(?,?,?,?,?,?,?,'active')",
                       (cid, o["kind"], o["multiplier"], o["reason"], o["cost_est"], iso(now), iso(now + timedelta(days=o["days"]))))
    conn.commit()
    return {"id": cur.lastrowid, "multiplier": o["multiplier"], "expires_at": iso(now + timedelta(days=o["days"]))}


def offer_budget(conn, S=None):
    S = S or load_settings(conn)
    now = utcnow()
    r = one(conn, "SELECT COALESCE(SUM(cost_est),0) used, COUNT(*) n FROM offers WHERE created_at>=?", (iso(_month_start(now)),))
    used_up = one(conn, "SELECT COUNT(*) n FROM offers WHERE created_at>=? AND status='used'", (iso(_month_start(now)),))["n"]
    return {"budget": S["offers"]["monthly_budget"], "committed": round(r["used"], 2), "offers_issued": r["n"], "offers_used": used_up}


# ---------- the analysis ----------
def _fill_gap(recs, gap):
    picked, total = [], 0.0
    for r in recs:
        if total >= gap or len(picked) >= 4:
            break
        picked.append(r)
        total += r["price"]
    return picked, total


def analyze(conn, cid, k=12):
    S = load_settings(conn)
    m = analytics.get_model(conn)
    f = m.feat[cid]
    tier = loyalty.tier_info(conn, cid, S)
    pts = loyalty.points_summary(conn, cid)
    recs = recommender.for_customer(conn, cid, k=k)
    cust = one(conn, "SELECT name FROM customers WHERE id=?", (cid,))
    first = cust["name"].split()[0]
    pv = S["loyalty"]["point_value"]
    n = f["n_orders"]
    churn = f.get("churn_risk") or 0.0
    A = []

    def add(code, title, message, priority, why, items=(), offer=None, cta=None):
        A.append({"code": code, "title": title, "message": message, "priority": round(priority), "why": why,
                  "items": list(items), "offer": offer, "cta": cta or {"label": "Shop now", "route": "shop"}})

    if n == 0:
        na = store.new_account_offer(conn, cid, S)
        perk = []
        if na and na["discount_pct"] > 0:
            perk.append("%g%% off" % na["discount_pct"])
        if na and na["bonus_points_pct"] > 0:
            perk.append("%g%% extra points" % na["bonus_points_pct"])
        add("WELCOME", "Welcome aboard",
            "Hi %s! Place your first order and we'll add %d bonus points straight away" % (first, S["loyalty"]["welcome_bonus"]) +
            (", plus your new-account offer: %s." % " and ".join(perk) if perk else "."),
            90, ["No orders yet", "Welcome bonus: %d points" % S["loyalty"]["welcome_bonus"]] + (["New-account offer: " + " and ".join(perk)] if perk else []), recs[:4])
    # win-back
    if n >= 3 and (f["recency_days"] or 0) > 30 and (churn >= 0.5 or (f.get("overdue_ratio") or 0) >= 2.5):
        mult = 3.0 if churn >= 0.8 else 2.0
        offer = _offer(conn, S, f, tier, mult, 14, "Win-back offer")
        add("WIN_BACK", "We miss you", "It has been %d days since your last order, %s. Activate this offer for %gx points on your next order in the next 14 days."
            % (round(f["recency_days"]), first, mult), 62 + 38 * churn,
            ["Churn risk %d%%" % round(churn * 100), "Usually orders every %s days; last order %d days ago" % (round(f["median_gap"] or 0), round(f["recency_days"])),
             "Estimated 12-month value at stake: Rs %s" % format(int(f["clv_12m"]), ",")],
            [r for r in recs if r["reason_code"] == "replenish"][:2] + [r for r in recs if r["reason_code"] != "replenish"][:2], offer,
            {"label": "Activate offer and shop", "route": "shop"})
    # tier protection
    if tier["at_risk"] and tier["drop_to"]:
        offer = _offer(conn, S, f, tier, 1.5, 21, "Tier retention offer")
        add("TIER_AT_RISK", "Keep your %s status" % tier["tier"],
            "Your %s status is set to drop to %s on %s. Shop Rs %s more before then to keep %gx points."
            % (tier["tier"], tier["drop_to"], tier["drop_date"], format(int(tier["retain_gap"]), ","), tier["multiplier"]), 66,
            ["%s ends on %s" % (tier["tier"], tier["drop_date"]), "Needs Rs %s more spend to retain" % format(int(tier["retain_gap"]), ",")],
            _fill_gap(recs, tier["retain_gap"])[0], offer)
    # upgrade nudge
    if tier["next_tier"]:
        gap = tier["gap_to_next"]
        close = gap <= max(4000.0, 0.15 * tier["next_threshold"])
        if close and n > 0:
            items, tot = _fill_gap(recs, gap)
            nxt_mult = next(t["multiplier"] for t in S["loyalty"]["tiers"] if t["name"] == tier["next_tier"])
            offer = _offer(conn, S, f, tier, 1.5, 14, "Upgrade boost")
            add("TIER_NUDGE", "Almost %s" % tier["next_tier"], "You're Rs %s away from %s, which unlocks %gx points. These picks could get you there."
                % (format(int(gap), ","), tier["next_tier"], nxt_mult), 52 + 30 * max(0.0, 1 - gap / max(1.0, 0.15 * tier["next_threshold"])),
                ["Rs %s to next tier" % format(int(gap), ","), "%d%% of the way there" % round(tier["progress"] * 100)], items, offer)
    # expiring points
    if pts["expiring_30d"] >= 50:
        add("EXPIRING_POINTS", "Points expiring soon", "%d points (worth Rs %s) expire on %s. Redeem them on your next order so they don't go to waste."
            % (pts["expiring_30d"], format(int(pts["expiring_30d"] * pv), ","), pts["expiring_30d_date"]), 58 + min(20, pts["expiring_30d"] / 25.0),
            ["%d points expire within 30 days" % pts["expiring_30d"]], recs[:3], cta={"label": "Shop and redeem", "route": "shop"})
    # replenishment
    due = [r for r in recs if r["reason_code"] == "replenish"]
    if len(due) >= 2:
        add("REPLENISH", "Time to restock", "%d things you buy regularly are due for a reorder." % len(due), 48 + 4 * min(len(due), 5),
            ["Reorder cycles learned from your past orders"], due[:4])
    # redeem
    if pts["active"] >= 300 and pts["expiring_30d"] < 50:
        add("REDEEM", "Use your points", "You have %d points worth Rs %s. You can use them for up to %d%% off any order." % (pts["active"], format(int(pts["active"] * pv), ","),
                                                                                            S["loyalty"]["max_redeem_pct"]), 40, ["Large unused balance"], recs[:3])
    # discover
    fresh = [r for r in recs if m.cat_share[m.cidx[cid]][m.cat_keys.index(r["category"])] < 0.03] if n else []
    if fresh:
        add("DISCOVER", "Try something new", "Shoppers with a taste like yours also love these.", 30, ["Categories you haven't explored yet"], fresh[:4])
    add("FOR_YOU", "Picked for you", "Fresh picks based on what you buy and what is trending.", 25, ["Personalised ranking"], recs[:4])
    A.sort(key=lambda a: -a["priority"])
    return {"customer_id": cid, "first_name": first, "tier": tier, "points": pts, "features": f, "traits": analytics.shopper_traits(f),
            "actions": A, "next_best_action": A[0], "recommendations": recs}


# ---------- admin portfolio view ----------
def portfolio(conn, limit=8):
    S = load_settings(conn)
    m = analytics.get_model(conn)
    names = {r["id"]: r["name"] for r in rows(conn, "SELECT id, name FROM customers")}
    tiers = S["loyalty"]["tiers"]
    bulk = loyalty.tier_names_bulk(conn, S)
    win, up = [], []
    for cid, f in m.feat.items():
        if f["n_orders"] >= 3 and (f.get("churn_risk") or 0) >= 0.5 and (f["recency_days"] or 0) > 30:
            win.append({"customer_id": cid, "name": names[cid], "churn_risk": f["churn_risk"], "clv_12m": f["clv_12m"],
                        "recency_days": round(f["recency_days"]), "segment": f["segment"]})
        ti, spend = bulk.get(cid, (0, 0.0))
        if ti + 1 < len(tiers):
            gap = tiers[ti + 1]["min_spend"] - spend
            if 0 < gap <= max(4000.0, 0.15 * tiers[ti + 1]["min_spend"]) and f["n_orders"] > 0:
                up.append({"customer_id": cid, "name": names[cid], "tier": tiers[ti]["name"], "next_tier": tiers[ti + 1]["name"], "gap": round(gap)})
    win.sort(key=lambda x: -(x["churn_risk"] * (x["clv_12m"] + 1)))
    up.sort(key=lambda x: x["gap"])
    expiring = rows(conn, "SELECT c.id customer_id, c.name, SUM(l.remaining) points FROM points_ledger l JOIN customers c ON c.id=l.customer_id "
                          "WHERE l.status='active' AND l.kind IN ('earn','bonus','refund') AND l.remaining>0 AND l.expires_at<=? GROUP BY c.id "
                          "ORDER BY points DESC LIMIT ?", (iso(utcnow() + timedelta(days=30)), limit))
    return {"win_back": {"count": len(win), "top": win[:limit]}, "upgrade_candidates": {"count": len(up), "top": up[:limit]},
            "expiring": expiring, "offer_budget": offer_budget(conn, S)}


# ---------- chat assistant ----------
def _cards(items, n=4):
    return [{k: r[k] for k in ("id", "name", "emoji", "unit", "price", "mrp", "reason", "category_name", "badges") if k in r} for r in items[:n]]


def chat(conn, cid, message):
    msg = (message or "").lower().strip()
    a = analyze(conn, cid)
    t, p, f = a["tier"], a["points"], a["features"]
    S = load_settings(conn)
    pv = S["loyalty"]["point_value"]
    products, quick = [], ["What's my tier?", "Recommend something", "Any offers for me?", "When do my points expire?"]
    cat = next((v for k, v in CATEGORY_WORDS.items() if k in msg), None)
    if any(w in msg for w in ("hello", "hi ", "hey", "good morning", "good evening")) or msg in ("hi", "hey", "hello"):
        reply = "Hi %s! I can explain your points and tier, suggest products, and find offers. What would you like to do?" % a["first_name"]
    elif any(w in msg for w in ("expire", "expiry", "expiring")):
        reply = ("%d of your points (about Rs %s) expire on %s. " % (p["expiring_30d"], format(int(p["expiring_30d"] * pv), ","), p["expiring_30d_date"])
                 if p["expiring_30d"] else "None of your points expire in the next 30 days.") + \
                (" Your next expiry date is %s." % p["next_expiry"] if p["next_expiry"] else "")
    elif any(w in msg for w in ("point", "balance", "reward", "redeem")):
        reply = "You have %d active points (worth Rs %s)." % (p["active"], format(int(p["active"] * pv), ","))
        if p["pending"]:
            reply += " Another %d points are waiting for admin approval." % p["pending"]
        reply += " You can redeem from %d points, up to %d%% of an order." % (S["loyalty"]["min_redeem"], S["loyalty"]["max_redeem_pct"])
    elif any(w in msg for w in ("tier", "level", "status", "gold", "silver", "platinum", "bronze", "upgrade")):
        reply = "You're %s, earning %gx points. You've spent Rs %s in the last 12 months." % (t["tier"], t["multiplier"], format(int(t["spend_12m"]), ","))
        if t["next_tier"]:
            reply += " Spend Rs %s more to reach %s." % (format(int(t["gap_to_next"]), ","), t["next_tier"])
        if t["at_risk"]:
            reply += " Heads up: your status drops to %s on %s unless you spend Rs %s more." % (t["drop_to"], t["drop_date"], format(int(t["retain_gap"]), ","))
        quick = ["How do I reach the next tier?", "Recommend something", "When do my points expire?"]
    elif any(w in msg for w in ("offer", "deal", "discount", "coupon", "promo")):
        nba = next((x for x in a["actions"] if x.get("offer")), a["next_best_action"])
        reply = nba["message"]
        products = _cards(nba["items"])
    elif any(w in msg for w in ("order", "track", "delivery", "bought", "last purchase")):
        o = one(conn, "SELECT id, created_at, status, total_paid FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 1", (cid,))
        reply = ("Your latest order #%d (%s) is %s, total Rs %s." % (o["id"], o["created_at"][:10], o["status"], format(int(o["total_paid"]), ","))
                 if o else "You haven't placed an order yet.")
    elif any(w in msg for w in ("spend", "spent", "how much")):
        reply = "In the last 12 months you spent Rs %s over %d orders (average Rs %s)." % (format(int(f["spend_12m"]), ","), f["n_orders"], format(int(f["aov"]), ","))
    elif any(w in msg for w in ("recommend", "suggest", "buy", "gift", "show", "find", "looking", "want", "need")) or cat:
        recs = recommender.for_customer(conn, cid, k=40)
        if cat:
            recs = [r for r in recs if r["category"] == cat]
            reply = "Here are my top picks in %s for you." % categories.load(conn)[1].get(cat, {}).get("name", cat) if recs else "I couldn't find in-stock picks in that category right now."
        else:
            reply = "Here is what I'd suggest for you right now."
        products = _cards(recs)
    else:
        nba = a["next_best_action"]
        reply = "I can help with points, tiers, offers, orders and product ideas. Meanwhile: " + nba["message"]
        products = _cards(nba["items"])
    out = {"reply": reply, "products": products, "suggestions": quick, "source": "rules"}
    llm = _llm_rephrase(a, message, reply)
    if llm:
        out["reply"], out["source"] = llm, "claude"
    return out


def _llm_rephrase(a, user_msg, draft):
    """Optional: ask Claude to phrase the answer. Facts come from the rule-based draft, so nothing is invented."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import requests
        system = ("You are a friendly loyalty-programme assistant for an online store. Rewrite the DRAFT reply so it answers the customer's "
                  "message naturally in at most 3 sentences. Use only facts in the draft or context. Never invent points, prices or offers.")
        ctx = {"tier": a["tier"]["tier"], "points": a["points"], "next_best_action": a["next_best_action"]["message"]}
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=15,
                          headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": config.LLM_MODEL, "max_tokens": 300, "system": system,
                                "messages": [{"role": "user", "content": "Customer message: %s\nContext: %s\nDRAFT: %s" % (user_msg, ctx, draft)}]})
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception:
        return None
