#!/usr/bin/env python3
"""
Outreach — Community Outreach Agent (high-velocity pipeline)

Modes (mutually exclusive — pick one per invocation):
  --find     Discover 20-30 candidate communities, score, save to master DB.
  --track    Follow-up reminders, review-request timing alerts.
  --deliver  Send today's queue (10 messages, each with inline buttons).
  --seed     One-shot: pre-populate communities.json with 14 starter communities.
  --dry-run  Print Telegram payloads instead of sending. Stacks with the above.

Persistence (under /root/clearfolks/outreach/):
  communities.json — master DB of every known community + draft + state
  queue.json       — today's action queue (pending/sent/skipped) + carryover

State machine per-community.status:
  pending → sent | skipped | edit
  sent    → converted | rejected | no_response
  converted → review_requested (after 14d)

Telegram messages carry inline buttons; callback handling lives in telegram_bot.py.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, date

import anthropic

OUTREACH_DIR = Path("/root/clearfolks/outreach")
COMMUNITIES_FILE = OUTREACH_DIR / "communities.json"
QUEUE_FILE = OUTREACH_DIR / "queue.json"
PRODUCTS_FILE = Path("/root/clearfolks/products.json")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BASE = f"https://api.telegram.org/bot{TOKEN}"

DAILY_DELIVER = 10
DAILY_FIND_TARGET = 25
SEP = "━" * 26

DRY_RUN = "--dry-run" in sys.argv

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------- product helpers ---------------------------------------------------

PRODUCT_ONE_LINER = {
    "Caregiver Command Center":      "it tracks medications, appointments, and contacts for the person you're caring for",
    "Medication Tracker":            "it tracks doses, refills, and symptoms so nothing slips through",
    "IEP Parent Binder":             "it tracks goals, meetings, services, and contacts for your child's IEP",
    "IEP Meeting Prep Kit":          "it walks you through 28 questions, your parental rights, and meeting notes",
    "Etsy Seller Business System":   "it tracks sales, fees, expenses, and listings for your shop",
    "Wedding Planning App":          "it tracks budget, vendors, guest lists, and the wedding timeline",
    "Baby Tracker & Postpartum App": "it tracks feeds, sleep, diapers, and milestones in one place",
    "Homeschool Planner App":        "it tracks lessons, curriculum, and progress for multiple kids in one place",
    "Pet Care Organizer App":        "it tracks vet visits, medications, grooming, and feeding for every pet",
    "Meal Planner & Grocery App":    "it tracks meals, recipes, groceries, and the household food budget",
    "Moving Day Organizer App":      "it tracks packing, utilities, change-of-address, and the moving timeline",
    "Travel Planner App":            "it tracks itinerary, packing, budget, and activities for your trip",
}

AUDIENCE_DESCRIPTOR = {
    "Caregiver Command Center":      "families looking after aging parents or a sick loved one",
    "Medication Tracker":            "people managing complex medication routines",
    "IEP Parent Binder":             "parents navigating the IEP process",
    "IEP Meeting Prep Kit":          "parents preparing for an IEP meeting",
    "Etsy Seller Business System":   "indie makers running their own Etsy shops",
    "Wedding Planning App":          "couples planning their wedding",
    "Baby Tracker & Postpartum App": "new parents in the postpartum window",
    "Homeschool Planner App":        "families already doing the hard work of homeschooling",
    "Pet Care Organizer App":        "people who care for their pets like family",
    "Meal Planner & Grocery App":    "families trying to eat well on a budget",
    "Moving Day Organizer App":      "families in the middle of a move",
    "Travel Planner App":            "people planning a trip",
}


def load_products():
    with open(PRODUCTS_FILE) as f:
        return json.load(f)["products"]


def product_by_name(name):
    for p in load_products():
        if p["name"] == name:
            return p
    return None


# ---------- persistence -------------------------------------------------------

def load_communities():
    OUTREACH_DIR.mkdir(parents=True, exist_ok=True)
    if not COMMUNITIES_FILE.exists():
        return {"updated": None, "communities": []}
    with open(COMMUNITIES_FILE) as f:
        return json.load(f)


def save_communities(data):
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(COMMUNITIES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_queue():
    if not QUEUE_FILE.exists():
        return None
    with open(QUEUE_FILE) as f:
        return json.load(f)


def save_queue(q):
    with open(QUEUE_FILE, "w") as f:
        json.dump(q, f, indent=2)


def next_id(data):
    nums = [int(c["id"].split("_")[1]) for c in data["communities"] if c["id"].startswith("com_")]
    n = (max(nums) + 1) if nums else 1
    return f"com_{n:03d}"


# ---------- Telegram ----------------------------------------------------------

def api(method, params, retries=2):
    if DRY_RUN:
        preview = {k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v) for k, v in params.items()}
        print(f"[DRY_RUN] {method}: {json.dumps(preview)[:300]}")
        return {"ok": True, "result": {"message_id": 0}}
    url = f"{BASE}/{method}"
    data = urllib.parse.urlencode(params).encode()
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries:
                print(f"Telegram API error ({method}): {e}")
                return {}
            time.sleep(1 + attempt)
    return {}


def send_message(text, buttons=None):
    params = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}
    if buttons is not None:
        params["reply_markup"] = json.dumps(buttons)
    return api("sendMessage", params)


def buttons_outreach(community_id):
    return {
        "inline_keyboard": [[
            {"text": "✅ Sent", "callback_data": f"sent_{community_id}"},
            {"text": "⏭ Skip", "callback_data": f"skip_{community_id}"},
            {"text": "🔄 Edit", "callback_data": f"edit_{community_id}"},
        ]]
    }


# ---------- copy rendering ----------------------------------------------------

def render_draft_message(community):
    """The DM-the-admin draft. Plain text — no markdown."""
    name = community["name"]
    product = community["product_match"]
    etsy_url = community["etsy_url"]
    one_liner = PRODUCT_ONE_LINER.get(product, "it organizes everything in one place")
    audience = AUDIENCE_DESCRIPTOR.get(product, "people doing the hard work of caring for their families")
    return (
        f"Hi there,\n\n"
        f"I came across {name} and wanted to reach out directly.\n\n"
        f"I'm Debajit, founder of Clearfolks. I spent two years building practical "
        f"organizer apps for families — not because it seemed like a good business "
        f"idea, but because I watched people I love struggle with this and couldn't "
        f"find anything that actually worked.\n\n"
        f"The result is the {product} — {one_liner}. One payment, lifetime access, "
        f"works offline, household sharing included. No subscriptions.\n\n"
        f"It's on Etsy here:\n{etsy_url}\n\n"
        f"No affiliate arrangement. No ask for promotion. Just a genuine offer for "
        f"{audience}. If even a handful leave an honest review, that means "
        f"everything to a small indie maker.\n\n"
        f"Would you be open to sharing it with your group?\n\n"
        f"— Debajit Lahiri\nFounder, Clearfolks\nclearfolks.com"
    )


def render_group_post(community):
    """The ready-to-paste group post for after an admin says yes."""
    product = community["product_match"]
    one_liner = PRODUCT_ONE_LINER.get(product, "it organizes everything in one place")
    etsy_url = community["etsy_url"]
    return (
        f"Hey everyone! We're excited to share something from Debajit at Clearfolks "
        f"— a practical {product} that helps you stay organized: {one_liner}.\n\n"
        f"It's on their Etsy shop here:\n{etsy_url}\n\n"
        f"If you try it, please leave an honest review on Etsy — it helps a small "
        f"indie maker enormously."
    )


def render_outreach_card(community, position, total):
    return "\n".join([
        SEP,
        f"📨 OUTREACH [{position} of {total}] — today's queue",
        SEP,
        f"🏘 {community['name']}",
        f"📱 {community['platform']}",
        f"👥 {community['size']}",
        f"🎯 {community['product_match']}",
        SEP,
        "WHERE TO FIND ADMIN:",
        community["admin_hint"],
        SEP,
        "MESSAGE TO COPY & PASTE:",
        SEP,
        community["draft_message"],
        SEP,
    ])


def render_summary(queue, communities):
    week_start = (date.today() - timedelta(days=7)).isoformat()
    sent_this_week = sum(
        1 for c in communities["communities"]
        if c.get("sent_at") and c["sent_at"] >= week_start
    )
    converted = sum(1 for c in communities["communities"] if c.get("status") == "converted")
    return "\n".join([
        SEP,
        "📋 TODAY'S OUTREACH QUEUE",
        SEP,
        f"{len(queue['pending'])} ready to action",
        f"📦 Backlog: {queue['total_backlog']} pending",
        f"✅ Sent this week: {sent_this_week}",
        f"🎉 Converted: {converted} communities",
        SEP,
        "Messages incoming ↓",
    ])


# ---------- find --------------------------------------------------------------

FIND_PROMPT = """You are a community-research assistant for Clearfolks, an indie maker of practical organizer apps.

