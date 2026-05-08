"""
Zacharia — Zack.ai Commenting Agent
=====================================
The most intelligent LinkedIn commenting agent available.

Comments on posts from your engagement list in your exact voice.
Learns when each person posts and shows up while the post is still fresh.
Never hallucinates — extracts real facts from each post before writing.

Run: python zacharia_engage.py

Sheet setup:
  Create a tab called 'Zacharia Engagement List':
  Column A: Name  |  Column B: LinkedIn URL  |  Column C: Notes
"""

import os, re, sys, time, random, hashlib, gspread, math
from datetime import datetime, timezone, timedelta
from groq import Groq
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── Load personalised config from zack_config.py ─────────────────────────────
try:
    import zack_loader as cfg
    GOOGLE_CREDENTIALS_PATH = cfg.GOOGLE_CREDENTIALS_PATH
    SPREADSHEET_ID          = cfg.SPREADSHEET_ID
    GROQ_API_KEY            = cfg.GROQ_API_KEY
    ENGAGEMENT_LIST_SHEET   = cfg.SHEET_ENGAGEMENT
    MAX_COMMENTS_PER_RUN    = cfg.MAX_COMMENTS_PER_RUN
    POST_RECENCY_HOURS      = cfg.POST_RECENCY_HOURS
    USER_PLAYBOOK           = cfg.COMMENTING_PLAYBOOK
    CLIENT_NAME             = cfg.CLIENT_NAME
    CLIENT_FIRST_NAME       = cfg.CLIENT_FIRST_NAME
except Exception as e:
    print(f"❌ Could not load zack_config.py: {e}")
    print("   Run: python zack_setup.py")
    sys.exit(1)

# ── Commenting thresholds ─────────────────────────────────────────────────────
POST_FRESH_MAX_HOURS        = 6    # 0-6hrs  = FRESH — comment first
POST_RECENT_MAX_HOURS       = 24   # 6-24hrs = RECENT — comment after fresh
                                   # 24+hrs  = STALE  — skip entirely
POST_WINDOW_HRS             = 2    # ±hrs around typical posting time
POST_WINDOW_MIN_CONFIDENCE  = 3    # data points needed before window filter activates

SLOW_MODE = True

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LIST_HEADERS = [
    "Name",              # A
    "LinkedIn URL",      # B
    "Notes",             # C
    "Last Post URL",     # D
    "Last Post ID",      # E
    "Last Comment",      # F
    "Last Comment Date", # G
    "Status",            # H
    "Typical Post Hour", # I
    "Post Confidence",   # J
    "Last Post Time",    # K
]


# ══════════════════════════════════════════════════════════════════════════════
# COMMENTING INTELLIGENCE — THE CORE OF ZACK
# ══════════════════════════════════════════════════════════════════════════════

BASE_PLAYBOOK = """You write LinkedIn comments that make people stop, read twice, and reply.

ANTI-HALLUCINATION RULE — MOST IMPORTANT:
You will be given EXTRACTED FACTS from the post.
Only reference things that appear in those facts or the post text.
Never invent numbers, events, or claims that are not in the post.
If you're not sure about a specific detail — leave it out.

READ THE POST TYPE FIRST:
FUNNY/LIGHT → match the energy, be wry/dry, never add a lesson to a joke
EMOTIONAL/PERSONAL → make them feel seen, specific and warm, no insight-dropping
INTELLECTUAL/NEW IDEA → add depth, sharpen the idea, show the flip side
HOW-TO/TACTICAL → validate what works, add one honest thing the post missed
ACHIEVEMENT/MILESTONE → short, genuine, reference the specific actual thing
OPINION/HOT TAKE → have a real view, sharpen their argument or show the edge case

PICK ONE MOVE:
A. Land the unsaid truth — say what they implied but didn't fully say
B. The flip — show the other side (not a fight, a reveal)
C. A lived moment — one tight specific real thing from experience (2 sentences max)
D. Dry observation — wry reframe, let it land without explaining it
E. Make them feel seen — reflect what made their post worth reading
F. Sharpen it — take their idea and make it more precise or more useful

FORMAT — NON-NEGOTIABLE:
Each thought gets its OWN line. Blank line between every line.

First short punchy line.

Second line that builds or lands.

Optional third line or question.

Max 3 lines. No paragraphs. No walls of text. Ever.
Questions only ~40% of the time — only for intellectual posts.

ABSOLUTE BANS — these instantly signal AI:
resonates / this landed / so true / great post / love this / powerful / inspiring
great post / thanks for sharing / well said / couldn't agree more / absolutely / 100%
unpacking / nuanced / framework / mindset / journey / game-changer / impactful
as a founder / as someone who / this is a reminder / what a... / ...thoughts?
Any corporate or motivational language

GUARDRAILS:
Grief/loss/medical: 1-2 warm human lines only — no lessons, no insights
Pure product promo: SKIP
Political: engage human/business angle only, never the politics
Nothing genuine to add: SKIP

OUTPUT: Write ONLY the comment. Blank line between each line.
If skipping: write exactly SKIP"""


