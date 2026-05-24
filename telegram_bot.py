#!/usr/bin/env python3
"""
Clearfolks HQ Telegram Bot
Commands: /categories /add /remove /status /signals /products /outreach
Also handles inline-button callback_queries from the outreach agent.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, "/root/clearfolks")
from outreach import (
    load_communities, save_communities,
    load_queue, save_queue,
    render_group_post, render_outreach_card,
    buttons_outreach,
    SEP,
)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
BASE = f"https://api.telegram.org/bot{TOKEN}"
CATEGORIES_FILE = "/root/clearfolks/categories.json"
PRODUCTS_FILE = "/root/clearfolks/products.json"
SIGNALS_DIR = "/root/clearfolks/signals"
LOGS_DIR = "/root/clearfolks/logs"

def api(method, params={}):
    url = f"{BASE}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"API error: {e}")
        return {}

def send(text, parse_mode="Markdown"):
    api("sendMessage", {"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode})

def send_plain(text, buttons=None):
    """Plain-text send (no markdown). Used for outreach which embeds raw chars."""
    params = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}
    if buttons is not None:
        params["reply_markup"] = json.dumps(buttons)
    return api("sendMessage", params)

def edit_text(message_id, text, buttons=None):
    """Edit an existing message in-place. Removes buttons unless `buttons` given."""
    params = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    params["reply_markup"] = json.dumps(buttons if buttons is not None else {"inline_keyboard": []})
    return api("editMessageText", params)

def answer_cb(cb_id, text=""):
    return api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

def _find_community(db, cid):
    for c in db["communities"]:
        if c["id"] == cid:
            return c
    return None

def load_categories():
    if not Path(CATEGORIES_FILE).exists():
        return {"updated": "never", "categories": []}
    with open(CATEGORIES_FILE) as f:
        return json.load(f)

def save_categories(data):
    with open(CATEGORIES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def cmd_categories():
    data = load_categories()
    cats = data.get("categories", [])
    if not cats:
        send("No categories tracked yet. Run Layer 1 research first.")
        return
    lines = [f"*Clearfolks tracked categories* (updated {data.get('updated','?')})\n"]
    for c in cats:
        verdict = c.get("verdict", "?").upper()
        name = c.get("category", "?")
        ptype = c.get("type", "?")
        fit = c.get("pwa_fit", "?")
        product = c.get("suggested_product_name") or c.get("existing_product_match") or "TBD"
        lines.append(f"[{verdict}] *{name}*\n  Type: {ptype} | PWA fit: {fit}\n  Product: {product}")
    send("\n\n".join(lines))

def cmd_add(category_name):
    if not category_name:
        send("Usage: /add Category Name")
        return
    data = load_categories()
    existing = [c["category"].lower() for c in data["categories"]]
    if category_name.lower() in existing:
        send(f"*{category_name}* is already in the list.")
        return
    new_cat = {
        "category": category_name,
        "type": "evergreen",
        "seasonal_window": None,
        "pain_summary": "Manually added — run research to populate details",
        "pwa_fit": "unknown",
        "pwa_fit_reason": "Pending research",
        "etsy_demand": "unknown",
        "etsy_demand_reason": "Pending research",
        "existing_product_match": "none",
        "verdict": "validate",
        "verdict_reason": "Manually added for investigation",
        "suggested_product_name": f"{category_name} Organizer App"
    }
    data["categories"].append(new_cat)
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    save_categories(data)
    send(f"Added *{category_name}* to tracked categories.\nVerdict: VALIDATE\nRun monthly research to get full analysis.")

def cmd_remove(category_name):
    if not category_name:
        send("Usage: /remove Category Name")
        return
    data = load_categories()
    before = len(data["categories"])
    data["categories"] = [c for c in data["categories"] if c["category"].lower() != category_name.lower()]
    after = len(data["categories"])
    if before == after:
        send(f"*{category_name}* not found. Use /categories to see current list.")
        return
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    save_categories(data)
    send(f"Removed *{category_name}* from tracked categories.")

def cmd_status():
    lines = ["*Clearfolks pipeline status*\n"]
    pulse_log = Path(LOGS_DIR) / "pulse.log"
    if pulse_log.exists():
        with open(pulse_log) as f:
            lines_list = f.readlines()
        last = lines_list[-1].strip() if lines_list else "No runs yet"
        lines.append(f"Pulse (daily): {last}")
    else:
        lines.append("Pulse: never run")
    cats = load_categories()
    lines.append(f"Categories: {len(cats.get('categories', []))} tracked (updated {cats.get('updated','never')})")
    sig_files = list(Path(SIGNALS_DIR).glob("signals-*.md")) if Path(SIGNALS_DIR).exists() else []
    lines.append(f"Signal reports: {len(sig_files)} total")
    if sig_files:
        latest = sorted(sig_files)[-1].name
        lines.append(f"Latest: {latest}")
    send("\n".join(lines))

def cmd_signals():
    sig_files = sorted(Path(SIGNALS_DIR).glob("signals-*.md")) if Path(SIGNALS_DIR).exists() else []
    if not sig_files:
        send("No signal reports yet.")
        return
    latest = sig_files[-1]
    with open(latest) as f:
        content = f.read()
    lines = content.split("\n")
    total_line = next((l for l in lines if "Total signals" in l), "")
    signals = []
    current = {}
    for line in lines:
        if line.startswith("## Signal"):
            if current:
                signals.append(current)
            current = {"header": line}
        elif line.startswith("**Subreddit:**"):
            current["subreddit"] = line.replace("**Subreddit:**", "").strip()
        elif line.startswith("**Pain point:**"):
            current["pain"] = line.replace("**Pain point:**", "").strip()
    if current:
        signals.append(current)
    out = [f"*Latest signals — {latest.stem}*", total_line, ""]
    for s in signals[:5]:
        out.append(f"{s.get('header','')}")
        out.append(f"  {s.get('subreddit','')}")
        out.append(f"  {s.get('pain','')}\n")
    send("\n".join(out))

def cmd_products():
    if not Path(PRODUCTS_FILE).exists():
        send("No products registry found.")
        return
    with open(PRODUCTS_FILE) as f:
        data = json.load(f)
    products = data.get("products", [])
    lines = [f"*Clearfolks products* ({len(products)} total)\n"]
    for p in products:
        status = p.get("status", "?").upper()
        etsy = p.get("etsy_listing", "?")
        lines.append(
            f"{p['id']} *{p['name']}*\n"
            f"  Status: {status} | Etsy: {etsy}\n"
            f"  {p['url']}"
        )
    send("\n\n".join(lines))

def cmd_outreach():
    db = load_communities()
    q = load_queue()
    today = date.today().isoformat()
    by_status = {}
    for c in db["communities"]:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    pending = by_status.get("pending", 0)
    sent = by_status.get("sent", 0)
    converted = by_status.get("converted", 0)
    rejected = by_status.get("rejected", 0)
    skipped = by_status.get("skipped", 0)
    no_response = by_status.get("no_response", 0)
    post_shared = by_status.get("post_shared", 0)

    week_start = (date.today() - timedelta(days=7)).isoformat()
    sent_this_week = sum(
        1 for c in db["communities"]
        if c.get("sent_at") and c["sent_at"] >= week_start
    )

    lines = [
        "*Clearfolks outreach pipeline*",
        f"Communities tracked: {len(db['communities'])}",
        "",
        f"Pending:        {pending}",
        f"Sent:           {sent}  (this week: {sent_this_week})",
        f"No response:    {no_response}",
        f"Converted:      {converted}",
        f"Post shared:    {post_shared}",
        f"Rejected:       {rejected}",
        f"Skipped:        {skipped}",
        "",
    ]
    if q:
        same_day = "today" if q.get("date") == today else f"queue date: {q.get('date')}"
        lines.append(f"Queue ({same_day}): {len(q.get('pending', []))} ready, "
                     f"{q.get('total_backlog', 0)} in backlog")
    else:
        lines.append("No queue file yet — outreach.py --deliver builds it.")
    send("\n".join(lines))


CALLBACK_PREFIXES = (
    "sent_", "skip_", "editundo_", "editconfirm_", "edit_",
    "yes_", "no_", "pending_", "post_shared_", "copy_",
    # Signal (pulse.py daily push) actions:
    "posted_", "remind_",
)


def _parse_callback(data_str):
    for prefix in CALLBACK_PREFIXES:
        if data_str.startswith(prefix):
            return prefix[:-1], data_str[len(prefix):]
    return None, None


REDDIT_ACTIONS_LOG  = Path(LOGS_DIR) / "reddit_actions.json"
REDDIT_REMIND_QUEUE = Path(LOGS_DIR) / "reddit_remind_queue.json"


def _is_signal_id(cid: str) -> bool:
    """Pulse signal IDs look like S1, S2, S17. Outreach community IDs look
    like com_001. This lets us share callback prefixes (notably skip_) across
    the two flows without collisions."""
    return bool(cid) and cid[0] in ("S", "s") and cid[1:].isdigit()


def _append_json_list(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    data.append(entry)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _handle_signal_callback(cb, action, sid):
    """Posted / skip / remind handler for pulse signal messages."""
    cb_id      = cb["id"]
    msg        = cb.get("message", {}) or {}
    message_id = msg.get("message_id")
    msg_text   = msg.get("text", "") or ""
    now_iso    = datetime.now().isoformat(timespec="seconds")

    if action == "posted":
        _append_json_list(REDDIT_ACTIONS_LOG,
                          {"signal_id": sid, "action": "posted", "ts": now_iso})
        edit_text(message_id, f"✅ POSTED — {sid}\n   logged at {now_iso}")
        answer_cb(cb_id, "got it, marked as posted")

    elif action == "skip":
        _append_json_list(REDDIT_ACTIONS_LOG,
                          {"signal_id": sid, "action": "skipped", "ts": now_iso})
        edit_text(message_id, f"⏭ SKIPPED — {sid}\n   logged at {now_iso}")
        answer_cb(cb_id, "skipped")

    elif action == "remind":
        _append_json_list(REDDIT_ACTIONS_LOG,
                          {"signal_id": sid, "action": "remind_tomorrow", "ts": now_iso})
        _append_json_list(REDDIT_REMIND_QUEUE,
                          {"signal_id": sid, "text": msg_text, "queued_at": now_iso})
        edit_text(message_id, f"🔁 REMIND TOMORROW — {sid}\n   queued at {now_iso}")
        answer_cb(cb_id, "will remind you tomorrow")

    else:
        answer_cb(cb_id, "unknown signal action")


def handle_callback(cb):
    cb_id = cb["id"]
    data_str = cb.get("data", "")
    msg = cb.get("message", {})
    message_id = msg.get("message_id")

    action, cid = _parse_callback(data_str)
    if not action:
        answer_cb(cb_id, "Unknown action")
        return

    # Pulse signal callbacks (posted/skip/remind on S<n> IDs) go to their own
    # handler so they don't try to look up a non-existent outreach community.
    if action in ("posted", "remind") or (action == "skip" and _is_signal_id(cid)):
        _handle_signal_callback(cb, action, cid)
        return

    db = load_communities()
    c = _find_community(db, cid)
    if not c:
        answer_cb(cb_id, "Community not found")
        return
    today = date.today().isoformat()

    if action == "sent":
        c["status"] = "sent"
        c["sent_at"] = today
        edit_text(message_id,
                  f"✅ SENT — {c['name']}\n"
                  f"   [{c['platform']} · {c['product_match']}]\n"
                  f"   waiting for response …")
        followup = "\n".join([
            SEP, f"✅ {c['name']} — SENT", SEP, "Did they respond?",
        ])
        send_plain(followup, buttons={"inline_keyboard": [[
            {"text": "🎉 They said YES", "callback_data": f"yes_{cid}"},
            {"text": "❌ They said NO", "callback_data": f"no_{cid}"},
            {"text": "⏳ No response yet", "callback_data": f"pending_{cid}"},
        ]]})
        q = load_queue()
        if q and cid in q.get("pending", []) and cid not in q.get("sent_today", []):
            q["sent_today"].append(cid)
            save_queue(q)
        answer_cb(cb_id, "Marked sent")

    elif action == "skip":
        c["status"] = "skipped"
        c["skipped_at"] = today
        edit_text(message_id, f"⏭ SKIPPED — {c['name']}\n   [{c['platform']} · {c['product_match']}]")
        q = load_queue()
        if q and cid in q.get("pending", []):
            q["pending"].remove(cid)
            q.setdefault("skipped_today", []).append(cid)
            save_queue(q)
        answer_cb(cb_id, "Skipped")

    elif action == "edit":
        # Confirmation step — don't change status yet. Prevents accidental edit-flagging.
        edit_text(message_id,
                  "\n".join([
                      SEP,
                      f"✏️ Edit flagged for {c['name']}",
                      SEP,
                  ]),
                  buttons={"inline_keyboard": [
                      [{"text": "↩️ Undo — resend original", "callback_data": f"editundo_{cid}"}],
                      [{"text": "✏️ Confirm edit needed", "callback_data": f"editconfirm_{cid}"}],
                  ]})
        answer_cb(cb_id, "Confirm or undo")

    elif action == "editundo":
        # Restore the original outreach card in place. No status change.
        q = load_queue()
        pending = q.get("pending", []) if q else []
        if cid in pending:
            idx = pending.index(cid) + 1
            total = len(pending)
        else:
            idx, total = 1, 1
        edit_text(message_id, render_outreach_card(c, idx, total), buttons=buttons_outreach(cid))
        answer_cb(cb_id, "Restored")

    elif action == "editconfirm":
        c["status"] = "edit"
        c["edit_flagged_at"] = today
        edit_text(message_id,
                  f"🔄 EDIT FLAGGED — {c['name']}\n"
                  f"   [{c['platform']} · {c['product_match']}]\n"
                  f"   Stays in queue. Revise the draft, then re-deliver.")
        answer_cb(cb_id, "Flagged for edit")

    elif action == "yes":
        c["status"] = "converted"
        c["responded"] = "yes"
        c["converted_at"] = today
        c["review_request_due"] = (date.fromisoformat(today) + timedelta(days=14)).isoformat()
        edit_text(message_id, f"🎉 CONVERTED — {c['name']}")
        post = render_group_post(c)
        card = "\n".join([
            SEP,
            f"🎉 CONVERTED — {c['name']}",
            f"Est. reach: {c['size']}",
            SEP,
            "SHARE THIS WITH THE GROUP:",
            SEP,
            post,
            SEP,
        ])
        send_plain(card, buttons={"inline_keyboard": [[
            {"text": "✅ Group post shared", "callback_data": f"post_shared_{cid}"},
            {"text": "📋 Copy post", "callback_data": f"copy_{cid}"},
        ]]})
        answer_cb(cb_id, "Marked converted")

    elif action == "no":
        c["status"] = "rejected"
        c["responded"] = "no"
        c["rejected_at"] = today
        edit_text(message_id, f"❌ REJECTED — {c['name']}\n   Admin declined. Closed.")
        answer_cb(cb_id, "Marked rejected")

    elif action == "pending":
        # admin not yet responded — keep status="sent", track will nudge later
        edit_text(message_id,
                  f"⏳ WAITING — {c['name']}\n   No response yet. Track will nudge at day 4 / day 10.")
        answer_cb(cb_id, "Tracking")

    elif action == "post_shared":
        c["status"] = "post_shared"
        c["post_shared_at"] = today
        edit_text(message_id,
                  f"✅ GROUP POST SHARED — {c['name']}\n"
                  f"   Review request scheduled for {c.get('review_request_due', '?')}")
        answer_cb(cb_id, "Logged")

    elif action == "copy":
        # Send the post as a standalone clean message for easy phone copy
        send_plain(render_group_post(c))
        answer_cb(cb_id, "Post sent")

    save_communities(db)


def handle(msg):
    text = msg.get("text", "").strip()
    if not text:
        return
    if text in ["/categories", "/categories@Cf_pwa_bot"]:
        cmd_categories()
    elif text.startswith("/add"):
        cmd_add(text[4:].strip())
    elif text.startswith("/remove"):
        cmd_remove(text[7:].strip())
    elif text in ["/status", "/status@Cf_pwa_bot"]:
        cmd_status()
    elif text in ["/signals", "/signals@Cf_pwa_bot"]:
        cmd_signals()
    elif text in ["/products", "/products@Cf_pwa_bot"]:
        cmd_products()
    elif text in ["/outreach", "/outreach@Cf_pwa_bot"]:
        cmd_outreach()
    elif text in ["/start", "/start@Cf_pwa_bot"]:
        send("*Clearfolks HQ Bot*\n\nCommands:\n/categories — tracked category list\n/add Name — add a category\n/remove Name — remove a category\n/signals — latest signal report\n/products — all live products\n/outreach — community outreach pipeline status\n/status — pipeline status")
    else:
        send("Unknown command. Try /start for the full list.")

def run():
    print("Clearfolks HQ bot starting...")
    send("Clearfolks HQ bot is online. Send /start for commands.")
    offset = 0
    while True:
        try:
            result = api("getUpdates", {"offset": offset, "timeout": 10})
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    cb = update["callback_query"]
                    chat_id = cb.get("message", {}).get("chat", {}).get("id")
                    if chat_id == int(CHAT_ID):
                        try:
                            handle_callback(cb)
                        except Exception as e:
                            print(f"callback handler error: {e}")
                            answer_cb(cb.get("id", ""), "error — check logs")
                    continue
                msg = update.get("message", {})
                if msg.get("chat", {}).get("id") == int(CHAT_ID):
                    handle(msg)
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    run()