Surface REAL, well-known online communities (Facebook groups, subreddits, Substack newsletters, niche blogs) where Clearfolks customers might already be hanging out.

Return EXACTLY {target} candidates as a single JSON array. Each candidate must be a real community you have knowledge of — names that someone could find by searching today, not invented.

For each candidate include:
  name           — community name (real)
  platform       — one of: "Facebook Group", "Subreddit", "Substack", "Blog"
  size           — rough size, e.g. "~50,000 members" or "~10K subscribers"
  admin_hint     — one-line instruction for finding the admin/moderator
                   (e.g. "Search '<name>' on Facebook → click 'About' → moderator list")
  product_match  — EXACTLY one of:
                   "Caregiver Command Center", "Medication Tracker",
                   "IEP Parent Binder", "IEP Meeting Prep Kit",
                   "Etsy Seller Business System", "Wedding Planning App",
                   "Baby Tracker & Postpartum App", "Homeschool Planner App",
                   "Pet Care Organizer App", "Meal Planner & Grocery App",
                   "Moving Day Organizer App", "Travel Planner App"
  score          — integer 1-10 (10 = highest signal/size alignment for the product)

Search angles to cover (sample broadly):
- caregiver support, dementia, sandwich generation, family caregiver
- IEP advocacy, special needs parents, ADHD parenting
- homeschool moms, secular homeschool, homeschool planning
- new moms support, postpartum support, baby sleep
- meal prep, budget meal planning
- pet care, pet parenting
- moving tips, relocation
- travel planning
- etsy sellers, indie maker community
- wedding planning, bride communities

