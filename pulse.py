#!/usr/bin/env python3
"""
Pulse ,Signal Analyst Agent (Layer 3)
Reads subreddits.json, fetches RSS, scores buying signals, saves report.
"""

import os
import re
import sys
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
import anthropic

from clusters import product_to_cluster

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
SUBREDDITS_FILE = "/root/clearfolks/subreddits.json"
SIGNALS_DIR = "/root/clearfolks/signals"
LOGS_DIR = "/root/clearfolks/logs"
PRODUCTS_FILE = "/root/clearfolks/products.json"
BLOG_BASE_URL = "https://blog.clearfolks.com"


# ── Subreddit tier policy ─────────────────────────────────────────────────────
# Tier 1 = large, strict-moderation subs that remove any post containing a URL
# as a Rule 7 (self-promotion) violation. We post a link-free reply ending with
# a DM invitation. Match is case-insensitive on the bare name (no "r/" prefix).
TIER_1_SUBREDDITS = {
    "weddingplanning",
    "mealprepsunday",
    "beyondthebump",
    "homeschool",
    "specialeducation",
    "caregivers",
    "moving",
    "etsy",
    "dogs",
    "cats",
}

# Variety pool for the link-free tier-1 close. Picked deterministically per
# signal so the same signal_id always renders the same close, and so two
# adjacent signals get different closes.
TIER1_CLOSES = [
    "lmk if you want more info",
    "happy to share more if useful",
]

# Variety pool for the natural-URL tier-2 close. The URL is the LAST thing in
# the sentence, never on its own labeled line.
TIER2_CLOSES = [
    "its on etsy if you want to check it out: {url}",
    "built it and put it on etsy if thats useful: {url}",
    "on etsy if you want to look: {url}",
]


# ── Daily/weekly discussion threads ──────────────────────────────────────────
# Some strict tier-1 subs run a recurring megathread where self-promotion is
# allowed. When a signal lands in one of these subs, we generate a second
# version of the copy: a short on-thread promo post the user can drop into
# the megathread (separate action from the no-link reply on the OP).
KNOWN_DISCUSSION_THREADS = {
    "weddingplanning":  "Daily Discussion Chat",
    "beyondthebump":    "Weekly Discussion Thread",
    "homeschool":       "Weekly Share Thread",
    "mealprepsunday":   "Daily Discussion",
    "caregivers":       "Weekly Support Thread",
    "etsy":             "Weekly Sharing Thread",
    "dogs":             "Daily Discussion Thread",
    "cats":             "Daily Discussion Thread",
}


def discussion_thread_for(subreddit: str) -> str | None:
    """Return the megathread title for a sub, or None if no known thread."""
    return KNOWN_DISCUSSION_THREADS.get(_normalize_subreddit(subreddit))


# Product names that read awkwardly when lowercased and used as descriptors
# ("Caregiver Command Center app" sounds weird). Override with something
# natural-sounding. Everything else falls back to lowercased product name
# minus a trailing " App" suffix.
PRODUCT_DESCRIPTORS = {
    "Caregiver Command Center":     "caregiver organizer",
    "Caregiver Organizer App":      "caregiver organizer",
    "Etsy Seller Business System":  "etsy seller tracker",
    "IEP Parent Binder":            "iep parent binder",
    "IEP Meeting Prep Kit":         "iep meeting prep",
}


def product_descriptor(product: str) -> str:
    """Turn a product name into the short descriptor used by the megathread
    promo post: 'Wedding Planning App' → 'wedding planning'."""
    p = (product or "").replace("Upcoming:", "").strip()
    if p in PRODUCT_DESCRIPTORS:
        return PRODUCT_DESCRIPTORS[p]
    return p.lower().removesuffix(" app").strip()


def build_discussion_post(product: str, etsy_url: str) -> str:
    """The short promo text to drop into a sub's daily/weekly discussion
    megathread. Lowercase, lifestyle-Reddit voice, URL embedded as its own
    sentence-ending element (not labeled). No em dashes, no semicolons."""
    if not etsy_url:
        return ""
    d = product_descriptor(product)
    if not d:
        return ""
    article = "an" if d[0] in "aeiou" else "a"
    return (
        f"built {article} {d} app, on etsy for $9.99. "
        f"works offline, one payment. {etsy_url}. "
        f"happy to answer questions"
    )


