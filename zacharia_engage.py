"""
Zacharia — Zack.ai Commenting Agent
=====================================
The most intelligent LinkedIn commenting agent available.

Comments on posts from your engagement list in your exact voice.
Learns when each person posts and shows up while the post is still fresh.
Never hallucinates — extracts real facts from each post before writing.


Sheet setup:
  Create a tab called 'Zacharia Engagement List':
  Column A: Name  |  Column B: LinkedIn URL  |  Column C: Notes

WHAT'S NEW FROM v3:
    - Single-pass: visit profile → comment immediately → next. No queue, no second pass
    - Window filter runs BEFORE browser opens - no wasted visits
    - Skip-today filter: if already commented today, skip entirely
    - Sort: high-confidence known posters first - catch them while fresh
    - 35 comments per run default
    - On re-run: picks up where it left off — only unvisited profiles in window

Run: python zacharia_engage_user_v4.py

Setup: Make sure zack_config.py exists with your keys. Run python zack_setup.py first.
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
    SPREADSHEET_ID = cfg.SPREADSHEET_ID
    GROQ_API_KEY = cfg.GROQ_API_KEY
    ENGAGEMENT_LIST_SHEET = cfg.SHEET_ENGAGEMENT
    MAX_COMMENTS_PER_RUN = cfg.MAX_COMMENTS_PER_RUN
    POST_RECENCY_HOURS = cfg.POST_RECENCY_HOURS
    USER_PLAYBOOK = cfg.COMMENTING_PLAYBOOK
    CLIENT_NAME = cfg.CLIENT_NAME
    CLIENT_FIRST_NAME = cfg.CLIENT_FIRST_NAME
except Exception as e:
    print(f"❌ Could not load zack_config.py: {e}")
    print(" Run: python zack_setup.py")
    sys.exit(1)

# ── Commenting thresholds ─────────────────────────────────────────────────────
POST_FRESH_MAX_HOURS = 6 # 0-6hrs = FRESH — comment first
POST_RECENT_MAX_HOURS = 24 # 6-24hrs = RECENT — comment after fresh
                                   # 24+hrs = STALE — skip entirely
POST_WINDOW_HRS = 6 # ±hrs around typical posting time
POST_WINDOW_MIN_CONFIDENCE = 5 # data points needed before window filter activates

SLOW_MODE = True

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LIST_HEADERS = [
    "Name", # A
    "LinkedIn URL", # B
    "Notes", # C
    "Last Post URL", # D
    "Last Post ID", # E
    "Last Comment", # F
    "Last Comment Date", # G
    "Status", # H
    "Typical Post Hour", # I
    "Post Confidence", # J
    "Last Post Time", # K
]

# ══════════════════════════════════════════════════════════════════════════════
# COMMENTING INTELLIGENCE — ANTI-HALLUCINATION LAYER
# ══════════════════════════════════════════════════════════════════════════════

BASE_PLAYBOOK = """You write LinkedIn comments that sound like a smart friend texting after reading the post.

ANTI-HALLUCINATION — MOST IMPORTANT:
You will be given EXTRACTED FACTS from the post.
Only reference things that appear in those facts or the post text.
Never invent numbers, events, or claims not in the post.

CONTEXT RULE — DO NOT SKIP:
Every comment MUST reference at least one specific detail from the post:
- a number they mentioned
- a phrase from their opening line
- the core claim they made
- a name or company they referenced
If you cannot find something specific to reference, output SKIP.

VOICE:
- Talk like a human, not a coach. Use contractions, short sentences.
- Be fun first. Light sarcasm is good. Dry observations land better than praise.
- 95% of comments are statements. Questions only 5% of the time.
- Make them feel seen by naming the specific thing they wrote.

EXAMPLES OF GOOD (with context):
"This is the part everyone pretends is easy"
"Of course the 90 days worked, you actually showed up"
"That's a brutal lesson to learn after raising $2M"

