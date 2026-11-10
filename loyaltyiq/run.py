"""Run LoyaltyIQ locally:  python run.py   (then open http://localhost:5000)

  python run.py --port 8000     use another port
  python run.py --reset         delete the local database and re-seed fresh demo data
"""
import argparse
import os
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="LoyaltyIQ dev server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--reset", action="store_true", help="delete the database and re-seed")
    ap.add_argument("--debug", action="store_true", help="auto-reload on code changes")
    a = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app import config
    if a.reset:
        for suffix in ("", "-wal", "-shm"):
            Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
        print("Database removed. Fresh demo data will be created now.")
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    from app import create_app
    app = create_app()
    print("\n  LoyaltyIQ is running:  http://%s:%d" % ("localhost" if a.host == "127.0.0.1" else a.host, a.port))
    print("  Log in as admin / 1234, or user1 ... user10 / 1234\n")
    app.run(host=a.host, port=a.port, debug=a.debug, use_reloader=a.debug, threaded=True)


if __name__ == "__main__":
    main()