def _normalize_subreddit(name: str) -> str:
    """'r/WeddingPlanning' → 'weddingplanning' for tier lookup."""
    n = (name or "").strip().lower()
    if n.startswith("r/"):
        n = n[2:]
    return n


def subreddit_tier(subreddit: str) -> int:
    """1 for strict subs (no URL allowed), 2 for everywhere else."""
    return 1 if _normalize_subreddit(subreddit) in TIER_1_SUBREDDITS else 2


def _load_etsy_urls_by_product() -> dict:
    """Map product name (and a few aliases) → Etsy listing URL. Mirrors the
    helper in pinterest_poster but kept local so pulse has no cross-module
    side effects at import time."""
    try:
        with open(PRODUCTS_FILE) as f:
            data = json.load(f)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for p in data.get("products", []):
        url = p.get("etsy_url", "")
        name = p.get("name", "")
        if not url or not name:
            continue
        variants = {name, name.removesuffix(" App").strip()}
        # & / "and" interchange
        for n in list(variants):
            if "&" in n:
                variants.add(n.replace("&", "and"))
            if " and " in n:
                variants.add(n.replace(" and ", " & "))
        for v in variants:
            if v:
                out[v] = url
    return out


_ETSY_URLS = _load_etsy_urls_by_product()


def etsy_url_for_product(product: str) -> str:
    """Resolve a product_match string ('Upcoming: Wedding Planning App') to
    its Etsy listing URL. Returns '' if not found."""
    if not product:
        return ""
    p = product.replace("Upcoming:", "").strip()
    if p in _ETSY_URLS:
        return _ETSY_URLS[p]
    base = p.removesuffix(" App").strip()
    return _ETSY_URLS.get(base, "")


# Sentence-final phrases that signal a "soft close" we want to strip and
# replace with the tier-appropriate one. Match is substring + case-insensitive.
_CLOSE_MARKERS = (
    "on etsy",
    "lmk if",
    "want the link",
    "share the link",
    "if useful",
    "if helpful",
    "if that helps",
    "if thats useful",
    "happy to share",
    "more info",
)


def _strip_trailing_close(reply: str) -> str:
    """Drop any trailing sentence that reads like a soft close so we can append
    a tier-appropriate one without doubling up."""
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    while sentences:
        last = sentences[-1].lower()
        if any(m in last for m in _CLOSE_MARKERS):
            sentences.pop()
        else:
            break
    body = " ".join(sentences).rstrip()
    # Drop trailing punctuation so the new close adds its own.
    body = body.rstrip(".!? ,")
    return body


def rewrite_reply_for_tier(reply: str, tier: int, etsy_url: str,
                           signal_id: str | None = None) -> str:
    """Strip the model's soft close and append a tier-appropriate one.

    Tier 1: no URL anywhere — closes with a DM invitation.
    Tier 2: URL embedded naturally in the last sentence.

    signal_id is used as a stable seed so the same signal always renders the
    same close, and adjacent signals get visual variety."""
    body = _strip_trailing_close(reply or "")
    if not body:
        body = (reply or "").strip().rstrip(".!? ,")

    seed = abs(hash(signal_id or body)) if signal_id else abs(hash(body))

    if tier == 1 or not etsy_url:
        close = TIER1_CLOSES[seed % len(TIER1_CLOSES)]
    else:
        close = TIER2_CLOSES[seed % len(TIER2_CLOSES)].format(url=etsy_url)

    # Reattach with a period + space, lowercase first letter of close to stay
    # in the texting-style voice the prompt already enforces.
    return f"{body}. {close}"

