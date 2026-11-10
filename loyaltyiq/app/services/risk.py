"""Order risk screening. Every order gets a risk score (0-100) and a list of plain-language
flags. Orders at or above the admin-set threshold (or any order, if the approval mode is
"all") are held in the approvals queue; everything else is auto-approved."""
import json
import statistics

from ..db import one, parse, rows
from ..settings import load_settings


def screen(conn, order_id, settings=None):
    S = settings or load_settings(conn)
    A = S["approval"]
    o = one(conn, "SELECT * FROM orders WHERE id=?", (order_id,))
    items = rows(conn, "SELECT qty FROM order_items WHERE order_id=?", (order_id,))
    created = parse(o["created_at"])
    net = o["total_paid"]
    prev = rows(conn, "SELECT created_at, total_paid, status FROM orders WHERE customer_id=? AND id<>? AND created_at<=? "
                      "ORDER BY created_at", (o["customer_id"], order_id, o["created_at"]))
    valid = [p for p in prev if p["status"] in ("placed", "delivered")]
    flags = []

    def add(code, text, weight):
        flags.append({"code": code, "text": text, "weight": weight})

    if net >= A["large_order_threshold"]:
        add("LARGE_ORDER", "Order value Rs %s is above the Rs %s approval threshold" % (format(int(net), ","), format(int(A["large_order_threshold"]), ",")), 45)
    last_day = [p for p in prev if (created - parse(p["created_at"])).total_seconds() <= 86400]
    if len(last_day) >= 2:
        add("BURST", "%d orders from this customer within 24 hours" % (len(last_day) + 1), 40)
    qtys = [i["qty"] for i in items]
    if qtys and (max(qtys) >= 10 or sum(qtys) >= 20):
        add("BULK_QTY", "Unusually large quantity (%d units in one order)" % sum(qtys), 35)
    if len(valid) <= 1 and net >= 5000:
        add("NEW_HIGH_VALUE", "New customer placing a high-value order (Rs %s)" % format(int(net), ","), 40)
    if len(valid) >= 5:
        med = statistics.median(p["total_paid"] for p in valid)
        if med > 0 and net >= 4 * med and net >= 3000:
            add("ANOMALOUS_VALUE", "Order is %.1fx this customer's median order (Rs %s)" % (net / med, format(int(med), ",")), 35)
    if len(prev) >= 4:
        rr = sum(1 for p in prev if p["status"] == "returned") / len(prev)
        if rr >= 0.25:
            add("RETURN_HISTORY", "High return history (%d%% of past orders returned)" % round(rr * 100), 25)

    score = min(100, sum(f["weight"] for f in flags))
    needs = A["mode"] == "all" or score >= A["risk_threshold"]
    suggestion = "approve" if score < 40 else ("review" if score < 70 else "hold")
    return {"score": score, "flags": flags, "needs_approval": needs, "suggestion": suggestion}


def save(conn, order_id, result):
    conn.execute("UPDATE orders SET risk_score=?, risk_flags=? WHERE id=?",
                 (result["score"], json.dumps(result["flags"]), order_id))
