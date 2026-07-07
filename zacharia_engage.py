"""
Zacharia — Zack.ai Commenting Agent for Users v6
==================================================
WHAT'S NEW FROM v5 (user version):
  - Complete playbook rewrite — per-tone instructions for every post type
  - CELEBRATION posts: warm and specific, never analytical
  - SARCASM posts: match the wit, play back the irony
  - FUN/PLAYFUL posts: be playful, match the energy, land a joke
  - RANT/FRUSTRATION posts: validate the specific thing, don't lecture
  - QUESTION_TO_AUDIENCE posts: answer genuinely, add your own angle
  - Questions end with ? — fixed bug that was stripping ? and replacing with .
  - Pre-filter: rejects pure promos, job posts, polls, under-40-word posts before hitting AI
  - Deeper post analysis: sarcasm, celebration, playful, rant, question-post detection
  - Smarter relevance gate: only comments on posts with real substance
  - Expanded banned phrase list — removes more LinkedIn corporate speak
  - Session cursor tracking (from v5): unchanged

Run: python zacharia_engage_user_v6.py

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
POST_FRESH_MAX_HOURS        = 6    # 0–6h  = FRESH — comment first
POST_RECENT_MAX_HOURS       = 24   # 6–24h = RECENT — comment after fresh
                                   # 24+h  = STALE  — skip entirely
POST_WINDOW_HRS             = 6    # ±hrs around typical posting time
POST_WINDOW_MIN_CONFIDENCE  = 5    # data points needed before window filter activates

SLOW_MODE = True

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LIST_HEADERS = [
    "Name",              # A  col 1
    "LinkedIn URL",      # B  col 2
    "Notes",             # C  col 3
    "Last Post URL",     # D  col 4
    "Last Post ID",      # E  col 5
    "Last Comment",      # F  col 6
    "Last Comment Date", # G  col 7
    "Status",            # H  col 8
    "Typical Post Hour", # I  col 9
    "Post Confidence",   # J  col 10
    "Last Post Time",    # K  col 11
    "Session Visited",   # L  col 12
]


# ══════════════════════════════════════════════════════════════════════════════
# COMMENTING INTELLIGENCE — v6 PLAYBOOK
# ══════════════════════════════════════════════════════════════════════════════

BASE_PLAYBOOK = """You write LinkedIn comments that sound like a sharp, observant friend who actually read the post.

════════════════════════════════════════
RULE 0 — READ THE POST BEFORE ANYTHING
════════════════════════════════════════
You will receive EXTRACTED FACTS and the FULL POST.
Read both carefully. Identify:
  1. What is the emotional tone? (celebrating, ranting, joking, reflecting, teaching, questioning)
  2. What is the ONE thing they most want someone to notice?
  3. What specific detail can you reference that proves you read it?

If you cannot find a specific detail worth referencing — output SKIP.
Never comment on something generic. Never comment on the vibe alone.

════════════════════════════════════════
ANTI-HALLUCINATION — CRITICAL
════════════════════════════════════════
Only reference things that appear in the EXTRACTED FACTS or the post text.
Never invent numbers, quotes, events, companies, or outcomes.
If the post has no specific details — SKIP. Do not improvise.

════════════════════════════════════════
READ THE POST TYPE — MATCH THE ENERGY
════════════════════════════════════════

CELEBRATION / WIN (launched, hired, closed, raised, announced, milestone):
→ Be warm and specific about the ACTUAL thing they achieved
→ Name what they did, not what they are
→ Short. 1-2 lines max.
→ NEVER: drop a lesson, add unsolicited advice, reference your own experience
→ Examples: "That client number after the year you had — well earned." 
            "Closing that round quietly and then posting about it is so you."

SARCASM / IRONY (rhetorical flip, "apparently", "turns out", self-aware joke):
→ Match the wit. Don't explain the joke.
→ Play the irony back from a different angle
→ Keep it dry. One punch line.
→ NEVER: take it literally, get earnest, over-explain
→ Examples: "Turns out doing the work works."
            "Wild concept. Someone should write a book."

FUN / PLAYFUL (lighthearted, memes, jokes, emoji-heavy, self-deprecating):
→ Be playful. Match the energy.
→ A well-placed callback, unexpected angle, or light dig lands better than a reaction
→ NEVER: turn it serious, drop insights, be a LinkedIn coach about it
→ Examples: "The confidence to post this. Respect."
            "Plot twist nobody asked for but everyone needed."

RANT / FRUSTRATION (venting, calling something out, expressing irritation):
→ Validate the SPECIFIC thing they named — don't generalise
→ Add one tight observation that sharpens their point
→ Do not tell them what to do or how to handle it
→ NEVER: silver lining, "this is why I...", unsolicited advice
→ Examples: "That specific thing is exhausting and everyone pretends it's fine."
            "The fact that this still happens in 2025 says everything."

QUESTION TO AUDIENCE (asking followers something directly):
→ Actually answer the question — with your genuine take
→ Be specific, not theoretical
→ One concrete angle, not a list
→ NEVER: ask another question back, write "great question!", be wishy-washy
→ Example: If they ask "what's your unpopular opinion on cold outreach?" — give yours.