SIGNAL_PROMPT = """You are Pulse, a buying signal analyst for Clearfolks Templates, an Etsy store selling lightweight digital organizer apps.

Our products are lightweight web apps installed to phone home screen. Works offline. One payment, lifetime access, no subscription. Shareable across household.

Current products:
- Caregiver Organizer App
- Etsy Seller Organizer App

Upcoming products (flag signals for these too):
- Wedding Planning App
- Homeschool Planner App
- Pet Care Organizer App
- Meal Planner and Grocery App
- Moving Day Organizer App
- Baby Tracker and Postpartum App
- Travel Planner App

STRICT EXCLUSION RULES:
- No professional or paid workers (nurses, teachers in professional context, real estate agents)
- No pure venting with zero intent to find a tool
- No posts older than 7 days

HIGH INTENT signals are people who:
- Are overwhelmed and actively seeking a system or tool
- Express frustration with disorganization, things falling through cracks
- Ask for app, tracker, planner or organizer recommendations
- Mention coordinating with multiple family members

Score 1-10. Only include posts scoring 6 or above.

REPLY COPY RULES (apply to "suggested_response", non-negotiable).

THE BIGGEST TELL THAT TEXT WAS WRITTEN BY AI IS THE EM DASH CHARACTER. NEVER USE IT. NOT ONCE. NOT EVER.

THE REDDIT HUMAN TEST (overrides everything else):
The suggested_response must pass the Reddit human test. If a moderator read this reply they should not be able to tell it was written by AI. It reads like a real person who personally hit the same problem and found something that helped. Not a founder. Not a marketer. A neighbor.

ABSOLUTE PUNCTUATION BANS (any single occurrence = total failure):
- NO em dashes. The character "—" is BANNED. Never use it.
- NO en dashes either. The character "–" is BANNED.
- NO semicolons. The character ";" is BANNED.
- NO oxford commas. "vendors, budget, guest list and tasks" is right. "vendors, budget, guest list, and tasks" is WRONG. Drop the comma before "and" in lists of three or more.
- NO bullet points, no numbered lists, no headings, no markdown.
- NO exclamation marks.
- NO ellipses "...".

INSTEAD USE:
- plain commas
- periods, then a new sentence
- the word "and" where you'd be tempted to use a semicolon or em dash
- line breaks between thoughts
- simple short sentences

VOICE:
- lowercase is fine, even preferred. Real Reddit users don't capitalize the start of every sentence.
- short abbreviations are fine: "w" for "with", "lmk" for "let me know", "tbh", "imo", "rn".
- contractions everywhere: "thats", "whos", "youre", "dont" without apostrophes is fine too.
- short words, short sentences.
- the tone is "neighbor who found something useful", never "founder pitching".

LENGTH:
- Max 3 sentences. 2 is fine. Never 4+.

STRUCTURE (flexible, not strict):
- Optional opener that nods to their specific situation. Keep it under 8 words. Examples: "dealt w this same chaos.", "been there.", "this is rough especially solo.". You can also skip this entirely and dive straight in.
- Core sentence: what it does. Start with "built something for this", "built a [tracker/planner/organizer] for this", or "put together a [thing] that...". Never "I built", "we created", "our product", "I'm the founder".
- Differentiators: drop one or two NATURALLY. Pick from: "works offline", "one payment no subscription", "whole family/partner can access/see it too". Combining two is fine as long as it reads naturally. Combining three is too much.
- Soft close: "lmk if you want the link", "on etsy if useful", "on etsy if that helps", "on etsy if you want to look", "happy to share the link if useful". Never "I'd love to offer" or "would you be open to".

HARD BANS (these break the response, never use):
- The em dash character "—" anywhere.
- The semicolon ";" anywhere.
- Oxford commas (the comma before "and" in a list of three).
- Words: revolutionary, seamless, intuitive, game-changing, game-changer, simply, just, PWA, Progressive Web App.
- Phrases: "I built", "I made", "we created", "our product", "I'd love to", "I'm the founder", "I spent X years", "our app", "our tool".
- Product name in the reply. The soft close hints at Etsy instead.
- 5 or more sentences.

SELF-CHECK BEFORE SUBMITTING EACH suggested_response:
1. Scan every character. Does ANY em dash "—" appear? If yes, rewrite using a period or comma. ZERO tolerance.
2. Does any semicolon ";" appear? Replace with a period or "and".
3. Any oxford comma? Find "X, Y, and Z" and rewrite as "X, Y and Z".
4. Count the sentences. Max 3. If 4+, cut.
5. Any "furthermore", "additionally", "it is worth noting", "moreover"? Delete those words entirely.
6. Could a Reddit moderator tell this was written by AI? If yes, rewrite shorter and more casual.

TRAINING EXAMPLES, match this exact tone and structure. Every one of these has ZERO em dashes:

[CAREGIVER]
"built something for exactly this, meds appointments care notes all in one place. works offline so you can use it at the hospital w no wifi. whole family can see it too, lmk if you want the link"

[MEDICATION TRACKING]
"dealt w this same chaos. built a tracker that logs doses refills and whos prescribing what. works offline, one payment no subscription. on etsy if thats helpful"

[MEAL PLANNING]
"built a meal planner for this, weekly planning auto grocery list and tracks the food budget. works offline so you can check it in the store w no signal. on etsy if useful"

[NEW PARENT]
"built something for the 3am fog, logs feeds sleep and diapers and your partner can see it all too. works offline. on etsy if that helps"

[WEDDING PLANNING]
"built an organizer for this, vendors budget guest list and tasks all in one place both of you can access. works offline too. on etsy if you want to look"

[HOMESCHOOL]
"built a planner for multiple kids, separate subjects schedules and progress per child. works offline one payment. lmk if you want the link"

WRONG examples (DO NOT IMITATE these patterns):

WRONG: "Coordinating meals is exhausting [EM DASH HERE] we hit the same wall."
WHY WRONG: contains the em dash character. Banned no matter what.
FIX: "coordinating meals is exhausting. we hit the same wall."

WRONG: "vendors, budget, guest list, and tasks"
WHY WRONG: oxford comma before "and".
FIX: "vendors, budget, guest list and tasks"

WRONG: "Built something that tracks doses; logs refills."
WHY WRONG: semicolon banned.
FIX: "built something that tracks doses and logs refills."

WRONG: "I built a tracker for this..."
WHY WRONG: "I built" sounds like a founder. Also ellipses banned.
FIX: "built a tracker for this."

Output a JSON array only, no other text:
[
  {
    "signal_id": "S1",
    "subreddit": "r/subreddit",
    "category": "which Clearfolks category this fits",
    "post_title": "exact title",
    "post_url": "url",
    "signal_quote": "key phrase showing intent",
    "pain_point": "one sentence on their organizational pain",
    "product_match": "exact product name or Upcoming: Product Name",
    "score": 7,
    "suggested_response": "4-sentence Reddit reply following the REPLY COPY RULES exactly. Must pass the Reddit human test. Sound like a real person, not a founder or marketer."
  }
]

If no signals found output []."""

