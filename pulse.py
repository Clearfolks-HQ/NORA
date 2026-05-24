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
BLOG_BASE_URL = "https://blog.clearfolks.com"

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

    # Belt-and-suspenders: scrub forbidden words from every reply.
    for s in signals:
        if isinstance(s, dict) and "suggested_response" in s:
            s["suggested_response"] = scrub_forbidden_words(s["suggested_response"])
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

def build_reply_with_blog(suggested_response, cluster):
    """Append a natural blog-post mention to the Reddit reply copy.
    No-op if cluster is unknown or the link is already present."""
    reply = (suggested_response or "").rstrip()
    if not cluster:
        return reply
    blog_path = f"blog.clearfolks.com/{cluster}/"
    if blog_path in reply:
        return reply
    return f"{reply}\n\nI wrote a full guide on this: {blog_path}"

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
        cluster = product_to_cluster(product_name)
        blog_url = f"{BLOG_BASE_URL}/{cluster}/" if cluster else ""
        reply = build_reply_with_blog(s.get("suggested_response",""), cluster)
        blog_line = f"\n\n<b>Blog post:</b>\n{blog_url}" if blog_url else ""

        signal_id = s.get("signal_id") or f"S{i}"
        text = (
            f"<b>Signal {i}/{len(top)} - Score {s.get('score','?')}/10</b>  ({signal_id})\n"
            f"<b>Where:</b> {he(s.get('subreddit',''))}\n"
            f"<b>Post:</b> {he(s.get('post_title',''))}\n"
            f"<b>Pain:</b> {he(s.get('pain_point',''))}\n"
            f"<b>Product:</b> {he(product_name)}\n\n"
            f"<b>Reply to copy:</b>\n{he(reply)}\n\n"
            f"<b>Reddit link:</b>\n{s.get('post_url','')}"
            f"{blog_line}"
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

