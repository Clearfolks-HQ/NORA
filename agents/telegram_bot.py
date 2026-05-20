#!/usr/bin/env python3
"""
Clearfolks HQ Telegram Bot
Commands: /categories /add /remove /status /signals /products
"""

import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

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
    elif text in ["/start", "/start@Cf_pwa_bot"]:
        send("*Clearfolks HQ Bot*\n\nCommands:\n/categories — tracked category list\n/add Name — add a category\n/remove Name — remove a category\n/signals — latest signal report\n/products — all live products\n/status — pipeline status")
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
                msg = update.get("message", {})
                if msg.get("chat", {}).get("id") == int(CHAT_ID):
                    handle(msg)
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(1)

if __name__ == "__main__":
    run()