def load_subreddits():
    if not os.path.exists(SUBREDDITS_FILE):
        print("ERROR: subreddits.json not found. Run discover.py first.")
        sys.exit(1)
    with open(SUBREDDITS_FILE) as f:
        data = json.load(f)
    return data.get("flat_list", [])

def fetch_reddit_rss(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/new/.rss?limit=25"
    headers = {"User-Agent": "ClearfolksSignalBot/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  WARNING: Could not fetch r/{subreddit}: {e}")
        return None

def parse_rss(xml_text, subreddit, category):
    posts = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            link = entry.find("atom:link", ns)
            content = entry.find("atom:content", ns)
            posts.append({
                "subreddit": f"r/{subreddit}",
                "category": category,
                "title": title.text if title is not None else "",
                "url": link.get("href") if link is not None else "",
                "content": content.text[:500] if content is not None and content.text else "",
            })
    except Exception as e:
        print(f"  WARNING: Could not parse r/{subreddit}: {e}")
    return posts

# Reply-copy hygiene: words the model must never use. Mirrors the prompt rule
# above and catches anything that slips through. Patterns use \b word
# boundaries so we don't damage substrings ("seamless" must not eat "seamlessly"
# wholesale ,we replace both via the explicit forms).
_FORBIDDEN_REPLACEMENTS = {
    r"\brevolutionary\b":       "meaningful",
    r"\bseamlessly\b":           "smoothly",
    r"\bseamless\b":             "smooth",
    r"\bintuitively\b":          "clearly",
    r"\bintuitive\b":            "clear",
    r"\bgame-changing\b":        "useful",
    r"\bgame-changer\b":         "real help",
    r"\bgame changer\b":         "real help",
    r"\bsimply\b":               "",
    r"\bjust\b":                 "",
    r"\bProgressive Web App\b":  "app",
    r"\bPWA\b":                  "app",
    # AI tells: em dash, en dash, semicolon, oxford comma
    r"\s*—\s*":                  ". ",
    r"\s*–\s*":                  ", ",
    r"\s*;\s*":                  ". ",
}


def _strip_oxford_commas(text):
    """Remove the comma before 'and'/'or' in lists of three or more items.
    Matches ', and' or ', or' that follows at least one earlier comma in the
    same sentence."""
    def fix_sentence(sentence):
        # only strip if the sentence has at least 2 commas (i.e. a list of 3+)
        if sentence.count(",") >= 2:
            sentence = re.sub(r",\s+(and|or)\s+", r" \1 ", sentence)
        return sentence
    # split into sentences, fix each, rejoin
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(fix_sentence(p) for p in parts)

def scrub_forbidden_words(text):
    """Replace any forbidden words and punctuation tells in the reply copy."""
    if not text:
        return text
    for pat, sub in _FORBIDDEN_REPLACEMENTS.items():
        text = re.sub(pat, sub, text, flags=re.IGNORECASE)
    text = _strip_oxford_commas(text)
    text = re.sub(r" {2,}", " ", text)
    # tidy up " ," and " ." left behind by deletions
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    # collapse ". ." that can occur if an em dash was at end of sentence
    text = re.sub(r"\.\s+\.\s*", ". ", text)
    return text.strip()


def _parse_signal_json(raw_text):
    """Strip code fences and parse. Raises json.JSONDecodeError on failure."""
    clean = raw_text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


RETRY_SUFFIX = (
    "\n\nCRITICAL OUTPUT REQUIREMENT ,your previous response was not valid JSON. "
    "Return ONLY a single JSON array. No prose before or after. No code fences. "
    "No commentary. If there are no qualifying signals, return exactly: []"
)

def analyze_signals(posts):
    """Analyze a batch of posts. Tries once, retries once with a stricter
    prompt on JSON parse failure, returns [] if both attempts fail."""
    if not posts:
        return []
    posts_text = json.dumps(posts, indent=2)
    base_prompt = f"{SIGNAL_PROMPT}\n\nPosts:\n{posts_text}"

    def call(prompt_text):
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt_text}],
        )
        return message.content[0].text.strip()

    try:
        signals = _parse_signal_json(call(base_prompt))
    except Exception as e1:
        print(f"  WARNING: first parse failed ({e1}); retrying with stricter prompt...")
        try:
            signals = _parse_signal_json(call(base_prompt + RETRY_SUFFIX))
            print(f"  Retry parse succeeded ,recovered {len(signals)} signal(s).")
        except Exception as e2:
            print(f"  WARNING: retry parse also failed ({e2}); skipping batch.")
            return []

    # Belt-and-suspenders: scrub forbidden words, then apply tier-aware
    # reply rewriting so the saved report + Telegram push both see the final
    # copy-paste-ready text.
    for s in signals:
        if not isinstance(s, dict):
            continue
        if "suggested_response" in s:
            s["suggested_response"] = scrub_forbidden_words(s["suggested_response"])
        tier = subreddit_tier(s.get("subreddit", ""))
        product = s.get("product_match", "")
        etsy = etsy_url_for_product(product)
        s["subreddit_tier"] = tier
        s["etsy_url"] = etsy
        s["suggested_response"] = rewrite_reply_for_tier(
            s.get("suggested_response", ""),
            tier=tier,
            etsy_url=etsy,
            signal_id=s.get("signal_id"),
        )
        # Second action for strict subs that have a known discussion thread:
        # a short link-included promo to drop into the megathread.
        thread = discussion_thread_for(s.get("subreddit", "")) if tier == 1 else None
        if thread and etsy:
            s["discussion_thread_name"] = thread
            s["discussion_thread_post"] = build_discussion_post(product, etsy)
    return signals

