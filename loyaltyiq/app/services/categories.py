"""The live category list. The 16 built-in categories are stored in the database so the admin can add more."""
import re

from ..db import one, rows

PALETTE = ["#f6e3b4", "#cfeccb", "#dcebfb", "#fde0c4", "#f4dcc8", "#f6d6e6", "#d7ecee", "#e7dcf7", "#ecdcc9", "#d3dcf5", "#d4efdc", "#fad3d3"]


def load(conn):
    """Return (ordered keys, {key: meta}) where meta has key, name, emoji, color and cycle."""
    r = rows(conn, "SELECT key, name, emoji, color, cycle FROM categories ORDER BY position, key")
    return [x["key"] for x in r], {x["key"]: x for x in r}


def create(conn, name, emoji, color=None, cycle=None):
    name = (name or "").strip()
    emoji = (emoji or "").strip()
    if len(name) < 2 or len(name) > 40:
        raise ValueError("Category name must be 2 to 40 characters")
    if not emoji or len(emoji) > 8:
        raise ValueError("Pick an emoji for the category")
    if cycle in ("", None):
        cycle = None
    else:
        try:
            cycle = int(cycle)
        except (TypeError, ValueError):
            raise ValueError("Repeat cycle must be a whole number of days") from None
        if cycle < 1 or cycle > 365:
            raise ValueError("Repeat cycle must be between 1 and 365 days, or empty for one-off purchases")
    if one(conn, "SELECT 1 x FROM categories WHERE lower(name)=lower(?)", (name,)):
        raise ValueError("A category with this name already exists")
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "category"
    key, n = base, 2
    while one(conn, "SELECT 1 x FROM categories WHERE key=?", (key,)):
        key, n = "%s_%d" % (base, n), n + 1
    pos = one(conn, "SELECT COALESCE(MAX(position),0)+1 p FROM categories")["p"]
    if not color or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)):
        color = PALETTE[pos % len(PALETTE)]
    conn.execute("INSERT INTO categories(key, name, emoji, color, cycle, position, builtin) VALUES(?,?,?,?,?,?,0)", (key, name, emoji, color, cycle, pos))
    return {"key": key, "name": name, "emoji": emoji, "color": color, "cycle": cycle}
