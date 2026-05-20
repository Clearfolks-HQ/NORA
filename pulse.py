#!/usr/bin/env python3
"""
Pulse — Signal Analyst Agent (Layer 3)
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

SIGNAL_PROMPT = """You are Pulse, a buying signal analyst for Clearfolks Templates — an Etsy store selling lightweight digital organizer apps.

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

HIGH INTENT signals — people who:
- Are overwhelmed and actively seeking a system or tool
- Express frustration with disorganization, things falling through cracks
- Ask for app, tracker, planner, or organizer recommendations
- Mention coordinating with multiple family members

Score 1-10. Only include posts scoring 6 or above.

REPLY COPY RULES (apply to "suggested_response" — non-negotiable):
- Warm, practical, no hype. Sound like a real person who has been through this, not a marketer.
- NEVER use any of these words: revolutionary, seamless, intuitive, game-changing, game-changer, simply, just, PWA, Progressive Web App.
- No exclamation marks.

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
    "suggested_response": "helpful empathetic reply that: (1) acknowledges pain, (2) gives one practical tip, (3) mentions the product by exact name with ONE differentiator: lifetime access OR works offline OR shareable across household. Obeys the REPLY COPY RULES above."
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
# wholesale — we replace both via the explicit forms).
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
}

def scrub_forbidden_words(text):
    """Replace any forbidden words in the reply copy. Returns the cleaned
    string with double-spaces collapsed."""
    if not text:
        return text
    for pat, sub in _FORBIDDEN_REPLACEMENTS.items():
        text = re.sub(pat, sub, text, flags=re.IGNORECASE)
    text = re.sub(r" {2,}", " ", text)
    # also tidy up " ," and " ." left behind by deletions
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


def _parse_signal_json(raw_text):
    """Strip code fences and parse. Raises json.JSONDecodeError on failure."""
    clean = raw_text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


RETRY_SUFFIX = (
    "\n\nCRITICAL OUTPUT REQUIREMENT — your previous response was not valid JSON. "
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
            print(f"  Retry parse succeeded — recovered {len(signals)} signal(s).")
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
        f.write(f"# Clearfolks Signal Report — {date_str}\n\n")
        f.write(f"**Total signals found:** {len(signals)}\n\n")
        f.write("---\n\n")
        for i, s in enumerate(signals, 1):
            f.write(f"## Signal {i} — Score {s.get('score','?')}/10\n\n")
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

def send_telegram_msg(token, chat_id, text):
    if DRY_RUN:
        print("\n----- TELEGRAM MESSAGE -----")
        print(text)
        print("----- END MESSAGE -----\n")
        return
    import urllib.request, urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true"
    }).encode()
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

def send_daily_push(signals):
    if not signals:
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not DRY_RUN and (not token or not chat_id):
        return

    top = signals[:3]
    date_str = datetime.now().strftime("%b %d")

    header = (
        f"*Clearfolks signals — {date_str}*\n"
        f"_{len(signals)} signals found. Top {len(top)} below._"
    )
    send_telegram_msg(token, chat_id, header)

    for i, s in enumerate(top, 1):
        product_name = s.get("product_match","").replace("Upcoming: ","").strip()
        cluster = product_to_cluster(product_name)
        blog_url = f"{BLOG_BASE_URL}/{cluster}/" if cluster else ""
        reply = build_reply_with_blog(s.get("suggested_response",""), cluster)
        blog_line = f"\n\n*Blog post:*\n{blog_url}" if blog_url else ""

        text = (
            f"*Signal {i}/{len(top)} — Score {s.get('score','?')}/10*\n"
            f"*Where:* {s.get('subreddit','')}\n"
            f"*Post:* {s.get('post_title','')}\n"
            f"*Pain:* {s.get('pain_point','')}\n"
            f"*Product:* {product_name}\n\n"
            f"*Reply to copy:*\n{reply}\n\n"
            f"*Reddit link:*\n{s.get('post_url','')}"
            f"{blog_line}"
        )
        if len(text) > 4000:
            text = text[:3900] + "\n_...truncated_"
        send_telegram_msg(token, chat_id, text)

    print(f"Daily push sent — {len(top)+1} messages")

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Pulse running — {date_str}")
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