Spread candidates across at least 8 different product matches.
AVOID these already-known names (exact-match exclusion):
{exclude_names}

Output ONLY the JSON array. No prose, no code fences, no commentary.
"""


def find_communities():
    data = load_communities()
    known = {c["name"].lower() for c in data["communities"]}
    prompt = FIND_PROMPT.format(
        target=DAILY_FIND_TARGET,
        exclude_names=json.dumps(sorted(list(known))[:200])
    )
    print(f"[find] asking claude for {DAILY_FIND_TARGET} candidates ...")
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        print(f"[find] claude API error: {e}")
        return 0
    raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    try:
        candidates = json.loads(raw)
    except Exception as e:
        print(f"[find] parse error: {e}\n  raw[:200]={raw[:200]!r}")
        return 0
    added = 0
    for c in candidates:
        name = (c.get("name") or "").strip()
        if not name or name.lower() in known:
            continue
        prod = product_by_name(c.get("product_match", ""))
        if not prod:
            continue
        community = {
            "id": next_id(data),
            "name": name,
            "platform": c.get("platform", "Unknown"),
            "size": c.get("size", "unknown"),
            "admin_hint": c.get("admin_hint", f"Search '{name}' online"),
            "product_match": prod["name"],
            "product_slug": prod["slug"],
            "etsy_url": prod["etsy_url"],
            "score": int(c.get("score", 5)),
            "status": "pending",
            "discovered": date.today().isoformat(),
            "sent_at": None,
            "responded": None,
            "converted_at": None,
            "review_request_due": None,
        }
        community["draft_message"] = render_draft_message(community)
        community["group_post"] = render_group_post(community)
        data["communities"].append(community)
        known.add(name.lower())
        added += 1
    save_communities(data)
    print(f"[find] added {added} new communities ({len(data['communities'])} total)")
    return added


# ---------- queue management --------------------------------------------------

def build_today_queue():
    """Build today's queue: yesterday's unactioned + new pending, top {DAILY_DELIVER} by score."""
    data = load_communities()
    today = date.today().isoformat()
    yesterday_q = load_queue()
    carried = list(yesterday_q["pending"]) if yesterday_q else []

    pending_ids = {c["id"] for c in data["communities"] if c["status"] == "pending"}
    by_id = {c["id"]: c for c in data["communities"]}

    backlog = [cid for cid in carried if cid in pending_ids]
    new_ids = [cid for cid in pending_ids if cid not in set(backlog)]

    backlog_sorted = sorted(backlog, key=lambda x: -by_id[x]["score"])
    new_sorted = sorted(new_ids, key=lambda x: -by_id[x]["score"])

    candidate_order = backlog_sorted + new_sorted
    if len(candidate_order) > 50:
        # backlog over 50: switch to pure highest-score ordering
        candidate_order = sorted(candidate_order, key=lambda x: -by_id[x]["score"])

    today_pending = candidate_order[:DAILY_DELIVER]
    remaining = candidate_order[DAILY_DELIVER:]

    return {
        "date": today,
        "pending": today_pending,
        "sent_today": [],
        "skipped_today": [],
        "total_backlog": len(remaining),
        "carryover": remaining,
        "message_ids": {},
    }


# ---------- deliver -----------------------------------------------------------

def deliver_queue():
    data = load_communities()
    q = load_queue()
    today = date.today().isoformat()

    if not q or q["date"] != today:
        q = build_today_queue()
        save_queue(q)
    elif q["pending"] and all(cid in q.get("message_ids", {}) for cid in q["pending"]):
        print("[deliver] today's queue already delivered — skipping")
        return

    if not q["pending"]:
        send_message("📋 Today's outreach queue is empty. New communities will be discovered overnight.")
        return

    print(f"[deliver] sending {len(q['pending'])} outreach cards to Telegram")
    send_message(render_summary(q, data))
    time.sleep(0.4)

    by_id = {c["id"]: c for c in data["communities"]}
    total = len(q["pending"])
    for idx, cid in enumerate(q["pending"], 1):
        c = by_id.get(cid)
        if not c:
            continue
        # Refresh copy in case product details changed
        c["draft_message"] = render_draft_message(c)
        c["group_post"] = render_group_post(c)
        card = render_outreach_card(c, idx, total)
        result = send_message(card, buttons=buttons_outreach(cid))
        mid = result.get("result", {}).get("message_id")
        if mid:
            q["message_ids"][cid] = mid
        time.sleep(0.4)

    save_communities(data)
    save_queue(q)
    print("[deliver] done")


# ---------- track -------------------------------------------------------------

def track_pipeline():
    """Send time-based reminders: follow-ups + review requests."""
    data = load_communities()
    today = date.today()
    alerts = []
    for c in data["communities"]:
        if c.get("status") == "sent" and c.get("sent_at"):
            sent_d = date.fromisoformat(c["sent_at"])
            age = (today - sent_d).days
            if age == 4 and not c.get("followup_sent"):
                alerts.append(("followup", c, age))
            if age == 10 and not c.get("nudge_sent"):
                alerts.append(("nudge", c, age))
        if c.get("status") == "converted" and c.get("converted_at"):
            conv_d = date.fromisoformat(c["converted_at"])
            age = (today - conv_d).days
            if age >= 14 and not c.get("review_requested"):
                alerts.append(("review", c, age))

    if not alerts:
        print("[track] no alerts today")
        return

    for kind, c, age in alerts:
        if kind == "followup":
            send_message(
                f"⏰ FOLLOW-UP — {c['name']}\n\n"
                f"Sent {age}d ago, no response yet.\n"
                f"Consider a short check-in DM to the admin."
            )
            c["followup_sent"] = today.isoformat()
        elif kind == "nudge":
            send_message(
                f"📭 NUDGE — {c['name']}\n\n"
                f"Sent {age}d ago. Mark as no-response or send one final nudge."
            )
            c["nudge_sent"] = today.isoformat()
        elif kind == "review":
            send_message(
                f"⭐ REVIEW REQUEST DUE — {c['name']}\n\n"
                f"Converted {age}d ago. Time to circle back to the admin and ask "
                f"for an Etsy review checkpoint.\n\n"
                f"Suggested DM:\n"
                f"\"Hi! It's been a couple weeks since you shared {c['product_match']} "
                f"with your group. If anyone gave it a try, an honest Etsy review "
                f"would mean the world to a small indie maker.\""
            )
            c["review_requested"] = today.isoformat()

    save_communities(data)
    print(f"[track] sent {len(alerts)} alert(s)")


# ---------- seed --------------------------------------------------------------

SEED_COMMUNITIES = [
    {"name": "Secular, Eclectic, Academic! Homeschoolers", "platform": "Facebook Group", "size": "~120,000 members", "admin_hint": "Search the group name on Facebook → 'About' tab → scroll to admins/moderators", "product_match": "Homeschool Planner App", "score": 9},
    {"name": "r/homeschool", "platform": "Subreddit", "size": "~180,000 members", "admin_hint": "Open r/homeschool → click 'See more' under moderators → DM the top mod", "product_match": "Homeschool Planner App", "score": 8},
    {"name": "Caregivers Connect", "platform": "Facebook Group", "size": "~45,000 members", "admin_hint": "Search 'Caregivers Connect' on Facebook → 'About' tab → admin list", "product_match": "Caregiver Command Center", "score": 9},
    {"name": "r/AgingParents", "platform": "Subreddit", "size": "~70,000 members", "admin_hint": "Open r/AgingParents → 'See more' under moderators → DM top mod", "product_match": "Caregiver Command Center", "score": 8},
    {"name": "IEP Support Group for Parents", "platform": "Facebook Group", "size": "~60,000 members", "admin_hint": "Search the group on Facebook → 'About' → admin/moderator names", "product_match": "IEP Parent Binder", "score": 9},
    {"name": "r/specialed", "platform": "Subreddit", "size": "~50,000 members", "admin_hint": "Open r/specialed → moderators list → DM top mod", "product_match": "IEP Meeting Prep Kit", "score": 7},
    {"name": "Etsy Sellers — Shop Talk", "platform": "Facebook Group", "size": "~80,000 members", "admin_hint": "Search 'Etsy Sellers Shop Talk' on Facebook → 'About' → admins", "product_match": "Etsy Seller Business System", "score": 9},
    {"name": "r/EtsySellers", "platform": "Subreddit", "size": "~95,000 members", "admin_hint": "Open r/EtsySellers → moderators → DM top mod", "product_match": "Etsy Seller Business System", "score": 8},
    {"name": "Wedding Planning Community", "platform": "Facebook Group", "size": "~200,000 members", "admin_hint": "Search the group on Facebook → 'About' tab → admins", "product_match": "Wedding Planning App", "score": 8},
    {"name": "New Moms Support Group", "platform": "Facebook Group", "size": "~150,000 members", "admin_hint": "Search 'New Moms Support Group' on Facebook → 'About' → moderators", "product_match": "Baby Tracker & Postpartum App", "score": 9},
    {"name": "Pet Parents Community", "platform": "Facebook Group", "size": "~110,000 members", "admin_hint": "Search the group on Facebook → 'About' → admin list", "product_match": "Pet Care Organizer App", "score": 8},
    {"name": "Budget Meal Planning for Families", "platform": "Facebook Group", "size": "~250,000 members", "admin_hint": "Search the group on Facebook → 'About' → moderators", "product_match": "Meal Planner & Grocery App", "score": 9},
    {"name": "Moving Tips & Tricks", "platform": "Facebook Group", "size": "~40,000 members", "admin_hint": "Search 'Moving Tips & Tricks' on Facebook → 'About' → admin", "product_match": "Moving Day Organizer App", "score": 7},
    {"name": "r/travel", "platform": "Subreddit", "size": "~10M members", "admin_hint": "Open r/travel → moderators → DM top mod (note: huge sub, expect slow response)", "product_match": "Travel Planner App", "score": 7},
]


def seed_communities():
    data = load_communities()
    if data["communities"]:
        print(f"[seed] communities.json already has {len(data['communities'])} entries — skipping seed")
        return
    today = date.today().isoformat()
    for entry in SEED_COMMUNITIES:
        prod = product_by_name(entry["product_match"])
        if not prod:
            print(f"[seed] WARNING: no product for {entry['product_match']}")
            continue
        c = {
            "id": next_id(data),
            "name": entry["name"],
            "platform": entry["platform"],
            "size": entry["size"],
            "admin_hint": entry["admin_hint"],
            "product_match": prod["name"],
            "product_slug": prod["slug"],
            "etsy_url": prod["etsy_url"],
            "score": entry["score"],
            "status": "pending",
            "discovered": today,
            "sent_at": None,
            "responded": None,
            "converted_at": None,
            "review_request_due": None,
        }
        c["draft_message"] = render_draft_message(c)
        c["group_post"] = render_group_post(c)
        data["communities"].append(c)
    save_communities(data)
    print(f"[seed] seeded {len(data['communities'])} communities")


# ---------- CLI ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--find", action="store_true", help="Discover new communities")
    parser.add_argument("--track", action="store_true", help="Send tracking/follow-up alerts")
    parser.add_argument("--deliver", action="store_true", help="Send today's queue to Telegram")
    parser.add_argument("--seed", action="store_true", help="One-shot: pre-populate starter communities")
    parser.add_argument("--dry-run", action="store_true", help="Print Telegram payloads, do not send")
    args = parser.parse_args()

    if args.seed:
        seed_communities()
    if args.find:
        find_communities()
    if args.track:
        track_pipeline()
    if args.deliver:
        deliver_queue()
    if not (args.seed or args.find or args.track or args.deliver):
        parser.print_help()


if __name__ == "__main__":
    main()
