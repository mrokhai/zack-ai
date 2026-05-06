"""
Zacharia — Autonomous Engagement Engine v2
===========================================
Reads a manual list from 'Zacharia Engagement List' sheet.
Visits each person's LinkedIn profile, finds their latest post,
generates a high-value comment using the LinkedIn Commenting Playbook,
and posts it automatically.

Tracks every comment posted so it never double-comments on the same post.
Fully autonomous — no email approval needed.

Run: python zacharia_engage.py

Sheet setup:
  Create a tab called 'Zacharia Engagement List' with columns:
  Name | LinkedIn URL | Notes | Last Post URL | Last Comment | Last Comment Date | Status
"""

import os, re, time, random, hashlib, gspread
from datetime import datetime, timezone
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


# ── Config ────────────────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_PATH = "google_credentials.json"
SPREADSHEET_ID          = "1SPpk_CXaPk0vstwTmP3McVK6ZC64-39KepY4h6Ug0os"
GROQ_API_KEY            = os.environ.get("GROQ_API_KEY", "")

ENGAGEMENT_LIST_SHEET   = "Zacharia Engagement List"
MAX_COMMENTS_PER_RUN    = 25       # LinkedIn safe limit
POST_RECENCY_HOURS      = 72       # Only comment on posts from last 72 hours
SLOW_MODE               = True

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LIST_HEADERS = [
    "Name",               # A — you fill this
    "LinkedIn URL",       # B — you fill this
    "Notes",              # C — optional context about the person
    "Last Post URL",      # D — auto-filled by Zacharia
    "Last Post ID",       # E — auto-filled (hash to track uniqueness)
    "Last Comment",       # F — auto-filled
    "Last Comment Date",  # G — auto-filled
    "Status",             # H — auto-filled
]