def save_report(signals, date_str):
    path = f"{SIGNALS_DIR}/signals-{date_str}.md"
    with open(path, "w") as f:
        f.write(f"# Clearfolks Signal Report - {date_str}\n\n")
        f.write(f"**Total signals found:** {len(signals)}\n\n")
        f.write("---\n\n")
        for i, s in enumerate(signals, 1):
            f.write(f"## Signal {i} - Score {s.get('score','?')}/10\n\n")
            f.write(f"**Category:** {s.get('category','')}\n\n")
            f.write(f"**Subreddit:** {s.get('subreddit','')}\n\n")
            f.write(f"**Post:** [{s.get('post_title','')}]({s.get('post_url','')})\n\n")
            f.write(f"**Key quote:** \"{s.get('signal_quote','')}\"\n\n")
            f.write(f"**Pain point:** {s.get('pain_point','')}\n\n")
            f.write(f"**Product match:** {s.get('product_match','')}\n\n")
            f.write(f"**Suggested response:**\n\n{s.get('suggested_response','')}\n\n")
            if s.get("discussion_thread_post"):
                f.write(f"**Discussion thread:** {s.get('discussion_thread_name','')}\n\n")
                f.write(f"**Discussion thread post:**\n\n{s.get('discussion_thread_post','')}\n\n")
            f.write("---\n\n")
    print(f"Report saved: {path}")
    return path