EXAMPLES OF BAD (no context):
"This resonates deeply" / "So true" / "Great insights"

READ THE POST TYPE:
FUNNY/LIGHT → match the joke, reference the specific funny bit
PERSONAL → name what hit you specifically, 1-2 warm lines
IDEA → sharpen their specific claim, use their words
HOW-TO → reference their specific step, add what they missed
WIN → congratulate the actual achievement they named
EMOTIONAL → make them feel seen, specific and warm, no insight-dropping

PICK ONE MOVE:
A. Land the unsaid truth — say what they implied but didn't fully say
B. The flip — show the other side (not a fight, a reveal)
C. A lived moment — one tight specific real thing from experience (2 sentences max)
D. Dry observation — wry reframe, let it land without explaining it
E. Make them feel seen — reflect what made their post worth reading
F. Sharpen it — take their idea and make it more precise or more useful

FORMAT:
Line 1: short punchy reaction referencing their post
[blank line]
Line 2: specific observation using their detail
[blank line]
Line 3: optional

Each line must end with a period, exclamation, or question mark.
Max 3 lines. Never a paragraph.
Only use a QUESTION for moves A, B, or F — and only when the post is intellectual
or when the question will genuinely open the conversation further.

BANNED PHRASES:
resonates / this landed / so true / great post / thanks for sharing
love this / well said / powerful / inspiring / couldn't agree more
absolutely / unpacking / nuanced / framework / mindset / journey
impactful / synergy / ecosystem / as a founder / game-changer / thoughts?

GUARDRAILS:
- Grief/loss/medical: 1-2 warm human lines only — no insight, no lesson
- Purely promotional: SKIP
- Political: engage the human/business angle only, never the politics
- Nothing genuine to add: SKIP