# ══════════════════════════════════════════════════════════════════════════════
# THE LINKEDIN COMMENTING PLAYBOOK — AI System Prompt
# ══════════════════════════════════════════════════════════════════════════════
COMMENTING_PLAYBOOK = """You write LinkedIn comments that make people stop, read twice, and reply.

WHO YOU ARE:
A founder who has built real things. You read carefully and react genuinely.
Witty without performing it. Direct without being cold.
You match the energy of the room — you don't bring a lecture to a laugh.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — READ THE POST TYPE FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before writing anything, identify what kind of post this is:

FUNNY / LIGHT — A joke, a relatable observation, something playful
→ Match the energy. Be funny back or add a dry wry observation.
→ DO NOT turn it serious. DO NOT add a lesson.
→ Example response energy: "That last line did it for me." or a dry one-liner.

EMOTIONAL / PERSONAL STORY — Vulnerability, struggle, loss, win, human moment
→ Acknowledge the human thing first. Make them feel seen.
→ Add your own honest reaction — not advice, not a lesson.
→ One warm specific line is worth ten generic ones.

INTELLECTUAL / NEW IDEA / FRAMEWORK — A new angle on a problem, a counterintuitive take
→ This is where you add depth. Extend the idea, show the flip side, or sharpen it.
→ A question is appropriate HERE — but only if it genuinely opens more thinking.

HOW-TO / TACTICAL / TOOL — A process, a technique, a specific method
→ Validate the specific thing that actually works.
→ Add one thing they didn't mention that makes it even better or more honest.

ACHIEVEMENT / MILESTONE — Funding, launch, new role, big win
→ Be genuinely happy for them. Short. Specific. Not performative.
→ Reference the actual thing, not generic "congrats."

OPINION / HOT TAKE — A strong position or contrarian view
→ Either sharpen their argument or respectfully show the edge case where it breaks.
→ No fence-sitting. Have a view.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — PICK YOUR MOVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
After identifying the post type, pick ONE move:

A. THE UNSAID THING — land the truth they implied but didn't say
B. THE FLIP — show the other side (not a fight — a reveal)
C. THE SPECIFIC MOMENT — one tight real thing from experience
D. THE DRY OBSERVATION — wry reframe, let it land without explaining it
E. MAKE THEM FEEL SEEN — reflect back what made their post worth reading
F. THE SHARPENER — take their idea and make it more precise, more useful

Only use a QUESTION for moves A, B, or F — and only when the post is intellectual
or when the question will genuinely open the conversation further.
Do NOT end every comment with a question. Questions in only ~40% of comments.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORMAT — NON-NEGOTIABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Each line is its own thought. Blank line between every line.

Short line.

Another line that builds or lands.

Optional third line. (No question unless it earns it.)

- Max 3 lines
- No paragraphs, no walls of text
- Each line punchy, not padded

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES BY POST TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FUNNY post about getting banned from LinkedIn 10 times:
"Getting banned is basically a LinkedIn badge of honour at this point.

The algorithm punishes authenticity and rewards safe mediocrity.

You're doing it right."

EMOTIONAL post about a mentor who passed away:
"The people who shape us the most rarely know how much they did.

Sounds like he knew exactly who you were becoming."

INTELLECTUAL post about AI replacing jobs:
"The jobs AI can't replace are the ones that require judgment under ambiguity.

Which means the value of that skill just went up — not down.

Most people haven't priced that in yet."

HOW-TO post about improving LinkedIn profiles:
"The profile photo is doing more than most people realise.

Everything else is downstream of whether someone trusts the face first."

ACHIEVEMENT post about closing a funding round:
"The round is just the start of a harder chapter.

But getting here first — that's the part most people underestimate.

Congrats, genuinely."

OPINION post about hustle culture:
"The advice assumes you have the option to rest.

For most early-stage founders that option shows up after the burnout — not before."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BANNED — these instantly signal AI or hollow thinking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"resonates" / "this landed" / "so true" / "powerful" / "inspiring"
"great post" / "thanks for sharing" / "love this" / "well said"
"couldn't agree more" / "absolutely" / "100%"
"unpacking" / "nuanced" / "framework" / "mindset" / "journey"
"as a founder" / "as someone who" / "this is a reminder that"
"leverage" (verb) / "ecosystem" / "impactful" / "synergy" / "game-changer"
Starting with "What a..." — ever
Ending with "...thoughts?" as a standalone line
Any motivational/corporate language

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GUARDRAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Grief/loss/medical: 1-2 warm human lines only — no insight, no lesson
- Purely promotional: SKIP
- Political: engage the human/business angle only, never the politics
- Nothing genuine to add: SKIP

OUTPUT: Write ONLY the comment with \n\n between each line.
If skipping: write exactly SKIP"""


# ══════════════════════════════════════════════════════════════════════════════
# BROWSER — identical to other working scripts
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
    # 60s page load timeout — long enough for LinkedIn's slow initial loads
    # but still protects against infinite hangs on activity pages
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(3)
    return driver


def is_driver_alive(driver):
    """Check if the browser window is still open and responsive."""
    try:
        _ = driver.current_url   # throws if window is closed
        return True
    except Exception:
        return False


def safe_get(driver, url):
    """
    Navigate to a URL with full protection:
    - Page load timeout → stop() and continue with partial load
    - ConnectionResetError (WinError 10054) → raise so run() can restart driver
    - Window closed / session invalid → return False
    """
    try:
        driver.get(url)
        return True
    except Exception as e:
        err     = str(e).lower()
        err_raw = str(e)

        # Timeout — stop loading and work with partial page
        if "timeout" in err or "timed out" in err:
            try:
                driver.execute_script("window.stop();")
                time.sleep(1)
                return True
            except Exception:
                return False

        # ChromeDriver lost its connection to Chrome (WinError 10054 equivalent)
        # Re-raise so the run() loop can catch it and restart the browser
        if any(x in err for x in [
            "connectionreset", "10054", "connection aborted",
            "remotedisconnected", "invalid session", "no such window",
            "web view not found", "target window already closed",
        ]):
            raise

        # Any other error — just skip this URL
        return False

