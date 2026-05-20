#!/usr/bin/env python3
"""
quora_poster.py — daily Quora answer dispatcher.

Picks one unprocessed answer from ~/clearfolks/drafts/quora/, formats it for
Telegram so Debajit can copy-paste it into the matching Quora question
manually (Quora has no public posting API), and moves the file to
drafts/quora/processed/.

Schedule: 30 8 * * * (between Echo at 7:30am and Sofia at 9am).

Run modes:
  python quora_poster.py            # live — sends to Telegram, archives draft
  python quora_poster.py --dry-run  # prints the would-be Telegram message, no send, no move
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


BASE          = Path("/root/clearfolks")
DRAFTS_DIR    = BASE / "drafts" / "quora"
PROCESSED_DIR = DRAFTS_DIR / "processed"
LOG_FILE      = BASE / "logs" / "quora.log"

TELEGRAM_LIMIT = 4096  # hard ceiling per message


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def parse_answer_file(path: Path) -> dict:
    """Split YAML-ish frontmatter from the answer body. Returns dict with
    meta fields + 'body'. Raises ValueError on malformed input."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path.name}: malformed frontmatter")
    meta_raw = parts[1].strip()
    body = parts[2].strip()

    meta = {}
    for line in meta_raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        # strip surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            try:
                value = json.loads(value)
            except Exception:
                value = value[1:-1]
        meta[key.strip()] = value

    meta["body"] = body
    return meta


def pick_next_draft() -> Path | None:
    """Pick the next answer to send: lowest priority number wins, ties broken
    alphabetically by cluster, then by filename."""
    drafts = [p for p in DRAFTS_DIR.glob("*.md") if p.is_file()]
    if not drafts:
        return None

    def sort_key(p: Path):
        try:
            meta = parse_answer_file(p)
            return (int(meta.get("priority", 99)), meta.get("cluster", ""), p.name)
        except Exception:
            return (99, "", p.name)

    drafts.sort(key=sort_key)
    return drafts[0]


def build_telegram_message(meta: dict) -> str:
    """Format the answer for Telegram. Sent as plain text — no parse_mode —
    so quotes, apostrophes, em-dashes etc. pass through as written and the
    operator can copy-paste straight into Quora."""
    date_str = datetime.now().strftime("%b %d, %Y")
    question = meta.get("question", "(no question)")
    url      = meta.get("url", "")
    cluster  = meta.get("cluster", "")
    body     = meta.get("body", "")

    def assemble(b: str) -> str:
        return (
            f"📝 Quora Answer — {date_str}\n\n"
            f"Question: {question}\n"
            f"URL: {url}\n\n"
            f"--- ANSWER (copy this) ---\n"
            f"{b}\n"
            f"---\n\n"
            f"Blog link included: blog.clearfolks.com/{cluster}/"
        )

    msg = assemble(body)
    if len(msg) > TELEGRAM_LIMIT:
        overflow = len(msg) - TELEGRAM_LIMIT + 16
        msg = assemble(body[:-overflow] + "…")
    return msg


def send_telegram(message: str) -> bool:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("Telegram credentials not set — skipping send.")
        return False
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       message,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except Exception as e:
        log(f"Telegram send failed: {e}")
        return False


def archive(path: Path) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROCESSED_DIR / path.name
    if dest.exists():
        ts = datetime.now().strftime("%H%M%S")
        dest = PROCESSED_DIR / f"{path.stem}-{ts}{path.suffix}"
    shutil.move(str(path), str(dest))
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the would-be Telegram message; don't send or archive.")
    args = ap.parse_args()

    draft = pick_next_draft()
    if draft is None:
        log("No unprocessed Quora answers in drafts/quora/ — nothing to do.")
        return 0

    try:
        meta = parse_answer_file(draft)
    except Exception as e:
        log(f"Could not parse {draft.name}: {e}")
        return 1

    cluster  = meta.get("cluster", "?")
    priority = meta.get("priority", "?")
    log(f"Selected draft: {draft.name}  (cluster={cluster}, priority={priority})")

    message = build_telegram_message(meta)

    if args.dry_run:
        print("\n----- TELEGRAM MESSAGE (dry-run) -----")
        print(message)
        print("----- END MESSAGE -----\n")
        log(f"Dry-run — would have sent {draft.name} ({len(message)} chars).")
        return 0

    if not send_telegram(message):
        log(f"Send failed for {draft.name} — leaving in drafts for retry.")
        return 1

    dest = archive(draft)
    log(f"Sent {draft.name} to Telegram and archived to {dest.relative_to(BASE)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