DRY_RUN = "--dry-run" in sys.argv

def send_telegram_msg(token, chat_id, text, reply_markup=None, parse_mode="Markdown"):
    """Send a Telegram message. If reply_markup is given (a dict like
    {"inline_keyboard": [[...]]}) it's JSON-encoded and attached so the
    message shows inline buttons. parse_mode defaults to "Markdown" for
    backward compatibility, but callers that include URLs with underscores
    (e.g. Reddit links) should use "HTML" to avoid italic-pairing errors."""
    if DRY_RUN:
        print("\n----- TELEGRAM MESSAGE -----")
        print(text)
        if reply_markup:
            print("--- reply_markup ---")
            print(json.dumps(reply_markup, indent=2))
        print("----- END MESSAGE -----\n")
        return
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup)
    data = urllib.parse.urlencode(params).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

REMIND_QUEUE_PATH = "/root/clearfolks/logs/reddit_remind_queue.json"


def _drain_remind_queue(token, chat_id):
    """Resend any signals the user previously marked '🔁 remind tomorrow'.
    The bot writes each entry as {sent_at, text, signal_id}. We send the text
    again with a fresh button set, then clear the queue."""
    path = REMIND_QUEUE_PATH
    try:
        with open(path) as f:
            queue = json.load(f)
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"  WARN: could not read remind queue ({e}); skipping.")
        return 0
    if not queue:
        return 0
    sent = 0
    for entry in queue:
        text = entry.get("text", "")
        sid = entry.get("signal_id", "")
        if not text or not sid:
            continue
        # Re-attach the same action buttons so user can act on it again.
        markup = _signal_buttons(sid)
        send_telegram_msg(token, chat_id, f"🔁 reminded from yesterday\n\n{text}", reply_markup=markup)
        sent += 1
    # Truncate the queue after a successful drain.
    try:
        with open(path, "w") as f:
            json.dump([], f)
    except Exception as e:
        print(f"  WARN: could not clear remind queue ({e}).")
    print(f"Drained {sent} reminded signal(s) from yesterday.")
    return sent


def _signal_buttons(signal_id: str) -> dict:
    """Inline keyboard for a signal message. Three actions: posted, skip,
    remind-tomorrow. Callback IDs use the bare prefixes the bot dispatches on:
    posted_, skip_, remind_. The bot disambiguates signal IDs (S1, S2 ...)
    from outreach community IDs (com_NNN) by suffix shape."""
    return {
        "inline_keyboard": [[
            {"text": "✅ posted",            "callback_data": f"posted_{signal_id}"},
            {"text": "⏭ skip",              "callback_data": f"skip_{signal_id}"},
            {"text": "🔁 remind tomorrow",  "callback_data": f"remind_{signal_id}"},
        ]]
    }