def pause(a=2.0, b=5.0):
    time.sleep(random.uniform(a, b) if SLOW_MODE else random.uniform(0.5, 1.5))


def wait_for_login(driver):
    """Open LinkedIn and wait for the user to log in. Fully crash-proof."""
    # Use safe_get so a slow first load doesn't kill the session
    try:
        driver.set_page_load_timeout(90)   # extra generous for first load
        safe_get(driver, "https://www.linkedin.com")
        driver.set_page_load_timeout(60)   # back to normal for everything else
    except Exception:
        pass   # even if this fails, we still check the URL below

    time.sleep(4)

    def _is_logged_in():
        try:
            url = driver.current_url
            if "feed" in url or "mynetwork" in url:
                return True
            if driver.find_elements(By.CSS_SELECTOR, ".global-nav__me"):
                return True
            return False
        except Exception:
            return False

    if _is_logged_in():
        print("   Already logged in!")
        return

    print("\n" + "="*55)
    print("ACTION: Log into LinkedIn in the Chrome window.")
    print("Zacharia will continue automatically once detected.")
    print("="*55)

    for _ in range(72):   # wait up to 6 minutes
        time.sleep(5)
        if _is_logged_in():
            print("   Logged in — continuing...")
            return

    print("   Continuing anyway...")


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════════════════════════════
def connect_sheets(max_retries=5):
    """
    Connect to Google Sheets with retry + exponential backoff.
    Handles WinError 10054 (connection forcibly closed) and other
    transient SSL/network errors that happen on unstable connections.
    """
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
            except Exception:
                ws = wb.add_worksheet(title=ENGAGEMENT_LIST_SHEET, rows=500, cols=9)
                ws.append_row(LIST_HEADERS)
                ws.format("A1:H1", {
                    "textFormat": {"bold": True,
                                   "foregroundColor": {"red":1,"green":1,"blue":1}},
                    "backgroundColor": {"red":0.04,"green":0.06,"blue":0.18}
                })
                ws.freeze(rows=1)
                print(f"   Created sheet: '{ENGAGEMENT_LIST_SHEET}'")
                print(f"\n   ⚠️  Sheet created. Please add people to it:")
                print(f"   Column A: Name")
                print(f"   Column B: LinkedIn URL")
                print(f"   Column C: Notes (optional)")
                print(f"   Then run again.\n")

            return ws

        except Exception as e:
            last_err = e
            err_str  = str(e)
            # Transient network errors — worth retrying
            retryable = any(x in err_str for x in [
                "10054", "ConnectionReset", "Connection aborted",
                "TransportError", "ssl", "SSL", "timed out",
                "RemoteDisconnected", "ConnectionError",
            ])
            if retryable and attempt < max_retries:
                wait = 3 * attempt   # 3s, 6s, 9s, 12s
                print(f"   ⚠️  Sheets connection failed (attempt {attempt}/{max_retries})"
                      f" — retrying in {wait}s...")
                time.sleep(wait)
                continue
            # Non-retryable or out of attempts
            break

    raise RuntimeError(
        f"Could not connect to Google Sheets after {max_retries} attempts.\n"
        f"Last error: {last_err}\n\n"
        f"Check your internet connection and try again."
    )


def load_engagement_list(ws):
    """
    Load the manual engagement list. Returns list of dicts.
    Reads raw rows directly (not get_all_records) so duplicate/blank
    column headers in the sheet never cause a crash.
    Expects columns: A=Name, B=LinkedIn URL, C=Notes,
                     D=Last Post URL, E=Last Post ID, F=Last Comment,
                     G=Last Comment Date, H=Status
    """
    try:
        all_rows = ws.get_all_values()   # always works regardless of headers
        if not all_rows:
            return []

        people = []
        # Skip row 0 (header) — start from row index 1 (sheet row 2)
        for i, row in enumerate(all_rows[1:], start=2):
            # Pad short rows so index access never throws
            row = row + [""] * 10

            name = (row[0] or "").strip()
            url  = (row[1] or "").strip().rstrip("/")

            if not name or not url or "/in/" not in url:
                continue

            people.append({
                "row":           i,
                "name":          name,
                "url":           url,
                "notes":         (row[2] or "").strip(),
                "last_post_url": (row[3] or "").strip(),
                "last_post_id":  (row[4] or "").strip(),
                "last_comment":  (row[5] or "").strip(),
                "last_date":     (row[6] or "").strip(),
                "status":        (row[7] or "").strip(),
            })

        return people

    except Exception as e:
        print(f"   Load error: {e}")
        return []


