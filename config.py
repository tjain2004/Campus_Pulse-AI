"""Central configuration for CampusPulse AI.

Values come from environment variables (optionally loaded from a .env file)
so that API keys never live in source code.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Tiny .env loader so python-dotenv is optional."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DATA_DIR = BASE_DIR / "data"
SAMPLE_CHATS_DIR = DATA_DIR / "sample_chats"
SAMPLE_DOCS_DIR = DATA_DIR / "sample_docs"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("CAMPUSPULSE_DB", str(DATA_DIR / "campuspulse.db")))

# Upload validation
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "10"))

# WhatsApp exports in India are day-first (10/10/26 = 10 Oct 2026).
DATE_ORDER = os.getenv("WHATSAPP_DATE_ORDER", "DMY").upper()  # DMY or MDY

# Optional LLM. The whole app works without one (rule-based engine);
# with a key, classification/extraction and Ask Campus AI get smarter.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").lower()  # none | anthropic | openai
LLM_MODEL = os.getenv("LLM_MODEL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")  # e.g. a Gemini/Groq OpenAI-compatible URL

# Pin "now" for demos so deadlines in the sample chats stay in the future.
_TODAY = os.getenv("CAMPUSPULSE_TODAY", "")


def reference_now() -> datetime:
    if _TODAY:
        try:
            return datetime.fromisoformat(_TODAY)
        except ValueError:
            pass
    return datetime.now().replace(microsecond=0)


# Priority formula weights  P = 0.35U + 0.30D + 0.20R + 0.15C
PRIORITY_WEIGHTS = {"U": 0.35, "D": 0.30, "R": 0.20, "C": 0.15}

DEFAULT_PROFILE = {
    "name": "Demo Student",
    "branch": "CSE - Data Science",
    "year": 4,
    "grad_year": 2027,
    "interests": ["placements", "AI", "hackathons"],
    "skills": ["Python", "SQL", "Machine Learning"],
    "teams": ["Team Aagaz"],
}