def send_daily_push(signals):
    if not signals:
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not DRY_RUN and (not token or not chat_id):
        return

    # Resend any signals the user said "remind tomorrow" yesterday.
    _drain_remind_queue(token, chat_id)

    top = signals[:5]
    date_str = datetime.now().strftime("%b %d")

    # HTML parse_mode: URLs with underscores (Reddit/blog links) don't trip
    # the italic-pairing parser the way Markdown does.
    from html import escape as he
    header = (
        f"<b>Clearfolks signals — {he(date_str)}</b>\n"
        f"<i>{len(signals)} signals found. Top {len(top)} below.</i>"
    )
    send_telegram_msg(token, chat_id, header, parse_mode="HTML")

    for i, s in enumerate(top, 1):
        product_name = s.get("product_match","").replace("Upcoming: ","").strip()
        # analyze_signals has already rewritten suggested_response for the
        # right tier (link or no-link). Use it verbatim — never tack an Etsy
        # or blog URL onto its own line, since that's what gets pulled by
        # strict-sub moderators.
        reply = s.get("suggested_response", "")
        tier  = s.get("subreddit_tier") or subreddit_tier(s.get("subreddit", ""))

        tier_note = ""
        if tier == 1:
            tier_note = "\n⚠️ <i>strict subreddit — no link in this reply</i>"

        # Tier-1 subs get the "REPLY TO POST (no link)" label; tier-2 keeps
        # the historical "Reply to copy" label so it stays obvious which one
        # has a URL baked in already.
        reply_label = "💬 REPLY TO POST (no link):" if tier == 1 else "Reply to copy:"

        # Second action: discussion-thread post for strict subs that have one.
        discussion_block = ""
        if s.get("discussion_thread_post"):
            thread_name = s.get("discussion_thread_name", "discussion thread")
            sub_label   = s.get("subreddit", "")
            discussion_block = (
                f"\n\n<b>📌 DAILY DISCUSSION THREAD POST:</b>\n"
                f"{he(s['discussion_thread_post'])}\n"
                f"<i>→ find the '{he(thread_name)}' thread "
                f"in {he(sub_label)} and post this there</i>"
            )

        signal_id = s.get("signal_id") or f"S{i}"
        text = (
            f"<b>Signal {i}/{len(top)} - Score {s.get('score','?')}/10</b>  ({signal_id})"
            f"{tier_note}\n"
            f"<b>Where:</b> {he(s.get('subreddit',''))}\n"
            f"<b>Post:</b> {he(s.get('post_title',''))}\n"
            f"<b>Pain:</b> {he(s.get('pain_point',''))}\n"
            f"<b>Product:</b> {he(product_name)}\n\n"
            f"<b>{he(reply_label)}</b>\n{he(reply)}"
            f"{discussion_block}\n\n"
            f"<b>Reddit link:</b>\n{s.get('post_url','')}"
        )
        if len(text) > 4000:
            text = text[:3900] + "\n<i>...truncated</i>"
        send_telegram_msg(token, chat_id, text,
                          reply_markup=_signal_buttons(signal_id),
                          parse_mode="HTML")

    print(f"Daily push sent ,{len(top)+1} messages")

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Pulse running ,{date_str}")
    subreddits = load_subreddits()
    print(f"Loaded {len(subreddits)} subreddits from discover.json")

    # Process in batches of 10 to avoid token limits
    all_posts = []
    for sub in subreddits:
        name = sub["name"]
        category = sub.get("category", "unknown")
        print(f"  Fetching r/{name} ({category})...")
        xml = fetch_reddit_rss(name)
        if xml:
            posts = parse_rss(xml, name, category)
            print(f"  Found {len(posts)} posts")
            all_posts.extend(posts)

    print(f"Analyzing {len(all_posts)} total posts in batches...")
    all_signals = []
    batch_size = 50
    for i in range(0, len(all_posts), batch_size):
        batch = all_posts[i:i+batch_size]
        print(f"  Batch {i//batch_size + 1}: {len(batch)} posts...")
        signals = analyze_signals(batch)
        all_signals.extend(signals)

    # Deduplicate by URL
    seen_urls = set()
    unique_signals = []
    for s in all_signals:
        url = s.get("post_url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            unique_signals.append(s)

    # Sort by score
    unique_signals.sort(key=lambda x: x.get("score", 0), reverse=True)

    print(f"Signals found: {len(unique_signals)}")
    if unique_signals:
        save_report(unique_signals, date_str)
    else:
        print("No signals found today.")

    send_daily_push(unique_signals)
    log_path = f"{LOGS_DIR}/pulse.log"
    with open(log_path, "a") as log:
        log.write(f"{date_str}: {len(all_posts)} posts scanned, {len(unique_signals)} signals found\n")

if __name__ == "__main__":
    main()