OUTPUT: comment only, or SKIP"""

def extract_post_facts(post_text):
    facts = {
        "numbers": [],
        "quotes": [],
        "first_line": "",
        "core_claim": "",
        "has_story": False,
        "has_list": False,
        "word_count": len(post_text.split()),
        "post_type_hint": "",
    }
    lines = [l.strip() for l in post_text.split('\n') if l.strip()]
    if lines:
        facts["first_line"] = lines[0][:150]

    numbers = re.findall(
        r'\$[\d,]+(?:\.\d+)?[KMBkm]?|'
        r'\d+(?:,\d{3})*(?:\.\d+)?%?(?:\s*(?:million|billion|thousand|k|m|b))?|'
        r'#\d+',
        post_text
    )
    facts["numbers"] = list(set(numbers))[:6]

    quotes = re.findall(r'["\u201c\u201d][^"\u201c\u201d]{5,80}["\u201c\u201d]', post_text)
    facts["quotes"] = quotes[:3]

    story_markers = ["i was", "i remember", "last year", "last month",
                     "when i", "years ago", "i met", "i built", "i failed"]
    facts["has_story"] = any(m in post_text.lower() for m in story_markers)
    facts["has_list"] = bool(re.search(r'^\d+[\.\)]\s', post_text, re.MULTILINE))

    t = post_text.lower()
    if any(w in t for w in ["😂", "lol", "haha", "funny", "joke"]):
        facts["post_type_hint"] = "FUNNY/LIGHT"
    elif any(w in t for w in ["lost", "grief", "died", "cancer", "struggle", "difficult"]):
        facts["post_type_hint"] = "EMOTIONAL/PERSONAL"
    elif any(w in t for w in ["raised", "funding", "closed", "launched", "hired", "excited to share"]):
        facts["post_type_hint"] = "ACHIEVEMENT/MILESTONE"
    elif any(w in t for w in ["how to", "step 1", "tips:", "here's what", "the secret"]):
        facts["post_type_hint"] = "HOW-TO/TACTICAL"
    elif facts["has_story"]:
        facts["post_type_hint"] = "EMOTIONAL/PERSONAL"

    sentences = re.split(r'(?<=[.!?])\s+', post_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    if sentences:
        facts["core_claim"] = sentences[0][:200]

    return facts

def build_grounded_prompt(post_text, person_name, person_notes, facts):
    facts_block = []
    if facts["first_line"]:
        facts_block.append(f"Opening line: \"{facts['first_line']}\"")
    if facts["core_claim"] and facts["core_claim"]!= facts["first_line"]:
        facts_block.append(f"Core claim: \"{facts['core_claim'][:150]}\"")
    if facts["numbers"]:
        facts_block.append(f"Numbers in post: {', '.join(facts['numbers'][:4])}")
    if facts["quotes"]:
        facts_block.append(f"Quotes from post: {' | '.join(facts['quotes'][:2])}")
    if facts["has_story"]:
        facts_block.append("Post contains: a personal story")
    if facts["post_type_hint"]:
        facts_block.append(f"Post type: {facts['post_type_hint']}")

    facts_section = "\n".join(f" • {f}" for f in facts_block)

    return (
        f"Post by: {person_name}\n"
        f"About them: {person_notes or 'not provided'}\n\n"
        f"GROUNDING FACTS (only reference these):\n{facts_section}\n\n"
        f"FULL POST:\n\"\"\"\n{post_text[:1800]}\n\"\"\"\n\n"
        f"Write ONLY the comment (or SKIP). No preamble."
    )

def _parse_retry_after(err_str):
    m = re.search(r'try again in (\d+)m([\d.]+)s', err_str)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2)) + 5
    m = re.search(r'try again in ([\d.]+)s', err_str)
    if m:
        return float(m.group(1)) + 5
    return 60

def generate_comment(post_text, person_name, person_notes,
                     _model=None, _retries=0):
    if _retries >= 3:
        return None

    model = _model or "llama-3.3-70b-versatile"
    try:
        client = Groq(api_key=GROQ_API_KEY)
        facts = extract_post_facts(post_text)
        system = USER_PLAYBOOK if USER_PLAYBOOK.strip() else BASE_PLAYBOOK
        prompt = build_grounded_prompt(post_text, person_name, person_notes, facts)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.92,
            max_tokens=180,
        )

        comment = response.choices[0].message.content.strip().strip('"\'')

        # ENFORCE 5% QUESTION RULE
        if comment.endswith('?') and random.random() > 0.05:
            comment = comment.rstrip('?').strip()
            if not comment.endswith(('.', '!')):
                comment += '.'

        # FORCE FULL STOPS ON EVERY SENTENCE
        lines = [l.strip() for l in comment.split('\n\n') if l.strip()]
        fixed = []
        for line in lines:
            # Clean up and ensure punctuation
            line = line.strip()
            if line and not line.endswith(('.', '!', '?')):
                line += '.'
            fixed.append(line)
        comment = '\n\n'.join(fixed)

        if not comment or comment.upper().startswith("SKIP"):
            return None

        # Strip leaked preamble
        for prefix in ["STEP 1", "Post type:", "Type:", "FUNNY", "EMOTIONAL",
                        "INTELLECTUAL", "HOW-TO", "ACHIEVEMENT", "OPINION", "Move:"]:
            if comment.startswith(prefix):
                parts = comment.split("\n\n", 1)
                if len(parts) > 1:
                    comment = parts[1].strip()

        # Quality guard
        banned = [
            "resonates", "this landed", "so true", "great post",
            "thanks for sharing", "love this", "well said", "powerful",
            "inspiring", "couldn't agree more", "absolutely", "unpacking",
            "nuanced", "mindset", "journey", "impactful", "synergy",
            "ecosystem", "as a founder", "as someone", "what a ",
            "this is a reminder", "game-changer",
        ]
        if any(p in comment.lower() for p in banned):
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        # Format: enforce line-by-line
        if "\n\n" not in comment and len(comment.split(". ")) >= 2:
            sentences = [s.strip() for s in comment.replace(".\n", ". ").split(". ") if s.strip()]
            formatted = []
            for s in sentences:
                if not s.endswith((".", "!", "?")):
                    s += "."
                formatted.append(s)
            comment = "\n\n".join(formatted)

        # Length guard
        words = comment.replace("\n", " ").split()
        if len(words) < 5 or len(words) > 90:
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        return comment

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate_limit_exceeded" in err_str:
            wait = _parse_retry_after(err_str)
            if "tokens per day" in err_str.lower() and wait > 600:
                if model == "llama-3.3-70b-versatile":
                    print(f" 70b daily limit — switching to 8b")
                    return generate_comment(post_text, person_name, person_notes,
                                            _model="llama-3.1-8b-instant", _retries=_retries)
                return None
            print(f" Rate limited — waiting {wait:.0f}s...")
            time.sleep(wait)
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)
        print(f" AI error: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# BROWSER
# ══════════════════════════════════════════════════════════════════════════════
def create_driver():
    CHROME_PROFILE_PATH = r"C:\chrome_linkedin"
    opts = Options()
    opts.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
    opts.add_argument("--profile-directory=Default")
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
            return bool(driver.find_elements(By.CSS_SELECTOR, ".global-nav__me"))
        except Exception:
            return False

    if _logged_in():
        if not silent:
            print(" Already logged in!")
        return True

    if not silent:
        print("\n" + "="*55)
        print("ACTION: Log into LinkedIn in the Chrome window.")
        print("Zacharia continues automatically once detected.")
        print("="*55)

    for _ in range(72):
        time.sleep(5)
        if _logged_in():
            if not silent:
                print(" Logged in — continuing...")
            return True
    return False

# ══════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════
def connect_sheets(max_retries=5):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            creds = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
            client = gspread.authorize(creds)
            wb = client.open_by_key(SPREADSHEET_ID)

            try:
                ws = wb.worksheet(ENGAGEMENT_LIST_SHEET)
                print(f" Using sheet: '{ENGAGEMENT_LIST_SHEET}'")
            except Exception:
                ws = wb.add_worksheet(title=ENGAGEMENT_LIST_SHEET, rows=500, cols=12)
                ws.append_row(LIST_HEADERS)
                ws.freeze(rows=1)
                print(f" Created sheet: '{ENGAGEMENT_LIST_SHEET}'")

            return ws

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(3 * attempt)
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
            url = (row[1] or "").strip().rstrip("/")
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
                "row": i,
                "name": name,
                "url": url,
                "notes": (row[2] or "").strip(),
                "last_post_url": (row[3] or "").strip(),
                "last_post_id": (row[4] or "").strip(),
                "last_comment": (row[5] or "").strip(),
                "last_date": (row[6] or "").strip(),
                "status": (row[7] or "").strip(),
                "typical_hour": typical_hour,
                "confidence": confidence,
                "last_post_time": (row[10] or "").strip(),
            })
        return people
    except Exception as e:
        print(f" Load error: {e}")
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
        print(f" Sheet update error: {e}")

def update_timing(ws, row_num, post_hour_utc, current_confidence, post_dt_str):
    """Update the person's typical posting hour using circular mean."""
    try:
        new_confidence = current_confidence + 1
        cur_val = ws.cell(row_num, 9).value or ""
        try:
            current_hour = int(cur_val)
        except (ValueError, TypeError):
            current_hour = None

        if current_hour is None:
            new_hour = post_hour_utc
        else:
            w_old = current_confidence
            w_new = 2
            w_tot = w_old + w_new
            a_old = current_hour * (2 * math.pi / 24)
            a_new = post_hour_utc * (2 * math.pi / 24)
            sin_a = (math.sin(a_old) * w_old + math.sin(a_new) * w_new) / w_tot
            cos_a = (math.cos(a_old) * w_old + math.cos(a_new) * w_new) / w_tot
            new_hour = int((math.atan2(sin_a, cos_a) * 24 / (2 * math.pi)) % 24)

        ws.update_cell(row_num, 9, str(new_hour))
        ws.update_cell(row_num, 10, str(new_confidence))
        ws.update_cell(row_num, 11, post_dt_str)
    except Exception as e:
        print(f" Timing update error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# WINDOW FILTER — pre-browser, pure Python
# ══════════════════════════════════════════════

def in_posting_window(person, current_hour_utc):
    """
    Returns (should_visit: bool, reason: str).

    Before POST_WINDOW_MIN_CONFIDENCE data points: always visit (still learning).
    After: only visit within ±POST_WINDOW_HRS of their typical hour.
    """
    confidence = person.get("confidence", 0)
    typical_hour = person.get("typical_hour")

    if confidence < POST_WINDOW_MIN_CONFIDENCE or typical_hour is None:
        return True, f"learning ({confidence}/{POST_WINDOW_MIN_CONFIDENCE} pts)"

    diff = min(
        abs(current_hour_utc - typical_hour),
        24 - abs(current_hour_utc - typical_hour)
    )
    if diff <= POST_WINDOW_HRS:
        return True, f"in window (posts ~{typical_hour:02d}:xx UTC ±{POST_WINDOW_HRS}h)"

    open_h = (typical_hour - POST_WINDOW_HRS) % 24
    close_h = (typical_hour + POST_WINDOW_HRS) % 24
    return False, f"posts ~{typical_hour:02d}:xx UTC (window {open_h:02d}–{close_h:02d})"

def already_commented_today(person, today_str):
    """True if we already commented on this person today."""
    last = person.get("last_date", "") or ""
    return last.startswith(today_str)

# ══════════════════════════════════════════════
# POST SCRAPING
# ══════════════════════════════════════════════════════════════════════════════

def _estimate_age_hours(ts):
    if not ts:
        return 4.0
    ts = ts.strip()
    if 'T' in ts and len(ts) > 15:
        try:
            ts_clean = re.sub(r'\.\d+', '', ts.replace('Z', '+00:00'))
            dt = datetime.fromisoformat(ts_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except Exception:
            pass
    try:
        from dateutil import parser as dp
        dt = dp.parse(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        pass
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
    return 4.0

def get_latest_post(driver, profile_url):
    try:
        username = profile_url.rstrip("/").split("/in/")[-1].split("/")[0].split("?")[0]
        activity_url = f"https://www.linkedin.com/in/{username}/recent-activity/all/"
        if not safe_get(driver, activity_url):
            return None
        pause(4, 6)

        for _ in range(4):
            driver.execute_script("window.scrollBy(0, 700);")
            time.sleep(1.2)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        posts = driver.execute_script("""
            var results = [];
            var containers = document.querySelectorAll(
                '.feed-shared-update-v2,.occludable-update'
            );
            for (var i = 0; i < Math.min(containers.length, 8); i++) {
                var el = containers[i];
                var textEl = (
                    el.querySelector('.update-components-text') ||
                    el.querySelector('.feed-shared-text span[dir="ltr"]') ||
                    el.querySelector('.feed-shared-text') ||
                    el.querySelector('.break-words span[dir="ltr"]')
                );
                var text = textEl? textEl.innerText.trim() : '';
                if (!text || text.length < 80 || text.split(' ').length < 10) continue;

                var ts = '';
                var timeEl = el.querySelector('time[datetime]');
                if (timeEl) ts = timeEl.getAttribute('datetime') || '';
                if (!ts) {
                    var allT = el.querySelectorAll('time');
                    for (var t = 0; t < allT.length; t++) {
                        var dt = allT[t].getAttribute('datetime');
                        if (dt && dt.indexOf('T') > 0) { ts = dt; break; }
                        if (!ts) ts = allT[t].innerText || '';
                    }
                }
                var url = '';
                var linkEl = (
                    el.querySelector('a[href*="/feed/update/"]') ||
                    el.querySelector('a[href*="activity"]') ||
                    el.querySelector('a[href*="ugcPost"]')
                );
                if (linkEl) url = linkEl.href;
                results.push({text: text, ts: ts, url: url});
            }
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
        url = post.get("url", "") or activity_url
        ts = post.get("ts", "")

        if not text or len(text) < 80:
            return None

        # Strip name echo
        lines = text.split("\n")
        if len(lines) >= 3 and lines[0].strip() == lines[1].strip():
            text = "\n".join(lines[2:]).strip()
        if len(text) < 40:
            return None

        age_hours = _estimate_age_hours(ts)
        if age_hours > POST_RECENCY_HOURS:
            return None

        post_id = hashlib.md5(f"{username}:{text[:120]}".encode()).hexdigest()[:16]

        return {"text": text[:2500], "url": url, "post_id": post_id, "age_hours": age_hours}

    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["connectionreset", "10054", "invalid session", "no such window"]):
            raise
        print(f" Post fetch error: {e}")
        return None

# ══════════════════════════════════════════════════════════════════════════════
# COMMENT POSTING
# ══════════════════════════════════════════════════════════════════════════════

def _find_comment_box(driver, timeout=6):
    SELECTORS = [
        "div[data-placeholder='Add a comment…'][contenteditable='true']",
        "div[aria-placeholder='Add a comment…'][contenteditable='true']",
        ".ql-editor[contenteditable='true']",
        ".comments-comment-box.ql-editor",
        ".comments-comment-texteditor.ql-editor",
        "div[role='textbox'][aria-label*='comment']",
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
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.4)
                    driver.execute_script("arguments[0].click();", btn)
                    return True
        except Exception:
            continue

    clicked = driver.execute_script("""
        var bar = document.querySelector('.social-actions,.feed-shared-social-action-bar');
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
        print(f" Type error: {e}")
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
        var form = document.querySelector('.comments-comment-box') ||
                   document.querySelector('.comments-comment-texteditor') ||
                   document.body;
        var btns = Array.from(form.querySelectorAll('button'));
        for (var i = 0; i < btns.length; i++) {
            var b = btns[i];
            var lbl = (b.getAttribute('aria-label') || '').toLowerCase().trim();
            var txt = (b.innerText || '').toLowerCase().trim();
            if (b.disabled) continue;
            if (txt==='comment'||txt==='post'||lbl==='comment'||lbl==='post comment') {
                b.click(); return true;
            }
        }
        var primary = form.querySelector('button.artdeco-button--primary:not([disabled])');
        if (primary) { primary.click(); return true; }
        return false;
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

        clicked = _click_comment_trigger(driver)
        if not clicked:
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1)
            clicked = _click_comment_trigger(driver)
        if not clicked and not _find_comment_box(driver, timeout=3):
            return False

        time.sleep(2.5)
        if not _type_into_box(driver, comment_text):
            return False

        pause(2.0, 3.0)
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
        print(f" Post comment error: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# COLOUR HELPERS
# ══════════════════════════════════════════════════════════════════════════════
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    def GREEN(t): return Fore.GREEN + str(t) + Style.RESET_ALL
    def YELLOW(t): return Fore.YELLOW + str(t) + Style.RESET_ALL
    def DIM(t): return Style.DIM + str(t) + Style.RESET_ALL
except Exception:
    def GREEN(t): return str(t)
    def YELLOW(t): return str(t)
    def DIM(t): return str(t)

def age_label(hours):
    if hours < 1: return GREEN("just now 🔥")
    if hours < POST_FRESH_MAX_HOURS: return GREEN(f"{hours:.0f}h ago 🔥 FRESH")
    if hours < POST_RECENT_MAX_HOURS: return YELLOW(f"{hours:.0f}h ago ⏱ RECENT")
    return DIM(f"{hours:.0f}h ago — stale")

# ══════════════════════════════════════════════
# MAIN — single-pass, window-filtered, skip-today
# ══════════════════════════════════════════════════════════════════════════════
def run():
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    cur_hour = now_utc.hour
    name_display = CLIENT_FIRST_NAME or CLIENT_NAME or "Zack User"

    print(f"\n{'='*58}")
    print(f" Zacharia — Commenting Agent v4 for Users")
    print(f" Running for: {name_display}")
    print(f" {now_utc.strftime('%Y-%m-%d %H:%M UTC')} | Max: {MAX_COMMENTS_PER_RUN} comments")
    print(f" Fresh: 0-{POST_FRESH_MAX_HOURS}h | Recent: {POST_FRESH_MAX_HOURS}-{POST_RECENT_MAX_HOURS}h | Window: ±{POST_WINDOW_HRS}h")
    print(f" Mode: SINGLE-PASS — scan and comment immediately")
    print(f"{'='*58}\n")

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in zack_config.py")
        print(" Run python zack_setup.py to reconfigure")
        return

    print("📊 Connecting to sheets...")
    ws = connect_sheets()

    people = load_engagement_list(ws)
    if not people:
        print(f" No people in '{ENGAGEMENT_LIST_SHEET}'.")
        return
    print(f" {len(people)} people in engagement list\n")

    # ── PRE-FILTER — all logic before opening the browser ─────────────────
    # Three gates, in order:
    # 1. Already commented today → skip entirely
    # 2. Outside posting window → skip (not their time)
    # 3. Sort: high-confidence posters first, learners last

    to_visit = []
    n_done_today = 0
    n_off_window = 0

    for person in people:
        # Gate 1: already done today - DISABLED to catch multiple posts
        # if already_commented_today(person, today):
        #     n_done_today += 1
        #     continue

        # Gate 2: outside their posting window
        in_win, win_reason = in_posting_window(person, cur_hour)
        if not in_win:
            n_off_window += 1
            continue

        to_visit.append((person, win_reason))

    # Sort: known posters (high confidence) first, learners last
    # Within known posters: those we haven't visited recently go first
    to_visit.sort(
        key=lambda x: (
            -(x[0].get("confidence", 0)), # high confidence first
            x[0].get("last_date", "") or "", # less-recently-visited first
        )
    )

    known = [(p, r) for p, r in to_visit if p.get("confidence", 0) >= POST_WINDOW_MIN_CONFIDENCE]
    learners = [(p, r) for p, r in to_visit if p.get("confidence", 0) < POST_WINDOW_MIN_CONFIDENCE]

    print(f"🕐 {now_utc.strftime('%H:%M UTC')} | {today}")
    print(f" ✅ Already commented today : {n_done_today} (skipped)")
    print(f" ⏭ Outside posting window : {n_off_window} (skipped — wrong time)")
    print(f" 🎯 Known posters in window : {len(known)}")
    print(f" 📚 Learning-mode posters : {len(learners)}")
    print(f" 🔍 Total to visit : {len(to_visit)}\n")

    if not to_visit:
        print(" Nothing to do this run.")
        print(" Either everyone was visited today, or no one is in their posting window.")
        print(" Try again when more people are in their active hours.")
        return

    # ── OPEN BROWSER ──────────────────────────────────────────────────────
    driver = create_driver()
    commented = 0
    no_post = 0
    already = 0
    stale = 0
    unsuitable = 0

    try:
        if not wait_for_login(driver):
            print("❌ Login timed out — stopping")
            return

        print(f"\n{'─'*58}")
        print(f"🔍 Visiting {len(to_visit)} profiles — commenting immediately...\n")

        # Process in order: known window posters → learners
        for person, win_reason in to_visit:
            if commented >= MAX_COMMENTS_PER_RUN:
                print(f"\n ✅ Limit reached ({MAX_COMMENTS_PER_RUN} comments) — stopping.")
                print(f" Remaining profiles will be picked up on the next run.")
                break

            name = person["name"]
            url = person["url"]
            notes = person.get("notes", "")
            conf = person.get("confidence", 0)

            print(f" {name} [{win_reason}]")

            # ── Browser health check ───────────────────────────────────────
            if not is_driver_alive(driver):
                print(f" ⚠️ Browser crashed — restarting...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(3)
                driver = create_driver()
                if not wait_for_login(driver):
                    print(" ❌ Login timed out — stopping")
                    break

            # ── Fetch post ────────────────────────────────────────────────
            print(f" → Fetching post...")
            try:
                post = get_latest_post(driver, url)
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["connectionreset","10054","invalid session","no such window","connection aborted"]):
                    print(f" ⚠️ Browser crashed — restarting...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    time.sleep(4)
                    driver = create_driver()
                    wait_for_login(driver)
                else:
                    print(f" → Error: {e}")
                no_post += 1
                pause(2, 4)
                continue

            if not post:
                print(f" → No post in last {POST_RECENCY_HOURS}h")
                update_row(ws, person["row"], "", "", "", "no_recent_post")
                no_post += 1
                pause(2, 4)
                continue

            age_h = post["age_hours"]
            post_id = post["post_id"]

            # ── Update timing intelligence ─────────────────────────────────
            # Do this every time we see a post — this is how Zack learns
            try:
                post_time = datetime.now(timezone.utc) - timedelta(hours=age_h)
                update_timing(ws, person["row"], post_time.hour,
                              conf, post_time.strftime("%Y-%m-%d %H:%M"))
            except Exception:
                pass

            # ── Already commented on this exact post ───────────────────────
            if post_id == person.get("last_post_id", ""):
                print(f" → Already commented on this post")
                already += 1
                pause(1, 2)
                continue

            print(f" → {len(post['text'].split())} words | {age_label(age_h)}")
            print(f" → '{post['text'][:80]}...'")

            # ── Age gate ───────────────────────────────────────────────────
            if age_h > POST_RECENT_MAX_HOURS:
                print(f" → {age_h:.0f}h — too stale, skipping")
                stale += 1
                update_row(ws, person["row"], post["url"], post_id, "", "stale_skipped")
                pause(1, 2)
                continue

            # ── Generate comment ───────────────────────────────────────────
            print(f" → Generating comment...")
            comment = generate_comment(post["text"], name, notes)

            if not comment:
                print(f" → Not suitable — skipping")
                update_row(ws, person["row"], post["url"], post_id, "", "skipped_unsuitable")
                unsuitable += 1
                pause(2, 4)
                continue

            freshness = "🔥 FRESH" if age_h <= POST_FRESH_MAX_HOURS else "⏱ RECENT"
            print(f" → [{freshness}] {comment[:75]}...")

            # ── Post comment immediately ───────────────────────────────────
            print(f" → Posting...")
            try:
                success = post_comment(driver, post["url"], comment)
            except Exception as e:
                print(f" → Error: {e}")
                success = False

            if success:
                commented += 1
                update_row(ws, person["row"], post["url"], post_id, comment, "commented")
                print(f" ✅ Done ({commented}/{MAX_COMMENTS_PER_RUN})\n")
            else:
                print(f" ❌ Failed\n")
                update_row(ws, person["row"], post["url"], post_id, comment, "post_failed")

            # Human pacing between comments
            pause(10, 16)

        # ── Summary ────────────────────────────────────────────────────────
        print(f"{'='*58}")
        print(f"✅ RUN COMPLETE")
        print(f" Comments posted : {commented}")
        print(f" No post found : {no_post}")
        print(f" Already commented : {already}")
        print(f" Stale (>{POST_RECENT_MAX_HOURS}h) : {stale}")
        print(f" Unsuitable : {unsuitable}")
        print(f" Done today (skipped) : {n_done_today}")
        print(f" Off-window (skipped) : {n_off_window}")
        print(f"\n Run again later to pick up anyone not yet visited.")
        print(f" Once confidence ≥ {POST_WINDOW_MIN_CONFIDENCE}, only their posting window is visited.")
        print(f"{'='*58}\n")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print("Browser closed.")

if __name__ == "__main__":
    run()
