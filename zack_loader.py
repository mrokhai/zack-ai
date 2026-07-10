"""
Zack.ai — Config Loader (All Agents)

Reads zack_config.py which auto-merges zack_master.py if present.
All Zack scripts import this instead of hardcoding values.
"""

import os

try:
    import zack_config as cfg
    CONFIG_LOADED = True
except ImportError:
    CONFIG_LOADED = False
    cfg = None

def get(key, default=""):
    if cfg and hasattr(cfg, key):
        return getattr(cfg, key)
    return os.environ.get(key, default)

# ── Core credentials ──────────────────────────────────────────────────────────
SPREADSHEET_ID = get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_PATH = get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
GROQ_API_KEY = get("GROQ_API_KEY")

# ── Identity (Section 1) ──────────────────────────────────────────────────────
CLIENT_NAME = get("CLIENT_NAME", "Zack User")
CLIENT_FIRST_NAME = get("CLIENT_FIRST_NAME", "")
CLIENT_TITLE = get("CLIENT_TITLE", "Founder")
CLIENT_COMPANY = get("CLIENT_COMPANY", "")
CLIENT_LINKEDIN = get("CLIENT_LINKEDIN", "")
ONE_SENTENCE = get("ONE_SENTENCE", "")
DIFFERENTIATOR = get("DIFFERENTIATOR", "")

# ── Ideal Client (Section 2) ──────────────────────────────────────────────────
PERFECT_CLIENT = get("PERFECT_CLIENT", "")
CLIENT_PROBLEM = get("CLIENT_PROBLEM", "")
CLIENT_LANGUAGE = get("CLIENT_LANGUAGE", [])
TARGET_AUDIENCE = get("TARGET_AUDIENCE", "founders")
TARGET_GEOGRAPHY = get("TARGET_GEOGRAPHY", "")

# ── Voice (Section 3) ─────────────────────────────────────────────────────────
MESSAGE_EXAMPLES = get("MESSAGE_EXAMPLES", [])
POST_EXAMPLES = get("POST_EXAMPLES", [])
NEVER_USE = get("NEVER_USE", [])
ALWAYS_USE = get("ALWAYS_USE", [])
TONE = get("TONE", "Professional but human")
HUMOUR = get("HUMOUR", "Subtle")
GREETING_STYLE = get("GREETING_STYLE", "")
COMMENTING_PLAYBOOK = get("COMMENTING_PLAYBOOK", "") # Still used by zack_setup.py

# ── Goals (Section 4) ─────────────────────────────────────────────────────────
PRIMARY_GOAL = get("PRIMARY_GOAL", "")
CONVERSATIONS_PER_WEEK = get("CONVERSATIONS_PER_WEEK", "5–10")
FIRST_REPLY_LINE = get("FIRST_REPLY_LINE", "")
NEVER_DO = get("NEVER_DO", [])

# ── Technical (Section 5) ─────────────────────────────────────────────────────
EMAIL_ADDRESS = get("EMAIL_ADDRESS", "")
OPERATING_SYSTEM = get("OPERATING_SYSTEM", "Windows 10 or 11")
NOTES = get("NOTES", "")

# ── Sheet ─────────────────────────────────────────────────────────────────────
SHEET_ENGAGEMENT = get("SHEET_ENGAGEMENT", "Zacharia Engagement List")

# ── Commenting settings ───────────────────────────────────────────────────────
MAX_COMMENTS_PER_RUN = int(get("MAX_COMMENTS_PER_RUN", 25))
POST_RECENCY_HOURS = int(get("POST_RECENCY_HOURS", 72))

if not CONFIG_LOADED:
    print("⚠ zack_config.py not found in this folder.")
    print(" Run: python zack_setup.py")
    print(" This creates your personalised config file.")
