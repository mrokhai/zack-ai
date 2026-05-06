"""
Zack.ai — Config Loader
========================
All Zack scripts import this instead of hardcoding values.
Reads from zack_config.py automatically.
Falls back to defaults if config not found.
"""

import os
import random

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


# ── Core settings ─────────────────────────────────────────────────────────────
SPREADSHEET_ID          = get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_PATH = get("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
GROQ_API_KEY            = get("GROQ_API_KEY")
SENDGRID_API_KEY        = get("SENDGRID_API_KEY")
FROM_EMAIL              = get("FROM_EMAIL")
APPROVAL_EMAIL          = get("APPROVAL_EMAIL")
IMAP_HOST               = get("IMAP_HOST", "imap.gmail.com")
IMAP_USER               = get("IMAP_USER")
IMAP_PASS               = get("IMAP_PASS")

CLIENT_NAME             = get("CLIENT_NAME", "Zack")
CLIENT_FIRST_NAME       = get("CLIENT_FIRST_NAME", "")
CLIENT_COMPANY          = get("CLIENT_COMPANY", "")

SHEET_INBOX             = get("SHEET_INBOX", "Zacharia Inbox 2")
SHEET_CONNECTIONS       = get("SHEET_CONNECTIONS", "Zacharia Connections")
SHEET_ENGAGEMENT        = get("SHEET_ENGAGEMENT", "Zacharia Engagement")

MAX_MESSAGES_PER_DAY    = int(get("MAX_MESSAGES_PER_DAY", 20))
MAX_CONNECTIONS_PER_DAY = int(get("MAX_CONNECTIONS_PER_DAY", 15))
REIGNITE_AFTER_DAYS     = int(get("REIGNITE_AFTER_DAYS", 7))
SEARCH_QUERIES          = get("SEARCH_QUERIES", [])
AI_VOICE_DESCRIPTION    = get("AI_VOICE_DESCRIPTION", "")

TARGET_FOUNDERS         = get("TARGET_FOUNDERS", True)
TARGET_INVESTORS        = get("TARGET_INVESTORS", True)
TARGET_REGIONS          = get("TARGET_REGIONS", [])


# ── Message builder ───────────────────────────────────────────────────────────
# Reads templates from config and fills placeholders
def _fill(template, first="", company="", fund=""):
    return (template
            .replace("{first}", first)
            .replace("{company}", company or "your startup")
            .replace("{fund}", fund or "your fund"))


def get_message(template_key, first="", company="", fund=""):
    """
    Get a random message from the config templates.
    Falls back to built-in defaults if config not loaded.
    """
    templates = get(template_key, [])
    if templates:
        return _fill(random.choice(templates), first, company, fund)
    return None  # caller uses built-in fallback


if not CONFIG_LOADED:
    print("⚠️  zack_config.py not found — using default settings.")
    print("   Ask your Zack.ai setup team for your config file.")
