"""LoyaltyIQ: AI-powered customer behaviour, product recommendation and loyalty prototype."""
import logging
import os

from flask import Flask, send_from_directory

from . import config, db

log = logging.getLogger("loyaltyiq")


def ensure_seeded(path=None):
    """Create the database and fill it with demo data the first time the app starts."""
    conn = db.connect(path)
    try:
        db.init_schema(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            from .seed.generate import seed_database
            log.warning("Empty database: seeding demo data (a few seconds)...")
            stats = seed_database(conn)
            log.warning("Seeded %s", stats)
    finally:
        conn.close()


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(SECRET_KEY=config.SECRET_KEY, JSON_SORT_KEYS=False, PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
                      SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
    if test_config:
        app.config.update(test_config)
    ensure_seeded()

    from .api import bp
    app.register_blueprint(bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # warm the analytics model so the first customer request is fast
    try:
        from .services import analytics
        conn = db.connect()
        analytics.get_model(conn)
        conn.close()
    except Exception:   # never block start-up on analytics
        log.exception("Model warm-up failed")
    return app
