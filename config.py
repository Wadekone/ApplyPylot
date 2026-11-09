"""Central configuration. Values come from the environment (or a local .env file)."""
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

# LLM
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = 0.2

# Ingestion
RAPIDAPI_HOST = "jsearch.p.rapidapi.com"
DEFAULT_QUERY = "Delivery Manager"
DEFAULT_LOCATION = "Remote"
HTTP_TIMEOUT_SECONDS = 30

# Scoring thresholds (single source of truth for PASS / BORDERLINE / FAIL)
PASS_THRESHOLD = 7.5
BORDERLINE_THRESHOLD = 5.0


def db_path() -> str:
    """Resolved at call time so tests/evals can point at a scratch database."""
    return os.environ.get("APPLYPILOT_DB_PATH", os.path.join(BASE_DIR, "data", "applypilot.db"))


def status_for_score(score: float) -> str:
    if score >= PASS_THRESHOLD:
        return "PASS"
    if score >= BORDERLINE_THRESHOLD:
        return "BORDERLINE"
    return "FAIL"
