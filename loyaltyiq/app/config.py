"""Runtime configuration. Everything can be overridden with environment variables,
which is how the app is configured on a hosting platform."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "loyaltyiq.db"))

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")

# Demo credentials: admin / user1 ... userN, all with the same easy password.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "1234")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", DEMO_PASSWORD)

# Self sign-up gives a discount, so cap how many accounts one address can open per hour.
REGISTER_LIMIT_PER_HOUR = int(os.environ.get("REGISTER_LIMIT_PER_HOUR", "8"))

SEED = int(os.environ.get("SEED", "42"))
N_BACKGROUND_CUSTOMERS = int(os.environ.get("N_CUSTOMERS", "300"))

# Optional LLM layer (assistant chat + friendlier explanations). Off unless a key is set.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
