#!/usr/bin/env python3
"""One-off: parse today's signals report and push ALL signals to Telegram
in the same format pulse.send_daily_push uses for the top 3."""

import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

from clusters import product_to_cluster

REPORT_PATH = sys.argv[1] if len(sys.argv) > 1 else (
    f"/root/clearfolks/signals/signals-{datetime.now().strftime('%Y-%m-%d')}.md"
)
BLOG_BASE_URL = "https://blog.clearfolks.com"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Markdown failed ({e.code}): {body[:200]} — retrying as plain text")
        data2 = urllib.parse.urlencode({
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": "true",
        }).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data2), timeout=15)


def parse_report(path):
    with open(path) as f:
        text = f.read()
    blocks = re.split(r"\n## Signal \d+ — Score ", text)[1:]
    signals = []
    for b in blocks:
        score = re.match(r"(\d+)/10", b).group(1)
        def grab(label, body=b):
            m = re.search(rf"\*\*{label}:\*\*\s*(.+?)(?=\n\n|\Z)", body, re.S)
            return m.group(1).strip() if m else ""
        title_match = re.search(r"\*\*Post:\*\* \[(.+?)\]\((.+?)\)", b)
        title = title_match.group(1) if title_match else ""
        url = title_match.group(2) if title_match else ""
        # Suggested response is everything between "Suggested response:" and "---"
        sr = re.search(r"\*\*Suggested response:\*\*\s*\n\n(.+?)\n\n---", b, re.S)
        suggested = sr.group(1).strip() if sr else ""
        signals.append({
            "score": score,
            "subreddit": grab("Subreddit"),
            "post_title": title,
            "post_url": url,
            "pain_point": grab("Pain point"),
            "product_match": grab("Product match"),
            "suggested_response": suggested,
        })
    return signals


def build_reply_with_blog(suggested, cluster):
    reply = (suggested or "").rstrip()
    if not cluster:
        return reply
    blog_path = f"blog.clearfolks.com/{cluster}/"
    if blog_path in reply:
        return reply
    return f"{reply}\n\nI wrote a full guide on this: {blog_path}"


def main():
    signals = parse_report(REPORT_PATH)
    total = len(signals)
    date_str = datetime.now().strftime("%b %d")

    header = (
        f"*Clearfolks signals — {date_str} (FULL REPORT)*\n"
        f"_{total} signals with rewritten human-tone responses. Sending all below._"
    )
    send(header)
    time.sleep(0.5)

    for i, s in enumerate(signals, 1):
        product_name = s.get("product_match", "").replace("Upcoming: ", "").strip()
        cluster = product_to_cluster(product_name)
        blog_url = f"{BLOG_BASE_URL}/{cluster}/" if cluster else ""
        reply = build_reply_with_blog(s.get("suggested_response", ""), cluster)
        blog_line = f"\n\n*Blog post:*\n{blog_url}" if blog_url else ""

        text = (
            f"*Signal {i}/{total} — Score {s['score']}/10*\n"
            f"*Where:* {s['subreddit']}\n"
            f"*Post:* {s['post_title']}\n"
            f"*Pain:* {s['pain_point']}\n"
            f"*Product:* {product_name}\n\n"
            f"*Reply to copy:*\n{reply}\n\n"
            f"*Reddit link:*\n{s['post_url']}"
            f"{blog_line}"
        )
        if len(text) > 4000:
            text = text[:3900] + "\n_...truncated_"
        send(text)
        time.sleep(0.4)  # avoid Telegram rate limit (30 msgs/sec hard, ~1/sec safe)
        print(f"  sent {i}/{total}")

    print(f"Done — {total + 1} messages sent.")


if __name__ == "__main__":
    main()