REFLECTION / PERSONAL STORY (vulnerability, lesson from experience, something that happened):
→ Make them feel seen by naming the SPECIFIC thing in their story
→ 1-2 tight lines — warm, human, no platitudes
→ NEVER: "this resonates", "so true", unsolicited insight, make it about you
→ Examples: "That moment of realising you can't force the timing is underrated."
            "The part about the co-founder call is the part people don't talk about."

IDEA / OPINION (strong claim, contrarian take, framework, argument):
→ Engage the specific claim — sharpen it, add the flip, or add a real dimension
→ Make the comment worth reading for EVERYONE who sees it, not just the author
→ NEVER: just agree, just disagree without substance, restate their point
→ Example: "The caveat is that this only works once you've done it badly first."

HOW-TO / TACTICAL (tips, steps, process breakdown):
→ Reference one specific step — either affirm it precisely or add what's missing
→ One sharp observation, no recap
→ NEVER: "great tips!", "number 3 is my favourite", generic affirmation

════════════════════════════════════════
PICK EXACTLY ONE MOVE
════════════════════════════════════════
A. The unsaid truth — what they implied but didn't fully say
B. The flip — the other side of their point, revealed not argued
C. A lived moment — one real, tight, specific thing from experience (2 lines max)
D. Dry observation — wry reframe, lands without explaining itself
E. Make them feel seen — reflect back the specific thing that made the post worth reading
F. Sharpen it — take their idea and make it more precise, more useful, or more honest

════════════════════════════════════════
FORMAT — NON-NEGOTIABLE
════════════════════════════════════════
Max 3 lines. Each line is one sentence. Blank line between each.
Every statement ends with a full stop or exclamation mark.
Every question ends with a question mark.
Never end a statement with a question mark.
Never end a question with a full stop.
Never write a paragraph — three separate punchy lines maximum.

════════════════════════════════════════
WHEN TO USE A QUESTION
════════════════════════════════════════
Questions are allowed for moves A, B, and F only.
Only use a question when the post is intellectual or when the question genuinely opens something.
Questions must end with a question mark — not a full stop.
Max one question per comment. Never start AND end with a question.

════════════════════════════════════════
BANNED PHRASES — NEVER USE THESE
════════════════════════════════════════
resonates / this landed / so true / great post / thanks for sharing / love this
well said / powerful / inspiring / couldn't agree more / absolutely / unpacking
nuanced / framework / mindset / journey / impactful / synergy / ecosystem
as a founder / as someone who / game-changer / thoughts? / what a post
this is a reminder / couldn't have said it better / preach / facts / drop the mic
100% this / needed to hear this / bookmarking this / saving this / so important
the way you / I love how / this hit different / just what I needed / real talk
authentic / vulnerable / brave / bold move / showing up / doing the work

════════════════════════════════════════
GUARDRAILS
════════════════════════════════════════
Grief / loss / medical emergency: 1-2 warm human lines only. No insight. No lesson.
Pure promotional post (product + CTA only, no substance): SKIP
Political content: engage the human or business angle only, never the politics
Announcement with no context (just "excited to share"): SKIP
Job posting: SKIP
If nothing genuine comes to mind: SKIP — a skipped comment is always better than a generic one