def update_row(ws, row_num, post_url, post_id, comment, status):
    """Update the sheet row after commenting."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        ws.update_cell(row_num, 4, post_url)     # D Last Post URL
        ws.update_cell(row_num, 5, post_id)      # E Last Post ID
        ws.update_cell(row_num, 6, comment[:300]) # F Last Comment
        ws.update_cell(row_num, 7, today)        # G Last Comment Date
        ws.update_cell(row_num, 8, status)       # H Status
    except Exception as e:
        print(f"      Sheet update error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SCRAPE LATEST POST
# ══════════════════════════════════════════════════════════════════════════════
def get_latest_post(driver, profile_url):
    """
    Visit the person's recent activity page and get their latest post.
    Returns dict with post_text, post_url, post_id or None if no recent post.
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

            // ── Strategy 1: standard feed update containers ───────────────────
            var containers = document.querySelectorAll(
                '.feed-shared-update-v2, .occludable-update'
            );

            for (var i = 0; i < Math.min(containers.length, 8); i++) {
                var el = containers[i];

                // Skip reshared posts where the person didn't write anything
                var reshareText = el.querySelector(
                    '.feed-shared-update-v2__commentary, ' +
                    '.feed-shared-mini-update-v2__commentary'
                );

                // Primary text selectors — in priority order
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

                // Filter out anything that looks like just a name / header
                // (real post content always has spaces and is longer than 80 chars
                //  OR contains punctuation / newlines)
                if (!text || text.length < 80) continue;
                var wordCount = text.split(' ').length;
                if (wordCount < 10) continue;

                // Timestamp
                var timeEl = el.querySelector('time');
                var ts = '';
                if (timeEl) {
                    ts = timeEl.getAttribute('datetime') || timeEl.innerText || '';
                }

                // Post URL
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

            // ── Strategy 2: fallback — grab all substantial text blocks ───────
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

        # Final guard: must be real content, not a repeated name
        if not text or len(text) < 80:
            return None

        # Strip any leading name echo (LinkedIn sometimes prepends "Name\nName\n")
        lines = text.split("\n")
        if len(lines) >= 3 and lines[0].strip() == lines[1].strip():
            text = "\n".join(lines[2:]).strip()

        if len(text) < 40:
            return None

        # Check recency
        age_hours = _estimate_age_hours(ts)
        if age_hours > POST_RECENCY_HOURS:
            return None

        post_id = hashlib.md5(f"{username}:{text[:120]}".encode()).hexdigest()[:16]

        return {
            "text":      text[:2000],
            "url":       url,
            "post_id":   post_id,
            "age_hours": age_hours,
        }

    except Exception as e:
        print(f"      Post fetch error: {e}")
        return None


def _estimate_age_hours(ts):
    """Estimate post age in hours from timestamp string."""
    if not ts:
        return 48
    t = ts.lower().strip()
    if any(x in t for x in ["just now","now","moment"]):
        return 0
    m = re.search(r"(\d+)\s*([smhdw])", t)
    if m:
        v, u = int(m.group(1)), m.group(2)
        if u in ("s","m"): return 0
        if u == "h": return v
        if u == "d": return v * 24
        if u == "w": return v * 168
    if "yesterday" in t: return 25
    if "today" in t: return 2
    try:
        from dateutil import parser as dp
        dt = dp.parse(ts)
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (now - dt).total_seconds() / 3600)
    except:
        return 48