def extract_post_facts(post_text):
    """
    Extract concrete grounding facts from the post BEFORE calling the AI.
    This is the anti-hallucination layer — the AI can only reference what's real.

    Returns a structured dict of facts found in the post.
    """
    facts = {
        "numbers":       [],   # any specific numbers, percentages, dollar amounts
        "quotes":        [],   # phrases in quotation marks
        "key_words":     [],   # repeated or emphasised words
        "first_line":    "",   # the hook/opening line
        "core_claim":    "",   # the central argument or point
        "has_story":     False,
        "has_list":      False,
        "word_count":    len(post_text.split()),
        "post_type_hint": "",
    }

    lines = [l.strip() for l in post_text.split('\n') if l.strip()]
    if lines:
        facts["first_line"] = lines[0][:150]

    # Extract numbers (including $, %, commas)
    numbers = re.findall(
        r'\$[\d,]+(?:\.\d+)?[KMBkm]?|'
        r'\d+(?:,\d{3})*(?:\.\d+)?%?(?:\s*(?:million|billion|thousand|k|m|b))?|'
        r'#\d+',
        post_text
    )
    facts["numbers"] = list(set(numbers))[:6]

    # Extract quoted phrases
    quotes = re.findall(r'["\u201c\u201d\u2018\u2019][^"\u201c\u201d\u2018\u2019]{5,80}["\u201c\u201d\u2018\u2019]', post_text)
    facts["quotes"] = quotes[:3]

    # Detect story presence
    story_markers = ["i was", "i remember", "last year", "last month",
                     "when i", "years ago", "i met", "i built", "i failed",
                     "we were", "that day", "the moment"]
    facts["has_story"] = any(m in post_text.lower() for m in story_markers)

    # Detect list
    facts["has_list"] = bool(re.search(r'^\d+[\.\)]\s', post_text, re.MULTILINE))

    # Post type hints
    t = post_text.lower()
    if any(w in t for w in ["😂", "lol", "haha", "funny", "joke", "irony"]):
        facts["post_type_hint"] = "FUNNY/LIGHT"
    elif any(w in t for w in ["lost", "grief", "died", "cancer", "struggle",
                               "difficult", "hard time", "broke down"]):
        facts["post_type_hint"] = "EMOTIONAL/PERSONAL"
    elif any(w in t for w in ["raised", "funding", "closed", "launched",
                               "hired", "promoted", "joined", "excited to share"]):
        facts["post_type_hint"] = "ACHIEVEMENT/MILESTONE"
    elif any(w in t for w in ["how to", "step 1", "tips:", "here's what",
                               "the secret", "the formula", "here's how"]):
        facts["post_type_hint"] = "HOW-TO/TACTICAL"
    elif facts["has_story"]:
        facts["post_type_hint"] = "EMOTIONAL/PERSONAL"

    # Core claim — usually the first or last complete sentence
    sentences = re.split(r'(?<=[.!?])\s+', post_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    if sentences:
        facts["core_claim"] = sentences[0][:200]

    return facts


def build_grounded_prompt(post_text, person_name, person_notes, facts):
    """
    Build an anti-hallucination prompt that gives the AI only real facts.
    Forces the comment to be grounded in what the post actually says.
    """
    # Build facts block — only include non-empty facts
    facts_block = []

    if facts["first_line"]:
        facts_block.append(f"Opening line: \"{facts['first_line']}\"")

    if facts["core_claim"] and facts["core_claim"] != facts["first_line"]:
        facts_block.append(f"Core claim/point: \"{facts['core_claim'][:150]}\"")

    if facts["numbers"]:
        facts_block.append(f"Specific numbers in post: {', '.join(facts['numbers'][:4])}")

    if facts["quotes"]:
        facts_block.append(f"Direct quotes from post: {' | '.join(facts['quotes'][:2])}")

    if facts["has_story"]:
        facts_block.append("Post contains: a personal story or lived experience")

    if facts["has_list"]:
        facts_block.append("Post contains: a numbered list")

    if facts["post_type_hint"]:
        facts_block.append(f"Post type detected: {facts['post_type_hint']}")

    facts_section = "\n".join(f"  • {f}" for f in facts_block)

    prompt = (
        f"Post by: {person_name}\n"
        f"About them: {person_notes if person_notes else 'not provided'}\n\n"

        f"GROUNDING FACTS (extracted from the post — only reference these):\n"
        f"{facts_section}\n\n"

        f"FULL POST:\n\"\"\"\n{post_text[:1800]}\n\"\"\"\n\n"

        f"INSTRUCTIONS:\n"
        f"1. Identify the post type: FUNNY/LIGHT | EMOTIONAL/PERSONAL | "
        f"INTELLECTUAL | HOW-TO | ACHIEVEMENT | OPINION\n"
        f"2. Pick one move: land the unsaid truth | flip it | lived moment | "
        f"dry observation | make them feel seen | sharpen it\n"
        f"3. Write the comment:\n"
        f"   - Reference ONLY specific things from the grounding facts above\n"
        f"   - Each thought on its own line with a blank line between\n"
        f"   - Max 3 lines. Short and punchy.\n"
        f"   - Do NOT start with 'I'\n"
        f"   - Questions only ~40%% of the time (intellectual posts only)\n"
        f"   - BANNED: resonates, landed, great post, so true, love this, "
        f"powerful, inspiring, absolutely, game-changer, as a founder\n"
        f"4. If nothing genuine to say: write SKIP\n\n"
        f"Write ONLY the comment. No preamble. No explanation."
    )

    return prompt


def _parse_retry_after(err_str):
    """Extract retry wait seconds from Groq 429 error."""
    m = re.search(r'try again in (\d+)m([\d.]+)s', err_str)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 5
    m = re.search(r'try again in ([\d.]+)s', err_str)
    if m:
        return float(m.group(1)) + 5
    return 60


def generate_comment(post_text, person_name, person_notes,
                     _model=None, _retries=0):
    """
    Generate a grounded, human, context-aware LinkedIn comment.

    Anti-hallucination: extracts real facts from the post first,
    then forces the AI to only reference those facts.
    Falls back from 70b to 8b if rate limited.
    """
    if _retries >= 3:
        return None

    model = _model or "llama-3.3-70b-versatile"

    try:
        client = Groq(api_key=GROQ_API_KEY)

        # Step 1: extract concrete facts — this is the hallucination guard
        facts = extract_post_facts(post_text)

        # Step 2: choose the right system prompt
        # Use the user's personalised playbook if available, else base playbook
        system_prompt = USER_PLAYBOOK if USER_PLAYBOOK.strip() else BASE_PLAYBOOK

        # Step 3: build a grounded user prompt with real extracted facts
        user_prompt = build_grounded_prompt(
            post_text, person_name, person_notes, facts
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.88,
            max_tokens=180,
        )

        comment = response.choices[0].message.content.strip().strip('"\'')

        if not comment or comment.upper().startswith("SKIP"):
            return None

        # Strip any leaked preamble (model sometimes outputs "Post type: X\n\n...")
        for prefix in ["STEP 1", "Post type:", "Type:", "FUNNY", "EMOTIONAL",
                        "INTELLECTUAL", "HOW-TO", "ACHIEVEMENT", "OPINION",
                        "Move:", "Grounding"]:
            if comment.startswith(prefix):
                parts = comment.split("\n\n", 1)
                if len(parts) > 1:
                    comment = parts[1].strip()

        # Quality guard — hard-banned AI phrases
        banned = [
            "resonates", "this landed", "so true", "great post",
            "thanks for sharing", "love this", "well said", "powerful",
            "inspiring", "couldn't agree more", "absolutely", "unpacking",
            "nuanced", "mindset", "journey", "impactful", "synergy",
            "ecosystem", "as a founder", "as someone", "what a ",
            "this is a reminder", "game-changer",
        ]
        if any(p in comment.lower() for p in banned):
            print(f"      Quality guard — regenerating")
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        # Format guard — enforce line-by-line if AI returned a paragraph
        if "\n\n" not in comment and len(comment.split(". ")) >= 2:
            sentences = [s.strip() for s in comment.replace(".\n", ". ").split(". ")
                         if s.strip()]
            formatted = []
            for s in sentences:
                if not s.endswith((".", "!", "?")):
                    s += "."
                formatted.append(s)
            comment = "\n\n".join(formatted)

        # Length guard
        words = comment.replace("\n", " ").split()
        if len(words) < 5 or len(words) > 90:
            print(f"      Length guard — regenerating")
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        return comment

    except Exception as e:
        err_str = str(e)

        if "429" in err_str or "rate_limit_exceeded" in err_str:
            wait_secs = _parse_retry_after(err_str)
            if "tokens per day" in err_str.lower() and wait_secs > 600:
                if model == "llama-3.3-70b-versatile":
                    print(f"      70b daily limit hit — switching to 8b model")
                    return generate_comment(post_text, person_name, person_notes,
                                            _model="llama-3.1-8b-instant",
                                            _retries=_retries)
                else:
                    print(f"      All models rate limited — skipping")
                    return None
            print(f"      Rate limited — waiting {wait_secs:.0f}s...")
            time.sleep(wait_secs)
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        print(f"      AI error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER
# ══════════════════════════════════════════════════════════════════════════════
def create_driver():
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--start-maximized")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=Service("chromedriver.exe"), options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(3)
    return driver


def is_driver_alive(driver):
    try:
        _ = driver.current_url
        return True
    except Exception:
        return False


def safe_get(driver, url):
    try:
        driver.get(url)
        return True
    except Exception as e:
        err = str(e).lower()
        if "timeout" in err or "timed out" in err:
            try:
                driver.execute_script("window.stop();")
                time.sleep(1)
                return True
            except Exception:
                return False
        if any(x in err for x in [
            "connectionreset", "10054", "connection aborted",
            "remotedisconnected", "invalid session", "no such window",
        ]):
            raise
        return False


def pause(a=2.0, b=5.0):
    time.sleep(random.uniform(a, b) if SLOW_MODE else random.uniform(0.5, 1.5))


def wait_for_login(driver, silent=False):
    try:
        driver.set_page_load_timeout(90)
        safe_get(driver, "https://www.linkedin.com")
        driver.set_page_load_timeout(60)
    except Exception:
        pass
    time.sleep(4)

    def _logged_in():
        try:
            url = driver.current_url
            if "feed" in url or "mynetwork" in url:
                return True
            if driver.find_elements(By.CSS_SELECTOR, ".global-nav__me"):
                return True
            return False
        except Exception:
            return False

    if _logged_in():
        if not silent:
            print("   Already logged in!")
        return True

    if not silent:
        print("\n" + "="*55)
        print("ACTION: Log into LinkedIn in the Chrome window.")
        print("Zacharia will continue automatically once detected.")
        print("="*55)

    for _ in range(72):
        time.sleep(5)
        if _logged_in():
            if not silent:
                print("   Logged in — continuing...")
            return True

    if not silent:
        print("   Timed out waiting for login — stopping.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════
def connect_sheets(max_retries=5):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            creds  = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
            client = gspread.authorize(creds)
            wb     = client.open_by_key(SPREADSHEET_ID)

            try:
                ws = wb.worksheet(ENGAGEMENT_LIST_SHEET)
                print(f"   Using sheet: '{ENGAGEMENT_LIST_SHEET}'")

                # Expand to 12 columns if needed (handles older sheets)
                try:
                    props = ws.spreadsheet.fetch_sheet_metadata()
                    for s in props.get('sheets', []):
                        if s['properties']['title'] == ENGAGEMENT_LIST_SHEET:
                            current_cols = s['properties']['gridProperties']['columnCount']
                            if current_cols < 12:
                                ws.spreadsheet.batch_update({"requests": [{
                                    "appendDimension": {
                                        "sheetId":   ws.id,
                                        "dimension": "COLUMNS",
                                        "length":    12 - current_cols
                                    }
                                }]})
                                for ci, h in enumerate(LIST_HEADERS, 1):
                                    try:
                                        if not ws.cell(1, ci).value:
                                            ws.update_cell(1, ci, h)
                                    except Exception:
                                        pass
                except Exception:
                    pass

            except Exception:
                ws = wb.add_worksheet(
                    title=ENGAGEMENT_LIST_SHEET, rows=500, cols=12)
                ws.append_row(LIST_HEADERS)
                ws.format("A1:K1", {
                    "textFormat": {"bold": True,
                                   "foregroundColor": {"red":1,"green":1,"blue":1}},
                    "backgroundColor": {"red":0.04,"green":0.06,"blue":0.18}
                })
                ws.freeze(rows=1)
                print(f"   Created sheet: '{ENGAGEMENT_LIST_SHEET}'")
                print("   Add people: A=Name | B=LinkedIn URL | C=Notes")

            return ws

        except Exception as e:
            last_err = e
            retryable = any(x in str(e) for x in [
                "10054","ConnectionReset","Connection aborted",
                "TransportError","ssl","SSL","timed out","RemoteDisconnected",
            ])
            if retryable and attempt < max_retries:
                wait = 3 * attempt
                print(f"   ⚠️  Sheets retry {attempt}/{max_retries} in {wait}s...")
                time.sleep(wait)
                continue
            break
    raise RuntimeError(f"Cannot connect to Google Sheets: {last_err}")


def load_engagement_list(ws):
    try:
        all_rows = ws.get_all_values()
        if not all_rows:
            return []
        people = []
        for i, row in enumerate(all_rows[1:], start=2):
            row = row + [""] * 12
            name = (row[0] or "").strip()
            url  = (row[1] or "").strip().rstrip("/")
            if not name or not url or "/in/" not in url:
                continue
            try:
                typical_hour = int(row[8]) if row[8].strip() else None
            except (ValueError, TypeError):
                typical_hour = None
            try:
                confidence = int(row[9]) if row[9].strip() else 0
            except (ValueError, TypeError):
                confidence = 0
            people.append({
                "row":            i,
                "name":           name,
                "url":            url,
                "notes":          (row[2] or "").strip(),
                "last_post_url":  (row[3] or "").strip(),
                "last_post_id":   (row[4] or "").strip(),
                "last_comment":   (row[5] or "").strip(),
                "last_date":      (row[6] or "").strip(),
                "status":         (row[7] or "").strip(),
                "typical_hour":   typical_hour,
                "confidence":     confidence,
                "last_post_time": (row[10] or "").strip(),
            })
        return people
    except Exception as e:
        print(f"   Load error: {e}")
        return []


def update_row(ws, row_num, post_url, post_id, comment, status):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        ws.update_cell(row_num, 4, post_url)
        ws.update_cell(row_num, 5, post_id)
        ws.update_cell(row_num, 6, comment[:300] if comment else "")
        ws.update_cell(row_num, 7, today)
        ws.update_cell(row_num, 8, status)
    except Exception as e:
        print(f"      Sheet update error: {e}")


def update_post_timing(ws, row_num, post_hour_utc, current_confidence,
                       post_datetime_str):
    try:
        new_confidence = current_confidence + 1
        current_hour_val = ws.cell(row_num, 9).value or ""
        try:
            current_hour = int(current_hour_val)
        except (ValueError, TypeError):
            current_hour = None

        if current_hour is None:
            new_typical_hour = post_hour_utc
        else:
            w_old = current_confidence
            w_new = 2
            w_tot = w_old + w_new
            a_old = current_hour   * (2 * math.pi / 24)
            a_new = post_hour_utc  * (2 * math.pi / 24)
            sin_a = (math.sin(a_old) * w_old + math.sin(a_new) * w_new) / w_tot
            cos_a = (math.cos(a_old) * w_old + math.cos(a_new) * w_new) / w_tot
            angle = math.atan2(sin_a, cos_a)
            new_typical_hour = int((angle * 24 / (2 * math.pi)) % 24)

        ws.update_cell(row_num, 9,  str(new_typical_hour))
        ws.update_cell(row_num, 10, str(new_confidence))
        ws.update_cell(row_num, 11, post_datetime_str)
    except Exception as e:
        print(f"      Timing update error: {e}")


def is_in_active_window(person, current_hour_utc,
                         window_hrs=POST_WINDOW_HRS,
                         min_confidence=POST_WINDOW_MIN_CONFIDENCE):
    confidence   = person.get("confidence", 0)
    typical_hour = person.get("typical_hour")
    if confidence < min_confidence or typical_hour is None:
        return True, f"learning ({confidence}/{min_confidence} data points)"
    diff = min(abs(current_hour_utc - typical_hour), 24 - abs(current_hour_utc - typical_hour))
    if diff <= window_hrs:
        return True, f"in window (posts ~{typical_hour:02d}:xx UTC)"
    open_h  = (typical_hour - window_hrs) % 24
    close_h = (typical_hour + window_hrs) % 24
    return False, f"outside window (posts ~{typical_hour:02d}:xx — window {open_h:02d}–{close_h:02d} UTC)"


def extract_post_hour(post):
    now       = datetime.now(timezone.utc)
    post_time = now - timedelta(hours=post["age_hours"])
    return post_time.hour, post_time.strftime("%Y-%m-%d %H:%M")


# ══════════════════════════════════════════════════════════════════════════════
# POST SCRAPING
# ══════════════════════════════════════════════════════════════════════════════
def _estimate_age_hours(ts):
    """Calculate post age from timestamp. Returns float hours."""
    if not ts:
        return 1.0

    ts = ts.strip()

    # ISO datetime (most accurate — from time[datetime] attribute)
    if 'T' in ts and len(ts) > 15:
        try:
            ts_clean = re.sub(r'\.\d+', '', ts.replace('Z', '+00:00'))
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            return max(0, age)
        except Exception:
            pass

    # dateutil fallback for other ISO formats
    try:
        from dateutil import parser as dp
        dt = dp.parse(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return max(0, age)
    except Exception:
        pass

    # Relative strings: "2h", "3d", "just now", "yesterday"
    t = ts.lower().strip()
    if any(x in t for x in ["just now", "now", "moment", "second"]):
        return 0.1
    if "today" in t:
        return 1.0
    if "yesterday" in t:
        return 26.0
    m = re.search(r"(\d+)\s*(s|sec|m|min|h|hr|hour|d|day|w|week)", t)
    if m:
        v, u = int(m.group(1)), m.group(2)[0]
        if u == 's': return 0.01
        if u == 'm': return v / 60
        if u == 'h': return float(v)
        if u == 'd': return float(v * 24)
        if u == 'w': return float(v * 168)

    # Can't parse — treat as recent (4hrs) so we don't skip valid posts
    return 4.0


def get_latest_post(driver, profile_url):
    """
    Visit the person's activity page and get their latest post.
    Returns dict with text, url, post_id, age_hours — or None.
    """
    try:
        username     = profile_url.rstrip("/").split("/in/")[-1].split("/")[0].split("?")[0]
        activity_url = f"https://www.linkedin.com/in/{username}/recent-activity/all/"
        if not safe_get(driver, activity_url):
            return None
        pause(4, 6)

        # Scroll to trigger lazy-load
        for _ in range(4):
            driver.execute_script("window.scrollBy(0, 700);")
            time.sleep(1.2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        posts = driver.execute_script("""
            var results = [];
            var containers = document.querySelectorAll(
                '.feed-shared-update-v2, .occludable-update'
            );
            for (var i = 0; i < Math.min(containers.length, 8); i++) {
                var el = containers[i];

                // Get post text
                var textEl = (
                    el.querySelector('.feed-shared-update-v2__description .update-components-text') ||
                    el.querySelector('.update-components-text') ||
                    el.querySelector('.feed-shared-text span[dir="ltr"]') ||
                    el.querySelector('.feed-shared-text') ||
                    el.querySelector('.attributed-text-segment-list__content') ||
                    el.querySelector('[data-test-id="main-feed-activity-card__commentary"]') ||
                    el.querySelector('.break-words span[dir="ltr"]')
                );
                var text = textEl ? textEl.innerText.trim() : '';
                if (!text || text.length < 80) continue;
                if (text.split(' ').length < 10) continue;

                // Get timestamp — ISO datetime attribute is most accurate
                var ts = '';
                var timeEl = el.querySelector('time[datetime]');
                if (timeEl) {
                    ts = timeEl.getAttribute('datetime') || '';
                }
                if (!ts) {
                    var allTimes = el.querySelectorAll('time');
                    for (var t = 0; t < allTimes.length; t++) {
                        var dt = allTimes[t].getAttribute('datetime');
                        if (dt && dt.indexOf('T') > 0) { ts = dt; break; }
                        if (!ts) ts = allTimes[t].innerText || '';
                    }
                }

                // Get post URL
                var url = '';
                var linkEl = (
                    el.querySelector('a[href*="/feed/update/"]') ||
                    el.querySelector('a[href*="activity"]') ||
                    el.querySelector('a[href*="ugcPost"]') ||
                    el.querySelector('a[href*="share"]')
                );
                if (linkEl) url = linkEl.href;

                results.push({text: text, ts: ts, url: url});
            }

            // Strategy 2 fallback: find substantial text blocks
            if (results.length === 0) {
                var spans = document.querySelectorAll('span[dir="ltr"]');
                for (var j = 0; j < spans.length; j++) {
                    var t = spans[j].innerText.trim();
                    if (t.length > 120 && t.split(' ').length > 15) {
                        results.push({text: t, ts: '', url: ''});
                        if (results.length >= 3) break;
                    }
                }
            }
            return results;
        """) or []

        if not posts:
            return None

        post = posts[0]
        text = post.get("text", "").strip()
        url  = post.get("url", "") or activity_url
        ts   = post.get("ts", "")

        if not text or len(text) < 80:
            return None

        # Strip leading name echo (LinkedIn sometimes prepends "Name\nName\n")
        lines = text.split("\n")
        if len(lines) >= 3 and lines[0].strip() == lines[1].strip():
            text = "\n".join(lines[2:]).strip()
        if len(text) < 40:
            return None

        age_hours = _estimate_age_hours(ts)
        if age_hours > POST_RECENCY_HOURS:
            return None

        post_id = hashlib.md5(f"{username}:{text[:120]}".encode()).hexdigest()[:16]

        return {
            "text":      text[:2500],
            "url":       url,
            "post_id":   post_id,
            "age_hours": age_hours,
        }

    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["connectionreset","10054","invalid session","no such window"]):
            raise
        print(f"      Post fetch error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# COMMENT POSTING
# ══════════════════════════════════════════════════════════════════════════════
def _find_comment_box(driver, timeout=6):
    SELECTORS = [
        "div[data-placeholder='Add a comment…'][contenteditable='true']",
        "div[aria-placeholder='Add a comment…'][contenteditable='true']",
        ".ql-editor[contenteditable='true']",
        ".comments-comment-box .ql-editor",
        ".comments-comment-texteditor .ql-editor",
        "div[role='textbox'][aria-label*='comment']",
        "div[role='textbox'][aria-label*='Comment']",
        "div[contenteditable='true']",
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in SELECTORS:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed() and el.is_enabled():
                        return el
            except Exception:
                continue
        time.sleep(0.5)
    return None


def _click_comment_trigger(driver):
    for sel in ["button[aria-label='Comment']", "button[aria-label='comment']",
                "button[aria-label*='Add a comment']"]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed():
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.4)
                    driver.execute_script("arguments[0].click();", btn)
                    return True
        except Exception:
            continue

    clicked = driver.execute_script("""
        var bar = document.querySelector(
            '.social-actions, .feed-shared-social-action-bar, .social-action-bar'
        );
        var scope = bar || document;
        var btns = Array.from(scope.querySelectorAll('button'));
        for (var b of btns) {
            var lbl = (b.getAttribute('aria-label') || '').toLowerCase();
            var txt = (b.innerText || '').trim();
            if (lbl.includes('comment') || txt === 'Comment') {
                b.click(); return true;
            }
        }
        return false;
    """)
    return bool(clicked)


def _type_into_box(driver, comment_text):
    box = _find_comment_box(driver, timeout=8)
    if not box:
        return False
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", box)
        time.sleep(0.7)
        segments = comment_text.split("\n")
        for idx, segment in enumerate(segments):
            if segment:
                for chunk in [segment[i:i+40] for i in range(0, len(segment), 40)]:
                    box.send_keys(chunk)
                    time.sleep(random.uniform(0.07, 0.18))
            if idx < len(segments) - 1:
                ActionChains(driver).key_down(Keys.SHIFT).send_keys(
                    Keys.RETURN).key_up(Keys.SHIFT).perform()
                time.sleep(0.15)
        return True
    except Exception as e:
        print(f"      Type error: {e}")
        try:
            box2 = _find_comment_box(driver, timeout=4)
            if box2:
                driver.execute_script("arguments[0].click();", box2)
                time.sleep(0.5)
                box2.send_keys(comment_text)
                return True
        except Exception:
            pass
        return False


def _submit_comment(driver):
    for sel in [
        "button.comments-comment-box__submit-button",
        "button.comments-comment-texteditor__submitButton",
        ".comments-comment-box button[type='submit']",
        ".comments-comment-texteditor button[type='submit']",
        "form button[type='submit']",
    ]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    return True
        except Exception:
            continue

    submitted = driver.execute_script("""
        var form = (
            document.querySelector('.comments-comment-box') ||
            document.querySelector('.comments-comment-texteditor') ||
            document.body
        );
        var btns = Array.from(form.querySelectorAll('button'));
        for (var i = 0; i < btns.length; i++) {
            var b   = btns[i];
            var lbl = (b.getAttribute('aria-label') || '').toLowerCase().trim();
            var txt = (b.innerText || '').toLowerCase().trim();
            if (b.disabled) continue;
            if (txt==='comment'||txt==='post'||txt==='post comment'||
                lbl==='comment'||lbl==='post comment'||lbl==='add comment') {
                b.click(); return 'clicked:' + txt;
            }
        }
        var primary = form.querySelector('button.artdeco-button--primary:not([disabled])');
        if (primary) { primary.click(); return 'primary-btn'; }
        return null;
    """)
    if submitted:
        return True

    try:
        ActionChains(driver).key_down(Keys.CONTROL).send_keys(
            Keys.RETURN).key_up(Keys.CONTROL).perform()
        time.sleep(0.5)
        return True
    except Exception:
        pass
    return False


def post_comment(driver, post_url, comment_text):
    try:
        if not safe_get(driver, post_url):
            return False
        pause(3, 5)
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(1.5)

        print(f"      → Opening comment editor...")
        clicked = _click_comment_trigger(driver)
        if not clicked:
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1)
            clicked = _click_comment_trigger(driver)
        if not clicked and not _find_comment_box(driver, timeout=3):
            print(f"      Comment trigger not found")
            return False

        time.sleep(2.5)

        print(f"      → Typing comment...")
        if not _type_into_box(driver, comment_text):
            print(f"      Could not type into comment box")
            return False

        pause(2.0, 3.0)   # let LinkedIn's React activate the Post button

        print(f"      → Posting comment...")
        submitted = _submit_comment(driver)
        if not submitted:
            try:
                ActionChains(driver).key_down(Keys.CONTROL).send_keys(
                    Keys.RETURN).key_up(Keys.CONTROL).perform()
                submitted = True
            except Exception:
                pass

        time.sleep(3.5)
        return bool(submitted)

    except Exception as e:
        print(f"      Post comment error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL COLOURS
# ══════════════════════════════════════════════════════════════════════════════
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    def GREEN(t):  return Fore.GREEN  + str(t) + Style.RESET_ALL
    def YELLOW(t): return Fore.YELLOW + str(t) + Style.RESET_ALL
    def DIM(t):    return Style.DIM   + str(t) + Style.RESET_ALL
except Exception:
    def GREEN(t):  return str(t)
    def YELLOW(t): return str(t)
    def DIM(t):    return str(t)


def _age_label(hours):
    if hours < 1:         return GREEN("just now  🔥")
    if hours < POST_FRESH_MAX_HOURS:  return GREEN(f"{hours:.0f}hrs ago  🔥 FRESH")
    if hours < POST_RECENT_MAX_HOURS: return YELLOW(f"{hours:.0f}hrs ago  ⏱ RECENT")
    return DIM(f"{hours:.0f}hrs ago  — stale")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def run():
    now_utc = datetime.now(timezone.utc)
    name_display = CLIENT_FIRST_NAME or CLIENT_NAME or "Zack User"

    print(f"\n{'='*55}")
    print(f"Zack.ai — LinkedIn Commenting Agent")
    print(f"Running for: {name_display}")
    print(f"{now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Max comments: {MAX_COMMENTS_PER_RUN} | "
          f"Fresh: {POST_FRESH_MAX_HOURS}hrs | "
          f"Recent: {POST_RECENT_MAX_HOURS}hrs")
    print(f"{'='*55}\n")

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in zack_config.py")
        print("   Run python zack_setup.py to reconfigure")
        return

    print("📊 Connecting to sheets...")
    ws = connect_sheets()

    people = load_engagement_list(ws)
    if not people:
        print(f"\n   No people in '{ENGAGEMENT_LIST_SHEET}'.")
        print("   Add: Column A=Name | Column B=LinkedIn URL | Column C=Notes")
        return
    print(f"   Engagement list: {len(people)} people\n")

    random.shuffle(people)

    driver    = create_driver()
    commented = 0
    no_post   = 0
    already   = 0
    skipped   = 0
    stale     = 0

    try:
        if not wait_for_login(driver):
            print("❌ Could not log into LinkedIn — stopping")
            return

        # ── Window filter: only visit people likely posting right now ──────────
        current_hour = now_utc.hour

        to_visit    = []
        win_skipped = []
        for p in people:
            visit, reason = is_in_active_window(p, current_hour)
            if visit:
                to_visit.append(p)
            else:
                win_skipped.append((p["name"], reason))

        print(f"\n🕐 Current time: {current_hour:02d}:xx UTC")
        print(f"   In active window: {len(to_visit)}")
        print(f"   Outside window:   {len(win_skipped)} (skipping — not their posting time)")
        if win_skipped:
            for name, reason in win_skipped[:4]:
                print(f"     • {name} — {reason}")
            if len(win_skipped) > 4:
                print(f"     ... and {len(win_skipped)-4} more")

        # ── Pass 1: Scan profiles and classify by post age ────────────────────
        fresh_queue = []
        deferred    = []

        print(f"\n📋 Pass 1 — Scanning {len(to_visit)} profiles...\n")
        print("─" * 55)

        for person in to_visit:
            name  = person["name"]
            url   = person["url"]
            notes = person["notes"]

            print(f"\n   {name}")

            # Browser health check
            if not is_driver_alive(driver):
                print(f"   ⚠️  Browser crashed — restarting...")
                try: driver.quit()
                except Exception: pass
                time.sleep(3)
                driver = create_driver()
                if not wait_for_login(driver):
                    print("   ❌ Login timed out — stopping")
                    break

            print(f"   → Checking post...")
            try:
                post = get_latest_post(driver, url)
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["10054","connectionreset","invalid session","no such window","connection aborted"]):
                    print(f"   ⚠️  Browser crashed — restarting...")
                    try: driver.quit()
                    except Exception: pass
                    time.sleep(4)
                    driver = create_driver()
                    wait_for_login(driver)
                else:
                    print(f"   → Error: {e} — skipping")
                no_post += 1
                pause(2, 4)
                continue

            if not post:
                print(f"   → No post in last {POST_RECENCY_HOURS}hrs — skipping")
                update_row(ws, person["row"], "", "", "", "no_recent_post")
                no_post += 1
                pause(2, 4)
                continue

            age_h   = post["age_hours"]
            post_id = post["post_id"]

            # Record timing data every time we see a post
            post_hour, post_dt_str = extract_post_hour(post)
            update_post_timing(ws, person["row"], post_hour,
                               person.get("confidence", 0), post_dt_str)

            if post_id == person["last_post_id"]:
                print(f"   → Already commented on this post — skipping")
                already += 1
                pause(1, 2)
                continue

            word_count = len(post["text"].split())
            print(f"   → Post: {word_count} words | {_age_label(age_h)}")
            print(f"   → Preview: '{post['text'][:100]}...'")

            entry = {"person": person, "post": post, "age_h": age_h}

            if age_h <= POST_FRESH_MAX_HOURS:
                fresh_queue.append(entry)
                print(f"   → Queued as FRESH")
            elif age_h <= POST_RECENT_MAX_HOURS:
                deferred.append(entry)
                print(f"   → Queued as RECENT")
            else:
                print(f"   → Post is {age_h:.0f}hrs old — too stale, skipping")
                stale += 1
                update_row(ws, person["row"], post["url"], post_id, "", "stale_skipped")

            pause(2, 4)

        # Sort: freshest first within each queue
        fresh_queue.sort(key=lambda x: x["age_h"])
        deferred.sort(key=lambda x: x["age_h"])

        total_to_comment = len(fresh_queue) + len(deferred)
        print(f"\n{'='*55}")
        print(f"📊 SCAN COMPLETE")
        print(f"   🔥 Fresh (0-{POST_FRESH_MAX_HOURS}hrs):   {len(fresh_queue)}")
        print(f"   ⏱  Recent ({POST_FRESH_MAX_HOURS}-{POST_RECENT_MAX_HOURS}hrs): {len(deferred)}")
        print(f"   ⏭  Stale / no post:   {stale + no_post}")
        print(f"   📝 Will comment on:   {min(total_to_comment, MAX_COMMENTS_PER_RUN)}")
        print(f"{'='*55}")

        # ── Pass 2: Comment — fresh first, then recent ─────────────────────────
        def comment_on(entry, label):
            nonlocal commented, skipped
            if commented >= MAX_COMMENTS_PER_RUN:
                return False
            if not is_driver_alive(driver):
                return False

            person  = entry["person"]
            post    = entry["post"]
            age_h   = entry["age_h"]

            print(f"\n   {person['name']}  [{label} — {age_h:.0f}hrs ago]")

            print(f"   → Generating comment...")
            comment = generate_comment(
                post["text"], person["name"], person.get("notes", "")
            )

            if not comment:
                print(f"   → Post not suitable for comment — skipping")
                update_row(ws, person["row"], post["url"], post["post_id"],
                           "", "skipped_unsuitable")
                skipped += 1
                pause(2, 4)
                return True

            print(f"   → Comment: '{comment[:80]}...'")
            print(f"   → Posting...")

            try:
                success = post_comment(driver, post["url"], comment)
            except Exception as e:
                print(f"   → Post error: {e}")
                success = False

            if success:
                commented += 1
                update_row(ws, person["row"], post["url"], post["post_id"],
                           comment, "commented")
                print(f"   ✅ Posted ({commented}/{MAX_COMMENTS_PER_RUN})")
            else:
                print(f"   ❌ Failed")
                update_row(ws, person["row"], post["url"], post["post_id"],
                           comment, "post_failed")

            pause(12, 20)
            return True

        if fresh_queue:
            print(f"\n\n🔥 Commenting on FRESH posts (0-{POST_FRESH_MAX_HOURS}hrs)...")
            print("─" * 55)
            for entry in fresh_queue:
                if commented >= MAX_COMMENTS_PER_RUN:
                    break
                comment_on(entry, "🔥 FRESH")
        else:
            print(f"\n   No fresh posts this run.")

        if deferred and commented < MAX_COMMENTS_PER_RUN:
            print(f"\n\n⏱  Commenting on RECENT posts ({POST_FRESH_MAX_HOURS}-{POST_RECENT_MAX_HOURS}hrs)...")
            print("─" * 55)
            for entry in deferred:
                if commented >= MAX_COMMENTS_PER_RUN:
                    break
                comment_on(entry, "⏱ RECENT")
        elif deferred:
            print(f"\n   Limit reached — {len(deferred)} recent post(s) held for next run.")

        # ── Summary ────────────────────────────────────────────────────────────
        print(f"\n{'='*55}")
        print(f"✅ RUN COMPLETE")
        print(f"   Comments posted:    {commented}")
        print(f"   Fresh posts:        {len(fresh_queue)}")
        print(f"   Recent posts:       {len(deferred)}")
        print(f"   Stale/skipped:      {stale}")
        print(f"   No post found:      {no_post}")
        print(f"   Already commented:  {already}")
        print(f"   Unsuitable:         {skipped}")
        print(f"{'='*55}\n")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print("Browser closed.")


if __name__ == "__main__":
    run()
ENDSCRIPT

python3 -c "import ast; ast.parse(open('/home/claude/zacharia_engage_new.py').read()); print('✅ syntax OK')"
Output

✅ syntax OK