════════════════════════════════════════
OUTPUT
════════════════════════════════════════
Write ONLY the comment. No preamble. No labels. No "Move:" or "Type:" prefix.
Or output: SKIP
"""


# ══════════════════════════════════════════════════════════════════════════════
# POST ANALYSIS — v6: richer tone detection
# ══════════════════════════════════════════════════════════════════════════════

def extract_post_facts(post_text):
    """
    Extracts structured facts from a post for grounding the AI prompt.
    v6 adds: sarcasm, celebration, playful, rant, question-to-audience detection.
    """
    facts = {
        "numbers":           [],
        "quotes":            [],
        "first_line":        "",
        "core_claim":        "",
        "has_story":         False,
        "has_list":          False,
        "word_count":        len(post_text.split()),
        "post_type_hint":    "",
        # v6 additions
        "is_celebration":    False,
        "is_sarcastic":      False,
        "is_playful":        False,
        "is_rant":           False,
        "is_question_post":  False,
        "emoji_count":       0,
    }

    lines = [l.strip() for l in post_text.split('\n') if l.strip()]
    if lines:
        facts["first_line"] = lines[0][:150]

    # Numbers and money
    numbers = re.findall(
        r'\$[\d,]+(?:\.\d+)?[KMBkm]?|'
        r'£[\d,]+(?:\.\d+)?[KMBkm]?|'
        r'€[\d,]+(?:\.\d+)?[KMBkm]?|'
        r'\d+(?:,\d{3})*(?:\.\d+)?%?(?:\s*(?:million|billion|thousand|k|m|b))?|'
        r'#\d+',
        post_text
    )
    facts["numbers"] = list(set(numbers))[:6]

    # Quoted phrases
    quotes = re.findall(r'["\u201c\u201d][^"\u201c\u201d]{5,80}["\u201c\u201d]', post_text)
    facts["quotes"] = quotes[:3]

    # Story markers
    story_markers = ["i was", "i remember", "last year", "last month",
                     "when i", "years ago", "i met", "i built", "i failed",
                     "yesterday", "this morning", "a few weeks ago"]
    facts["has_story"] = any(m in post_text.lower() for m in story_markers)

    # List markers
    facts["has_list"] = bool(re.search(r'^\s*\d+[\.\)]\s', post_text, re.MULTILINE))

    # Emoji count
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0\U000024C2-\U0001F251]+",
        flags=re.UNICODE
    )
    facts["emoji_count"] = len(emoji_pattern.findall(post_text))

    t = post_text.lower()

    # ── CELEBRATION / WIN detection ────────────────────────────────────────
    celebration_markers = [
        "excited to announce", "thrilled to share", "excited to share",
        "we did it", "we closed", "we launched", "we hit", "we signed",
        "officially", "just closed", "just launched", "just signed",
        "we raised", "closed our", "proud to", "honoured to", "honored to",
        "we're live", "we are live", "it's live", "it is live",
        "just got", "just hired", "just joined", "joining the team",
        "new chapter", "big news", "huge news", "milestone",
        "1 year", "2 year", "3 year", "anniversary",
        "first client", "first sale", "first hire", "sold out",
        "number 1", "#1", "record", "all-time",
    ]
    facts["is_celebration"] = any(m in t for m in celebration_markers)

    # ── SARCASM / IRONY detection ──────────────────────────────────────────
    sarcasm_markers = [
        "apparently", "turns out", "who knew", "shocking", "not surprising",
        "plot twist", "controversial opinion", "hot take", "unpopular opinion",
        "nobody talks about", "no one tells you", "they don't tell you",
        "funny how", "funny that", "wild that", "crazy how", "interesting how",
        "remind me why", "tell me why", "why does", "why do we",
        "just learned", "just realised", "just realized",
        "🙃", "😅", "😬", "🤡", "💀",
    ]
    facts["is_sarcastic"] = any(m in t for m in sarcasm_markers)

    # ── FUN / PLAYFUL detection ────────────────────────────────────────────
    playful_markers = [
        "😂", "😆", "🤣", "lol", "haha", "lmao", "💀", "🫡",
        "unpopular opinion", "controversial take", "nobody asked",
        "raise your hand", "who else", "be honest", "ngl",
        "not going to lie", "lowkey", "lowkey though",
        "this is your sign", "sending this to", "tag someone",
    ]
    facts["is_playful"] = any(m in t for m in playful_markers)
    if facts["emoji_count"] >= 4:
        facts["is_playful"] = True

    # ── RANT / FRUSTRATION detection ──────────────────────────────────────
    rant_markers = [
        "i'm tired of", "i am tired of", "fed up", "enough",
        "stop telling", "stop asking", "please stop", "can we stop",
        "why do people", "why does everyone", "the worst",
        "drives me crazy", "drives me mad", "pet peeve",
        "this needs to stop", "this has to stop", "genuinely frustrated",
        "nobody talks about", "completely wrong", "so wrong",
        "i'll say it", "i will say it", "unpopular opinion:",
        "truth is", "honest truth", "hard truth",
        "😤", "🤬", "😡",
    ]
    facts["is_rant"] = any(m in t for m in rant_markers)

    # ── QUESTION TO AUDIENCE detection ────────────────────────────────────
    question_post_markers = [
        "what do you think", "what's your", "what is your",
        "thoughts?", "agree or disagree", "yes or no",
        "what would you", "how do you", "do you think",
        "have you ever", "who else", "am i the only one",
        "let me know", "drop your", "comment below",
        "tell me in the comments",
    ]
    post_tail = t[-200:]
    facts["is_question_post"] = (
        any(m in t for m in question_post_markers) or
        (post_tail.count('?') >= 1 and len(t) > 80)
    )

    # ── CORE CLAIM ────────────────────────────────────────────────────────
    sentences = re.split(r'(?<=[.!?])\s+', post_text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    if sentences:
        facts["core_claim"] = sentences[0][:200]

    # ── POST TYPE HINT — enriched ─────────────────────────────────────────
    if facts["is_celebration"]:
        facts["post_type_hint"] = "CELEBRATION/WIN"
    elif facts["is_sarcastic"] and facts["is_playful"]:
        facts["post_type_hint"] = "SARCASM/WIT"
    elif facts["is_sarcastic"]:
        facts["post_type_hint"] = "SARCASM/IRONY"
    elif facts["is_playful"]:
        facts["post_type_hint"] = "FUN/PLAYFUL"
    elif facts["is_rant"]:
        facts["post_type_hint"] = "RANT/FRUSTRATION"
    elif facts["is_question_post"]:
        facts["post_type_hint"] = "QUESTION_TO_AUDIENCE"
    elif any(w in t for w in ["lost", "grief", "died", "cancer", "struggling",
                               "difficult time", "hard time", "heartbroken"]):
        facts["post_type_hint"] = "EMOTIONAL/PERSONAL"
    elif facts["has_story"]:
        facts["post_type_hint"] = "PERSONAL_STORY"
    elif any(w in t for w in ["how to", "step 1", "tips:", "here's what",
                               "the secret", "here are", "things i learned"]):
        facts["post_type_hint"] = "HOW-TO/TACTICAL"
    elif any(w in t for w in ["i think", "i believe", "unpopular", "controversial",
                               "hot take", "opinion:", "the truth is"]):
        facts["post_type_hint"] = "IDEA/OPINION"
    else:
        facts["post_type_hint"] = "GENERAL"

    return facts


# ══════════════════════════════════════════════════════════════════════════════
# POST RELEVANCE FILTER — v6: pre-AI gate
# ══════════════════════════════════════════════════════════════════════════════

def is_post_worth_commenting(post_text, facts):
    """
    Fast pre-filter before hitting the AI.
    Returns (worth_commenting: bool, skip_reason: str).
    Rejects low-value posts before burning API tokens.
    """
    t = post_text.lower().strip()
    word_count = len(post_text.split())

    # Too short to have substance
    if word_count < 40:
        return False, f"too short ({word_count} words)"

    # Pure job posting
    job_markers = [
        "we're hiring", "we are hiring", "now hiring", "join our team",
        "open role", "open position", "job opportunity", "we have an opening",
        "apply now", "apply here", "send your cv", "send your resume",
        "dm me your cv", "dm your resume", "link in bio to apply",
        "hiring for a", "looking for a", "we need a",
    ]
    job_hit = sum(1 for m in job_markers if m in t)
    if job_hit >= 2:
        return False, "job posting"

    # Pure promotional — product/service CTA with no personal substance
    promo_markers = [
        "link in bio", "link in comments", "comment below to get",
        "dm me to get", "grab yours", "shop now", "buy now",
        "limited spots", "limited time", "enrol now", "enroll now",
        "sign up now", "register now", "book your spot",
        "click the link", "swipe up", "check the link",
    ]
    promo_hits = sum(1 for m in promo_markers if m in t)
    if promo_hits >= 2 and word_count < 80:
        return False, "pure promotional post"

    # Pure poll (just a question + vote options, no substance)
    poll_markers = ["option a:", "option b:", "option 1:", "option 2:",
                    "vote below", "poll:", "your vote:", "cast your vote"]
    if any(m in t for m in poll_markers) and word_count < 60:
        return False, "poll with no substance"

    # Repost / share with no commentary
    share_markers = [
        "reposting this", "sharing this because", "worth resharing",
        "credit:", "via:", "h/t:", "ht:", "originally posted by",
    ]
    if any(m in t for m in share_markers) and word_count < 50:
        return False, "reshare with no original content"

    # Generic motivational filler with no specific content
    filler_markers = [
        "have a blessed", "good morning linkedin", "happy monday",
        "wishing everyone", "sending positive", "stay motivated",
        "believe in yourself", "you got this", "keep going",
    ]
    filler_hits = sum(1 for m in filler_markers if m in t)
    if filler_hits >= 2:
        return False, "generic motivational filler"

    return True, "ok"


def build_grounded_prompt(post_text, person_name, person_notes, facts):
    """
    Build the AI prompt with grounding facts clearly structured.
    v6: richer facts block including tone signals.
    """
    facts_block = []

    # Core content facts
    if facts["first_line"]:
        facts_block.append(f"Opening line: \"{facts['first_line']}\"")
    if facts["core_claim"] and facts["core_claim"] != facts["first_line"]:
        facts_block.append(f"Core claim: \"{facts['core_claim'][:150]}\"")
    if facts["numbers"]:
        facts_block.append(f"Numbers/stats in post: {', '.join(facts['numbers'][:4])}")
    if facts["quotes"]:
        facts_block.append(f"Direct quotes: {' | '.join(facts['quotes'][:2])}")
    if facts["has_story"]:
        facts_block.append("Post contains: a personal story or experience")
    if facts["has_list"]:
        facts_block.append("Post contains: a numbered list")

    # Tone signals — tell the AI what energy to match
    if facts["post_type_hint"]:
        facts_block.append(f"Post type / tone: {facts['post_type_hint']}")
    if facts["is_celebration"]:
        facts_block.append("Tone signal: CELEBRATING A WIN — be warm and specific, no lessons")
    if facts["is_sarcastic"]:
        facts_block.append("Tone signal: SARCASTIC/IRONIC — match the wit, play back the irony")
    if facts["is_playful"]:
        facts_block.append("Tone signal: PLAYFUL/FUN — match the energy, land a joke or callback")
    if facts["is_rant"]:
        facts_block.append("Tone signal: VENTING/RANT — validate the specific thing, no advice")
    if facts["is_question_post"]:
        facts_block.append("Tone signal: ASKING AUDIENCE — actually answer the question they asked")
    if facts["emoji_count"] >= 4:
        facts_block.append(f"Tone signal: emoji-heavy post ({facts['emoji_count']} emojis) — lighter energy")

    facts_section = "\n".join(f"  • {f}" for f in facts_block)

    return (
        f"Post by: {person_name}\n"
        f"About them: {person_notes or 'not provided'}\n\n"
        f"GROUNDING FACTS — only reference things that appear here or in the post:\n"
        f"{facts_section}\n\n"
        f"FULL POST TEXT:\n\"\"\"\n{post_text[:2000]}\n\"\"\"\n\n"
        f"Write ONLY the comment (or SKIP). No preamble. No labels."
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
    """
    Generate a comment using the AI.
    v6 fixes:
    - Questions keep their ? — no longer stripped and converted to statements
    - Richer banned phrase list
    - Tighter quality guard
    """
    if _retries >= 3:
        return None

    model = _model or "llama-3.3-70b-versatile"
    try:
        client = Groq(api_key=GROQ_API_KEY)
        facts  = extract_post_facts(post_text)
        system = USER_PLAYBOOK if USER_PLAYBOOK.strip() else BASE_PLAYBOOK
        prompt = build_grounded_prompt(post_text, person_name, person_notes, facts)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.88,
            max_tokens=200,
        )

        comment = response.choices[0].message.content.strip().strip('"\'')

        if not comment or comment.upper().startswith("SKIP"):
            return None

        # ── Strip leaked preamble labels ──────────────────────────────────
        for prefix in [
            "STEP 1", "Post type:", "Type:", "FUNNY", "EMOTIONAL", "CELEBRATION",
            "SARCASM", "RANT", "PLAYFUL", "INTELLECTUAL", "HOW-TO", "ACHIEVEMENT",
            "OPINION", "Move:", "GENERAL", "FUN/", "QUESTION"
        ]:
            if comment.startswith(prefix):
                parts = comment.split("\n\n", 1)
                if len(parts) > 1:
                    comment = parts[1].strip()
                else:
                    # Strip the label line
                    comment = re.sub(r'^[A-Z][A-Z /\-]+:?\s*\n', '', comment).strip()

        # ── Fix punctuation on each line ──────────────────────────────────
        # v6: Questions keep their ? — ONLY fix statements missing punctuation
        lines = [l.strip() for l in comment.split('\n\n') if l.strip()]
        fixed = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.endswith(('.', '!', '?')):
                # Already properly punctuated — leave it alone
                fixed.append(line)
            else:
                # Missing punctuation — determine if it reads as a question
                is_question = (
                    line.lower().startswith(("what ", "why ", "how ", "when ", "where ",
                                            "who ", "is ", "are ", "do ", "does ",
                                            "can ", "could ", "would ", "should "))
                    and any(q_word in line.lower() for q_word in
                            ["what", "why", "how", "when", "where", "who"])
                )
                line += '?' if is_question else '.'
                fixed.append(line)

        comment = '\n\n'.join(fixed)

        if not comment:
            return None

        # ── Expanded banned phrase check ──────────────────────────────────
        banned = [
            # Original list
            "resonates", "this landed", "so true", "great post",
            "thanks for sharing", "love this", "well said", "powerful",
            "inspiring", "couldn't agree more", "absolutely", "unpacking",
            "nuanced", "mindset", "journey", "impactful", "synergy",
            "ecosystem", "as a founder", "as someone", "what a ",
            "this is a reminder", "game-changer",
            # v6 additions
            "couldn't have said", "preach", "facts!", "drop the mic",
            "100% this", "needed to hear", "bookmarking", "saving this",
            "so important", "the way you", "this hit different",
            "just what i needed", "real talk", "authentic", "vulnerable",
            "brave of you", "bold move", "showing up", "doing the work",
            "legend", "king", "queen", "icon", "💯",
            "spot on", "nail on the head", "hit the nail",
            "you nailed", "nailed it", "crushed it",
            "this is gold", "this is fire", "fire post",
            "underrated post", "underrated take",
            "this deserves more", "more people need",
            "everyone needs to read", "sharing this",
        ]
        comment_lower = comment.lower()
        if any(p in comment_lower for p in banned):
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)

        # ── Format: ensure proper line breaks if AI returned a block ──────
        if "\n\n" not in comment and len(comment.split(". ")) >= 2:
            sentences = []
            parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', comment)
            for s in parts:
                s = s.strip()
                if s:
                    sentences.append(s)
            if len(sentences) > 1:
                comment = "\n\n".join(sentences)

        # ── Length guard ──────────────────────────────────────────────────
        words = comment.replace("\n", " ").split()
        if len(words) < 4:
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)
        if len(words) > 100:
            # Trim to first 2 lines
            trimmed_lines = comment.split("\n\n")[:2]
            comment = "\n\n".join(trimmed_lines)
            words = comment.replace("\n", " ").split()
            if len(words) < 4:
                return None

        # ── Don't let it end with a comma or colon ────────────────────────
        if comment.endswith((',', ':')):
            comment = comment[:-1] + '.'

        return comment

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate_limit_exceeded" in err_str:
            wait = _parse_retry_after(err_str)
            if "tokens per day" in err_str.lower() and wait > 600:
                if model == "llama-3.3-70b-versatile":
                    print(f"      70b daily limit — switching to 8b")
                    return generate_comment(post_text, person_name, person_notes,
                                            _model="llama-3.1-8b-instant", _retries=_retries)
                return None
            print(f"      Rate limited — waiting {wait:.0f}s...")
            time.sleep(wait)
            return generate_comment(post_text, person_name, person_notes,
                                    _model=model, _retries=_retries + 1)
        print(f"      AI error: {e}")
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
            print("   Already logged in!")
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
                print("   Logged in — continuing...")
            return True
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
            except Exception:
                ws = wb.add_worksheet(title=ENGAGEMENT_LIST_SHEET, rows=500, cols=13)
                ws.append_row(LIST_HEADERS)
                ws.freeze(rows=1)
                print(f"   Created sheet: '{ENGAGEMENT_LIST_SHEET}'")

            _ensure_session_col(ws)
            return ws

        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(3 * attempt)
                continue
            break
    raise RuntimeError(f"Cannot connect to Google Sheets: {last_err}")


def _ensure_session_col(ws):
    try:
        headers = ws.row_values(1)
        if len(headers) < 12 or not headers[11].strip():
            ws.update_cell(1, 12, "Session Visited")
            print("   Added 'Session Visited' column (L) to sheet header")
    except Exception as e:
        print(f"   Note: could not verify session column: {e}")


def load_engagement_list(ws):
    try:
        all_rows = ws.get_all_values()
        if not all_rows:
            return []
        people = []
        for i, row in enumerate(all_rows[1:], start=2):
            row = row + [""] * 13
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
                "row":             i,
                "name":            name,
                "url":             url,
                "notes":           (row[2] or "").strip(),
                "last_post_url":   (row[3] or "").strip(),
                "last_post_id":    (row[4] or "").strip(),
                "last_comment":    (row[5] or "").strip(),
                "last_date":       (row[6] or "").strip(),
                "status":          (row[7] or "").strip(),
                "typical_hour":    typical_hour,
                "confidence":      confidence,
                "last_post_time":  (row[10] or "").strip(),
                "session_visited": (row[11] or "").strip(),
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


def update_timing(ws, row_num, post_hour_utc, current_confidence, post_dt_str):
    try:
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
            a_old = current_hour  * (2 * math.pi / 24)
            a_new = post_hour_utc * (2 * math.pi / 24)
            sin_a = (math.sin(a_old) * w_old + math.sin(a_new) * w_new) / w_tot
            cos_a = (math.cos(a_old) * w_old + math.cos(a_new) * w_new) / w_tot
            new_hour = int((math.atan2(sin_a, cos_a) * 24 / (2 * math.pi)) % 24)

        ws.update_cell(row_num, 9,  str(new_hour))
        ws.update_cell(row_num, 10, str(current_confidence + 1))
        ws.update_cell(row_num, 11, post_dt_str)
    except Exception as e:
        print(f"      Timing update error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION TRACKING — col L
# ══════════════════════════════════════════════════════════════════════════════

def already_visited_this_session(person, today_str):
    sv = person.get("session_visited", "") or ""
    return sv.startswith(today_str)


def mark_session_visited(ws, row_num):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        ws.update_cell(row_num, 12, now_str)
    except Exception as e:
        print(f"      Session mark error: {e}")


def already_commented_today(person, today_str):
    last = person.get("last_date", "") or ""
    return last.startswith(today_str)


# ══════════════════════════════════════════════════════════════════════════════
# WINDOW FILTER
# ══════════════════════════════════════════════════════════════════════════════

def in_posting_window(person, current_hour_utc):
    confidence   = person.get("confidence", 0)
    typical_hour = person.get("typical_hour")

    if confidence < POST_WINDOW_MIN_CONFIDENCE or typical_hour is None:
        return True, f"learning ({confidence}/{POST_WINDOW_MIN_CONFIDENCE} pts)"

    diff = min(
        abs(current_hour_utc - typical_hour),
        24 - abs(current_hour_utc - typical_hour)
    )
    if diff <= POST_WINDOW_HRS:
        return True, f"in window (posts ~{typical_hour:02d}:xx UTC ±{POST_WINDOW_HRS}h)"

    open_h  = (typical_hour - POST_WINDOW_HRS) % 24
    close_h = (typical_hour + POST_WINDOW_HRS) % 24
    return False, f"posts ~{typical_hour:02d}:xx UTC (window {open_h:02d}–{close_h:02d})"


# ══════════════════════════════════════════════════════════════════════════════
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
        username     = profile_url.rstrip("/").split("/in/")[-1].split("/")[0].split("?")[0]
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
                '.feed-shared-update-v2, .occludable-update'
            );
            for (var i = 0; i < Math.min(containers.length, 8); i++) {
                var el = containers[i];
                var textEl = (
                    el.querySelector('.update-components-text') ||
                    el.querySelector('.feed-shared-text span[dir="ltr"]') ||
                    el.querySelector('.feed-shared-text') ||
                    el.querySelector('.break-words span[dir="ltr"]')
                );
                var text = textEl ? textEl.innerText.trim() : '';
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
        url  = post.get("url", "") or activity_url
        ts   = post.get("ts", "")

        if not text or len(text) < 80:
            return None

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
        var bar = document.querySelector('.social-actions, .feed-shared-social-action-bar');
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
            var b   = btns[i];
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
        print(f"      Post comment error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# COLOUR HELPERS
# ══════════════════════════════════════════════════════════════════════════════
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    def GREEN(t):  return Fore.GREEN  + str(t) + Style.RESET_ALL
    def YELLOW(t): return Fore.YELLOW + str(t) + Style.RESET_ALL
    def DIM(t):    return Style.DIM   + str(t) + Style.RESET_ALL
    def CYAN(t):   return Fore.CYAN   + str(t) + Style.RESET_ALL
except Exception:
    def GREEN(t):  return str(t)
    def YELLOW(t): return str(t)
    def DIM(t):    return str(t)
    def CYAN(t):   return str(t)


def age_label(hours):
    if hours < 1:                       return GREEN("just now  🔥")
    if hours < POST_FRESH_MAX_HOURS:    return GREEN(f"{hours:.0f}h ago  🔥 FRESH")
    if hours < POST_RECENT_MAX_HOURS:   return YELLOW(f"{hours:.0f}h ago  ⏱ RECENT")
    return DIM(f"{hours:.0f}h ago  — stale")


def tone_label(facts):
    """Returns a coloured tone indicator for the console."""
    t = facts.get("post_type_hint", "")
    if "CELEBRATION" in t:   return GREEN(f"🎉 {t}")
    if "SARCASM"     in t:   return CYAN(f"🙃 {t}")
    if "PLAYFUL"     in t:   return CYAN(f"😄 {t}")
    if "RANT"        in t:   return YELLOW(f"😤 {t}")
    if "QUESTION"    in t:   return CYAN(f"❓ {t}")
    if "PERSONAL"    in t:   return YELLOW(f"💬 {t}")
    if "HOW-TO"      in t:   return GREEN(f"📋 {t}")
    if "IDEA"        in t:   return CYAN(f"💡 {t}")
    return DIM(f"📄 {t}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — v6: smarter commenting with pre-filter and tone matching
# ══════════════════════════════════════════════════════════════════════════════
def run():
    now_utc  = datetime.now(timezone.utc)
    today    = now_utc.strftime("%Y-%m-%d")
    cur_hour = now_utc.hour
    name_display = CLIENT_FIRST_NAME or CLIENT_NAME or "Zack User"

    print(f"\n{'='*60}")
    print(f"  Zacharia — Commenting Agent v6 for Users")
    print(f"  Running for: {name_display}")
    print(f"  {now_utc.strftime('%Y-%m-%d %H:%M UTC')}  |  Max: {MAX_COMMENTS_PER_RUN} comments")
    print(f"  Fresh: 0-{POST_FRESH_MAX_HOURS}h  |  Recent: {POST_FRESH_MAX_HOURS}-{POST_RECENT_MAX_HOURS}h  |  Window: ±{POST_WINDOW_HRS}h")
    print(f"  Mode: SESSION-CURSOR + TONE-AWARE + PRE-FILTER")
    print(f"{'='*60}\n")

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in zack_config.py")
        print("   Run: python zack_setup.py to reconfigure")
        return

    print("📊 Connecting to sheets...")
    ws = connect_sheets()

    people = load_engagement_list(ws)
    if not people:
        print(f"   No people in '{ENGAGEMENT_LIST_SHEET}'.")
        return
    print(f"   {len(people)} people in engagement list\n")

    # ── Filter 1: Already commented today ─────────────────────────────────
    commented_today = [p for p in people if already_commented_today(p, today)]
    not_commented   = [p for p in people if not already_commented_today(p, today)]

    # ── Filter 2: Session cursor ───────────────────────────────────────────
    not_yet_visited = [p for p in not_commented if not already_visited_this_session(p, today)]
    visited_session = [p for p in not_commented if already_visited_this_session(p, today)]

    # ── Filter 3: Posting window ───────────────────────────────────────────
    in_window  = []
    off_window = []
    for p in not_yet_visited:
        in_win, reason = in_posting_window(p, cur_hour)
        if in_win:
            in_window.append((p, reason))
        else:
            off_window.append((p, reason))

    known    = [(p, r) for p, r in in_window if p.get("confidence", 0) >= POST_WINDOW_MIN_CONFIDENCE]
    learners = [(p, r) for p, r in in_window if p.get("confidence", 0) < POST_WINDOW_MIN_CONFIDENCE]
    to_visit = known + learners

    full_cycle_complete = (len(not_yet_visited) == 0 and len(off_window) == 0)

    print(f"🕐 {now_utc.strftime('%H:%M UTC')}  |  {today}")
    print(f"   ✅ Commented today (done)       : {len(commented_today)}")
    print(f"   🔄 Visited this session (skip)  : {len(visited_session)}")
    print(f"   ⏭  Off posting window           : {len(off_window)}")
    print(f"   🎯 Not yet visited this session : {len(not_yet_visited)}")
    print(f"      └─ In window (will visit)    : {len(in_window)}")
    print(f"   🔍 Queue this run               : {len(to_visit)}\n")

    if full_cycle_complete:
        print("   ✅ FULL CYCLE COMPLETE for today.")
        print("   Every profile visited. Resets automatically tomorrow.")
        print("   To force a fresh cycle: clear column L in the sheet.")
        return

    if not to_visit:
        print("   Nothing to visit this run.")
        if off_window:
            earliest_open = None
            for p, _ in off_window:
                th = p.get("typical_hour")
                if th is not None:
                    open_h = (th - POST_WINDOW_HRS) % 24
                    if earliest_open is None or open_h < earliest_open:
                        earliest_open = open_h
            if earliest_open is not None:
                print(f"   Next window opens around {earliest_open:02d}:00 UTC")
        return

    # ── OPEN BROWSER ──────────────────────────────────────────────────────
    driver    = create_driver()
    commented = 0
    no_post   = 0
    already   = 0
    stale     = 0
    unsuitable   = 0
    pre_filtered = 0
    n_visited_this_run = 0

    try:
        if not wait_for_login(driver):
            print("❌ Login timed out — stopping")
            return

        print(f"\n{'─'*60}")
        print(f"🔍 Visiting {len(to_visit)} profiles...\n")

        for person, win_reason in to_visit:
            if commented >= MAX_COMMENTS_PER_RUN:
                print(f"\n   ✅ Limit reached ({MAX_COMMENTS_PER_RUN} comments) — stopping.")
                print(f"   Next run continues from: {person['name']}")
                break

            name  = person["name"]
            url   = person["url"]
            notes = person.get("notes", "")
            conf  = person.get("confidence", 0)

            print(f"  {name}  [{win_reason}]")

            # ── Mark visited BEFORE browser (session cursor) ───────────────
            mark_session_visited(ws, person["row"])
            n_visited_this_run += 1

            # ── Browser health check ───────────────────────────────────────
            if not is_driver_alive(driver):
                print(f"   ⚠  Browser crashed — restarting...")
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(3)
                driver = create_driver()
                if not wait_for_login(driver):
                    print("   ❌ Login timed out — stopping")
                    break

            # ── Fetch post ────────────────────────────────────────────────
            print(f"   → Fetching post...")
            try:
                post = get_latest_post(driver, url)
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["connectionreset","10054","invalid session",
                                           "no such window","connection aborted"]):
                    print(f"   ⚠  Browser crashed — restarting...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    time.sleep(4)
                    driver = create_driver()
                    wait_for_login(driver)
                else:
                    print(f"   → Error: {e}")
                no_post += 1
                pause(2, 4)
                continue

            if not post:
                print(f"   → No post in last {POST_RECENCY_HOURS}h")
                update_row(ws, person["row"], "", "", "", "no_recent_post")
                no_post += 1
                pause(2, 4)
                continue

            age_h   = post["age_hours"]
            post_id = post["post_id"]

            # ── Update timing intelligence ─────────────────────────────────
            try:
                post_time = datetime.now(timezone.utc) - timedelta(hours=age_h)
                update_timing(ws, person["row"], post_time.hour,
                              conf, post_time.strftime("%Y-%m-%d %H:%M"))
            except Exception:
                pass

            # ── Never comment twice on the same post ───────────────────────
            if post_id == person.get("last_post_id", ""):
                print(f"   → Already commented on this exact post — skipping")
                already += 1
                pause(1, 2)
                continue

            # ── Age gate ───────────────────────────────────────────────────
            if age_h > POST_RECENT_MAX_HOURS:
                print(f"   → {age_h:.0f}h — too stale, skipping")
                stale += 1
                update_row(ws, person["row"], post["url"], post_id, "", "stale_skipped")
                pause(1, 2)
                continue

            # ── v6 PRE-FILTER: check if post is worth commenting on ────────
            facts = extract_post_facts(post["text"])
            worth_it, skip_reason = is_post_worth_commenting(post["text"], facts)
            if not worth_it:
                print(f"   → Pre-filter: {skip_reason} — skipping without AI call")
                update_row(ws, person["row"], post["url"], post_id, "", f"pre_filtered:{skip_reason}")
                pre_filtered += 1
                pause(1, 2)
                continue

            # ── Show what we detected ──────────────────────────────────────
            print(f"   → {len(post['text'].split())} words | {age_label(age_h)} | {tone_label(facts)}")
            print(f"   → '{post['text'][:80]}...'")

            # ── Generate comment ───────────────────────────────────────────
            print(f"   → Generating comment...")
            comment = generate_comment(post["text"], name, notes)

            if not comment:
                print(f"   → Not suitable — skipping")
                update_row(ws, person["row"], post["url"], post_id, "", "skipped_unsuitable")
                unsuitable += 1
                pause(2, 4)
                continue

            freshness = "🔥 FRESH" if age_h <= POST_FRESH_MAX_HOURS else "⏱ RECENT"
            print(f"   → [{freshness}] {comment[:80]}...")

            # ── Post comment ───────────────────────────────────────────────
            print(f"   → Posting...")
            try:
                success = post_comment(driver, post["url"], comment)
            except Exception as e:
                print(f"   → Error: {e}")
                success = False

            if success:
                commented += 1
                update_row(ws, person["row"], post["url"], post_id, comment, "commented")
                print(f"   ✅ Done ({commented}/{MAX_COMMENTS_PER_RUN})\n")
            else:
                print(f"   ❌ Failed\n")
                update_row(ws, person["row"], post["url"], post_id, comment, "post_failed")

            pause(10, 16)

        # ── Summary ────────────────────────────────────────────────────────
        remaining = len(not_yet_visited) - n_visited_this_run
        print(f"{'='*60}")
        print(f"✅ RUN COMPLETE — v6")
        print(f"   Comments posted           : {commented}")
        print(f"   Profiles visited this run : {n_visited_this_run}")
        print(f"   Pre-filtered (no AI used) : {pre_filtered}")
        print(f"   No post found             : {no_post}")
        print(f"   Already on this post      : {already}")
        print(f"   Stale (>{POST_RECENT_MAX_HOURS}h)              : {stale}")
        print(f"   Unsuitable (AI skipped)   : {unsuitable}")
        print(f"")
        print(f"   Session cursor:")
        print(f"   Already commented today   : {len(commented_today)}")
        print(f"   Visited this session      : {len(visited_session) + n_visited_this_run}")
        print(f"   Still unvisited today     : {max(0, remaining)}")
        print(f"   Off posting window        : {len(off_window)}")

        if remaining > 0:
            print(f"\n   ▶  Run again — {remaining} profiles still unvisited this session.")
        elif len(off_window) > 0:
            print(f"\n   ⏱  {len(off_window)} profiles off-window — run later to catch them.")
        else:
            print(f"\n   ✅ Full cycle complete. Resets tomorrow.")

        print(f"{'='*60}\n")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print("Browser closed.")


if __name__ == "__main__":
    run()