# ══════════════════════════════════════════════════════════════════════════════
# GENERATE COMMENT
# ══════════════════════════════════════════════════════════════════════════════
def _parse_retry_after(err_str):
    """Extract retry wait seconds from a Groq 429 error message."""
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
    Generate a context-aware, human LinkedIn comment via Groq.
    - Waits the exact time Groq specifies on 429 rate limits
    - Falls back to llama-3.1-8b-instant if 70b daily limit is hit
    - Truncates post_text to 1200 chars to save tokens
    """
    model = _model or "llama-3.3-70b-versatile"
    if _retries >= 3:
        return None

    try:
        client = Groq(api_key=GROQ_API_KEY)

        user_prompt = (
            f"Post by: {person_name}\n"
            f"Context: {person_notes if person_notes else 'not provided'}\n\n"
            f"POST:\n\"\"\"\n{post_text[:1200]}\n\"\"\"\n\n"
            f"STEP 1 — Identify the post type:\n"
            f"FUNNY/LIGHT | EMOTIONAL/PERSONAL | INTELLECTUAL/NEW IDEA | "
            f"HOW-TO/TACTICAL | ACHIEVEMENT/MILESTONE | OPINION/HOT TAKE\n\n"
            f"STEP 2 — Match the energy, pick your move:\n"
            f"  Funny → wry/dry, no lessons. Emotional → make them feel seen.\n"
            f"  Intellectual → add depth, show the flip. How-to → add one honest extra.\n"
            f"  Achievement → short, genuine, specific. Opinion → have a view.\n\n"
            f"STEP 3 — Write it:\n"
            f"  Each thought on its OWN line, blank line between them. Max 3 lines.\n"
            f"  No 'I' at the start. Questions only ~40% of the time (intellectual posts only).\n"
            f"  BANNED: resonates, landed, so true, great post, love this, powerful,\n"
            f"  inspiring, unpacking, nuanced, mindset, journey, absolutely, 100%,\n"
            f"  couldn't agree more, well said, as a founder, game-changer, impactful\n\n"
            f"If nothing genuine to add: write SKIP\n"
            f"Write ONLY the comment. No preamble."
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COMMENTING_PLAYBOOK},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.92,
            max_tokens=160,
        )

        comment = response.choices[0].message.content.strip().strip('"\'')

        if comment.upper().startswith("SKIP"):
            return None

        # Strip any leaked preamble
        for prefix in ["STEP 1", "Post type:", "Type:", "FUNNY", "EMOTIONAL",
                        "INTELLECTUAL", "HOW-TO", "ACHIEVEMENT", "OPINION"]:
            if comment.startswith(prefix):
                parts = comment.split("\n\n", 1)
                if len(parts) > 1:
                    comment = parts[1].strip()

        banned = [
            "resonates", "this landed", "so true", "great post",
            "thanks for sharing", "love this", "well said", "powerful",
            "inspiring", "couldn't agree more", "absolutely", "unpacking",
            "nuanced", "mindset", "journey", "impactful", "synergy",
            "ecosystem", "as a founder", "as someone", "what a ",
            "this is a reminder", "game-changer", "mathetes", "zack.ai",
        ]
        if any(p in comment.lower() for p in banned):
            print(f"      Quality guard — regenerating")
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        # Enforce line-by-line format
        if "\n\n" not in comment and len(comment.split(". ")) >= 2:
            sentences = [s.strip() for s in comment.replace(".\n", ". ").split(". ")
                         if s.strip()]
            formatted = []
            for s in sentences:
                if not s.endswith((".", "!", "?")):
                    s += "."
                formatted.append(s)
            comment = "\n\n".join(formatted)

        words = comment.replace("\n", " ").split()
        if len(words) < 6 or len(words) > 90:
            print(f"      Length guard — regenerating")
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        return comment

    except Exception as e:
        err_str = str(e)

        # 429 — parse exact wait time from Groq's error message
        if "429" in err_str or "rate_limit_exceeded" in err_str:
            wait_secs = _parse_retry_after(err_str)

            # Daily token limit hit on 70b → switch to 8b immediately
            if "tokens per day" in err_str.lower() and wait_secs > 600:
                if model == "llama-3.3-70b-versatile":
                    print(f"      70b daily limit hit — switching to llama-3.1-8b-instant")
                    return generate_comment(post_text, person_name, person_notes,
                                            _model="llama-3.1-8b-instant",
                                            _retries=_retries)
                else:
                    print(f"      All models rate limited for today — skipping")
                    return None

            # Short rate limit — wait and retry same model
            print(f"      Rate limited — waiting {wait_secs:.0f}s...")
            time.sleep(wait_secs)
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        print(f"      AI error: {e}")
        return None


def _find_comment_box(driver, timeout=6):
    """
    Find the visible comment editor. Always does a fresh DOM lookup —
    never reuse a stored reference (stale element protection).
    Uses JS click internally so overlapping elements can't block it.
    Returns the element or None.
    """
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


def _js_click(driver, el):
    """Click via JS — bypasses any overlapping element."""
    driver.execute_script("arguments[0].click();", el)


def _click_comment_trigger(driver):
    """
    Click the Comment button in the social action bar.
    Tries aria-label first, then JS text scan of action bar buttons.
    """
    # Strategy 1: aria-label on the button
    for sel in [
        "button[aria-label='Comment']",
        "button[aria-label='comment']",
        "button[aria-label*='Add a comment']",
    ]:
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                if btn.is_displayed():
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.4)
                    _js_click(driver, btn)
                    return True
        except Exception:
            continue

    # Strategy 2: JS scan of social action bar
    clicked = driver.execute_script("""
        var bar = document.querySelector(
            '.social-actions, .feed-shared-social-action-bar, '
            + '.social-action-bar, .feed-shared-footer'
        );
        var scope = bar || document;
        var btns = Array.from(scope.querySelectorAll('button'));
        for (var b of btns) {
            var lbl = (b.getAttribute('aria-label') || '').toLowerCase();
            var txt = (b.innerText || '').trim();
            if (lbl.includes('comment') || txt === 'Comment') {
                b.click();
                return true;
            }
        }
        return false;
    """)
    return bool(clicked)


def _type_into_box(driver, comment_text):
    """
    Re-find the comment box fresh, JS-focus it, then type the comment.
    Handles newlines correctly for LinkedIn's Quill editor:
      - Single \n  → Shift+Enter (line break within paragraph)
      - Double \n\n → Shift+Enter twice (blank line = visual paragraph gap)
    Returns True if typed successfully.
    """
    box = _find_comment_box(driver, timeout=8)
    if not box:
        return False

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});", box)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", box)
        time.sleep(0.7)

        # Split on newlines and type segment by segment
        segments = comment_text.split("\n")
        for idx, segment in enumerate(segments):
            if segment:
                # Type this segment in 40-char chunks
                for chunk in [segment[i:i+40] for i in range(0, len(segment), 40)]:
                    box.send_keys(chunk)
                    time.sleep(random.uniform(0.07, 0.18))
            # Between segments: Shift+Enter creates a line break in Quill
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
    """
    Click the blue 'Comment' submit button that appears after typing.
    LinkedIn's submit button text is literally 'Comment' — not 'Post',
    not 'Post comment'. It lives inside the comment form container.
    """
    # Strategy 1: known CSS class selectors (fastest if they exist)
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

    # Strategy 2: JS — scoped to comment form, matches the actual button text
    # The button says "Comment" (same word as the trigger) but is INSIDE the
    # .comments-comment-box container and is enabled only after text is typed.
    submitted = driver.execute_script("""
        var form = (
            document.querySelector('.comments-comment-box') ||
            document.querySelector('.comments-comment-texteditor') ||
            document.querySelector('[data-test-id*="comment-box"]') ||
            document.body
        );
        var btns = Array.from(form.querySelectorAll('button'));
        for (var i = 0; i < btns.length; i++) {
            var b   = btns[i];
            var lbl = (b.getAttribute('aria-label') || '').toLowerCase().trim();
            var txt = (b.innerText || '').toLowerCase().trim();
            if (b.disabled) continue;
            if (
                txt === 'comment' ||
                txt === 'post' ||
                txt === 'post comment' ||
                lbl === 'comment' ||
                lbl === 'post comment' ||
                lbl === 'add comment'
            ) {
                b.click();
                return 'clicked: ' + txt;
            }
        }
        // Broadest fallback — any enabled blue/primary button in the form
        var primary = form.querySelector(
            'button.artdeco-button--primary:not([disabled])'
        );
        if (primary) { primary.click(); return 'primary-btn'; }
        return null;
    """)

    if submitted:
        print(f"      → Submit result: {submitted}")
        return True

    # Strategy 3: Ctrl+Enter — universal keyboard fallback
    try:
        ActionChains(driver).key_down(Keys.CONTROL).send_keys(
            Keys.RETURN).key_up(Keys.CONTROL).perform()
        time.sleep(0.5)
        return True
    except Exception:
        pass

    return False


def post_comment(driver, post_url, comment_text):
    """Navigate to post and post a comment. Returns True on success."""
    try:
        # ── 1. Navigate ───────────────────────────────────────────────────────
        if not safe_get(driver, post_url):
            print(f"      Could not load post URL")
            return False
        pause(3, 5)
        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(1.5)

        # ── 2. Click Comment trigger to open the editor ───────────────────────
        print(f"      → Opening comment editor...")
        clicked = _click_comment_trigger(driver)
        if not clicked:
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1)
            clicked = _click_comment_trigger(driver)

        if not clicked:
            print(f"      Comment trigger button not found")
            if not _find_comment_box(driver, timeout=3):
                return False

        # Wait for LinkedIn to open editor and DOM to stabilise
        time.sleep(2.5)

        # ── 3. Type comment ───────────────────────────────────────────────────
        print(f"      → Typing comment...")
        typed = _type_into_box(driver, comment_text)
        if not typed:
            print(f"      Could not type into comment box")
            return False

        # ── 4. CRITICAL: pause so LinkedIn's React UI activates Post button ───
        # LinkedIn's Post button stays disabled until React registers the input.
        # Without this pause it fires before the button is enabled.
        pause(2.0, 3.0)

        # ── 5. Submit — fresh DOM lookup, mirrors send_message pattern ─────────
        print(f"      → Posting comment...")
        submitted = _submit_comment(driver)

        if not submitted:
            print(f"      Post button not found — trying Ctrl+Enter")
            try:
                ActionChains(driver).key_down(Keys.CONTROL).send_keys(
                    Keys.RETURN).key_up(Keys.CONTROL).perform()
                submitted = True
            except Exception:
                pass

        # Wait for LinkedIn to process
        time.sleep(3.5)
        return bool(submitted)

    except Exception as e:
        print(f"      Post comment error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def run():
    print(f"\n{'='*55}")
    print(f"Zacharia — Autonomous Engagement Engine v2")
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Max comments: {MAX_COMMENTS_PER_RUN} | Post recency: {POST_RECENCY_HOURS}hrs")
    print(f"{'='*55}\n")

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set.")
        print("   Run: setx GROQ_API_KEY your-key-here")
        return

    # Connect to sheets
    print("📊 Connecting to sheets...")
    ws = connect_sheets()

    # Load engagement list
    people = load_engagement_list(ws)
    if not people:
        print(f"\n   No people found in '{ENGAGEMENT_LIST_SHEET}' sheet.")
        print(f"   Add people manually:")
        print(f"   Column A: Name")
        print(f"   Column B: LinkedIn URL (e.g. https://linkedin.com/in/username)")
        print(f"   Column C: Notes (optional — e.g. 'CEO at Flutterwave, posts about fintech')")
        return

    print(f"   Engagement list: {len(people)} people\n")

    # Shuffle so we don't always process in same order
    random.shuffle(people)

    driver       = create_driver()
    commented    = 0
    no_post      = 0
    already_done = 0
    skipped      = 0

    try:
        wait_for_login(driver)

        print(f"\n📋 Processing engagement list...\n")
        print("─" * 55)

        for person in people:
            if commented >= MAX_COMMENTS_PER_RUN:
                print(f"\n   Daily limit reached ({MAX_COMMENTS_PER_RUN} comments).")
                break

            name  = person["name"]
            url   = person["url"]
            notes = person["notes"]

            print(f"\n   {name}")

            # ── Driver health check — restart if browser crashed ───────────────
            if not is_driver_alive(driver):
                print(f"   ⚠️  Browser crashed — restarting...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(3)
                driver = create_driver()
                try:
                    wait_for_login(driver)
                except Exception:
                    print(f"   ❌ Could not restart browser — stopping run")
                    break

            # Get their latest post
            print(f"   → Checking for recent posts...")
            try:
                post = get_latest_post(driver, url)
            except Exception as e:
                err = str(e).lower()
                # Browser connection lost — restart and continue
                if any(x in err for x in ["10054", "connectionreset", "invalid session",
                                           "no such window", "connection aborted",
                                           "remotedisconnected"]):
                    print(f"   ⚠️  Browser crashed — restarting...")
                    try: driver.quit()
                    except Exception: pass
                    time.sleep(4)
                    driver = create_driver()
                    try: wait_for_login(driver)
                    except Exception: pass
                else:
                    print(f"   → Fetch error: {e} — skipping")
                no_post += 1
                pause(2, 4)
                continue

            if not post:
                print(f"   → No post in last {POST_RECENCY_HOURS} hours — skipping")
                update_row(ws, person["row"], "", "", "", "no_recent_post")
                no_post += 1
                pause(2, 4)
                continue

            post_id  = post["post_id"]
            age_h    = post["age_hours"]

            # Check if we already commented on this exact post
            if post_id == person["last_post_id"]:
                print(f"   → Already commented on this post — skipping")
                already_done += 1
                pause(1, 2)
                continue

            word_count = len(post['text'].split())
            print(f"   → Post found ({age_h:.0f}hrs ago) | {word_count} words")
            print(f"   → Preview: '{post['text'][:120]}...'")

            # Generate comment
            print(f"   → Generating comment...")
            comment = generate_comment(post["text"], name, notes)

            if not comment:
                print(f"   → Skipping — post not suitable for comment")
                update_row(ws, person["row"], post["url"], post_id, "", "skipped_unsuitable")
                skipped += 1
                pause(2, 4)
                continue

            print(f"   → Comment: '{comment[:80]}...'")

            # Post the comment
            print(f"   → Posting...")
            try:
                success = post_comment(driver, post["url"], comment)
            except Exception as e:
                print(f"   → Post error: {e}")
                success = False

            if success:
                commented += 1
                update_row(ws, person["row"], post["url"], post_id,
                          comment, "commented")
                print(f"   ✅ Posted ({commented}/{MAX_COMMENTS_PER_RUN})")
            else:
                print(f"   ❌ Failed to post")
                update_row(ws, person["row"], post["url"], post_id,
                          comment, "post_failed")

            # Natural pause between comments
            pause(12, 20)

        print(f"\n{'='*55}")
        print(f"✅ ENGAGEMENT ENGINE COMPLETE")
        print(f"   Comments posted:  {commented}")
        print(f"   No recent post:   {no_post}")
        print(f"   Already done:     {already_done}")
        print(f"   Skipped:          {skipped}")
        print(f"   Sheet:            {ENGAGEMENT_LIST_SHEET}")
        print(f"{'='*55}\n")

    finally:
        driver.quit()
        print("Browser closed.")


if __name__ == "__main__":
    run()
