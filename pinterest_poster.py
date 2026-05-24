#!/usr/bin/env python3
"""
pinterest_poster.py — schedule Pinterest pins via Buffer.

For each Echo-generated pin draft in ~/clearfolks/drafts/pinterest/:
  1. Parse TITLE / DESCRIPTION / CTA / HASHTAGS / BOARD + Product footer.
  2. Map the product → Hugo cluster (same map sofia_blog.py uses).
  3. Construct the public blog URL  https://blog.clearfolks.com/{cluster}/{slug}
     where slug is the pin TITLE slugified.
  4. Attach the matching branded pin image from static/pin-images/{cluster}.png.
  5. POST to Buffer's update-create endpoint, scheduled at one of the day's
     two pinning slots (10:00 and 17:00 local).  Caps at 2 pins per run.
  6. Move processed drafts to drafts/pinterest/processed/.
  7. Append a JSON-ish line to logs/pinterest.log per draft.
  8. Send a Telegram summary.

Run modes:
  python pinterest_poster.py            # live — posts via Buffer
  python pinterest_poster.py --dry-run  # prints what would be posted, no API

Schedule: 0 10 * * *
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


# ── Config ─────────────────────────────────────────────────────────────────
BASE              = Path("/root/clearfolks")
DRAFTS_DIR        = BASE / "drafts" / "pinterest"
PROCESSED_DIR     = DRAFTS_DIR / "processed"
IMAGES_DIR        = BASE / "static" / "pin-images"
BOARDS_FILE       = BASE / "pinterest_boards.json"
PRODUCTS_FILE     = BASE / "products.json"
LOG_FILE          = BASE / "logs" / "pinterest.log"

BUFFER_API_URL    = "https://api.buffer.com/"  # GraphQL, OIDC bearer token
IMAGES_BASE_URL   = "https://blog.clearfolks.com/pin-images"  # served via Hugo static
BRAND_CLOSE       = "Made by Clearfolk · clearfolks.com"

# Four pins per day at 10am, 1pm, 5pm, 8pm. iter_future_slots cycles through
# these in order, rolling forward to the next day after the last slot fires.
SCHEDULE_SLOTS    = ["10:00", "13:00", "17:00", "20:00"]
MAX_PER_RUN       = 4

FORBIDDEN = [
    "revolutionary", "seamless", "intuitive", "game-changing",
    "simply", "just", "PWA", "Progressive Web App",
]

FORBIDDEN_REPLACEMENTS = {
    "revolutionary":       "meaningful",
    "seamless":            "straightforward",
    "intuitive":           "clear",
    "game-changing":       "useful",
    "simply":              "",
    "just":                "",
    "pwa":                 "app",
    "progressive web app": "app",
}

from clusters import PRODUCT_TO_CLUSTER


# ── Logging ────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Draft parser ───────────────────────────────────────────────────────────
DRAFT_FIELDS = {
    "TITLE":       re.compile(r"^TITLE:\s*(.+)$", re.M),
    "DESCRIPTION": re.compile(r"^DESCRIPTION:\s*(.+(?:\n(?!CTA:|HASHTAGS:|BOARD:|---).+)*)", re.M),
    "CTA":         re.compile(r"^CTA:\s*(.+)$", re.M),
    "HASHTAGS":    re.compile(r"^HASHTAGS:\s*(.+)$", re.M),
    "BOARD":       re.compile(r"^BOARD:\s*(.+)$", re.M),
}
PRODUCT_FOOTER = re.compile(r"\*Generated:.*?\|\s*Product:\s*(.+?)\*", re.S)
SOURCE_HEADER  = re.compile(r"^\*\*Source:\*\*\s*(\S+)", re.M)
PAIN_HEADER    = re.compile(r"^\*\*Pain point:\*\*\s*(.+)$", re.M)


def parse_draft(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8")

    out: dict = {"path": path}

    for key, rx in DRAFT_FIELDS.items():
        m = rx.search(raw)
        out[key.lower()] = m.group(1).strip() if m else ""

    m = PRODUCT_FOOTER.search(raw)
    out["product"] = m.group(1).strip().rstrip("*").strip() if m else ""

    m = SOURCE_HEADER.search(raw)
    out["source"] = m.group(1).strip() if m else ""

    m = PAIN_HEADER.search(raw)
    out["pain_point"] = m.group(1).strip() if m else ""

    if not out["title"] or not out["description"]:
        return None
    return out


def build_alt_text(product: str, pain_point: str) -> str:
    """Pinterest pin alt text. Format:
    '<product name> for <pain summary> - works offline, one payment, lifetime access'
    Lowercase, punctuation stripped, no leading articles. Capped near Pinterest's
    500-char alt-text limit."""
    name = (product or "").strip().lower().removesuffix(" app").strip()
    pain = (pain_point or "").strip().lower()
    # strip trailing period and collapse internal whitespace
    pain = re.sub(r"\s+", " ", pain).rstrip(". ")
    # drop common leading filler so the text reads as a benefit phrase
    pain = re.sub(r"^(a|an|the|someone|people|users?)\s+(who\s+is\s+|who\s+|that\s+(is\s+)?)?", "", pain)
    tail = "works offline, one payment, lifetime access"
    if not name and not pain:
        return tail
    if name and pain:
        text = f"{name} for {pain} - {tail}"
    elif name:
        text = f"{name} - {tail}"
    else:
        text = f"{pain} - {tail}"
    return text[:500]


# ── Helpers ────────────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def strip_forbidden(text: str) -> tuple[str, list[str]]:
    """Replace forbidden words case-insensitively.  Returns (cleaned, found)."""
    found: list[str] = []
    cleaned = text
    for word, replacement in FORBIDDEN_REPLACEMENTS.items():
        rx = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        if rx.search(cleaned):
            found.append(word)
            cleaned = rx.sub(replacement, cleaned)
    # collapse double spaces left behind by replacements
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, found


PINTEREST_MAX_CHARS = 500


def build_post_text(draft: dict, etsy_url: str, max_chars: int = PINTEREST_MAX_CHARS) -> str:
    """Assemble the Pinterest caption — description + CTA + Etsy link + brand close + hashtags.
    The Etsy link is always the last content line before the brand close; no blog URL
    is ever emitted. Pinterest rejects descriptions over 500 chars; if the full caption
    exceeds the cap, the description body is shortened (with an ellipsis) while
    everything else is kept."""
    def assemble(desc: str) -> str:
        link_line = f"find it on etsy: {etsy_url}" if etsy_url else ""
        parts = [
            desc,
            "",
            draft["cta"],
            "",
            link_line,
            "",
            BRAND_CLOSE,
            "",
            draft["hashtags"],
        ]
        return "\n".join(p for p in parts if p != "")

    text = assemble(draft["description"])
    if len(text) <= max_chars:
        return text

    # Reserve room for everything except the description body, then fit the rest.
    overhead = len(assemble("X")) - 1
    budget = max_chars - overhead
    if budget <= 1:
        return text[:max_chars]
    truncated = draft["description"][: budget - 1].rstrip() + "…"
    return assemble(truncated)


def iter_future_slots(reserved: set | None = None):
    """Yield future scheduling slot datetimes forever, skipping any in
    `reserved` (typically pins already scheduled in Buffer from prior runs).

    Slots cycle through SCHEDULE_SLOTS each day, rolling forward to the next
    day after the last slot fires. The very first yielded slot is the next
    SCHEDULE_SLOTS time after `now` that isn't already reserved — so today's
    remaining open slots get used before rolling into tomorrow."""
    reserved = reserved or set()
    now = datetime.now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    while True:
        for slot in SCHEDULE_SLOTS:
            hh, mm = slot.split(":")
            candidate = day.replace(hour=int(hh), minute=int(mm))
            if candidate <= now:
                continue
            if candidate in reserved:
                continue
            yield candidate
        day += timedelta(days=1)


def scheduled_slot_times_from_log() -> set:
    """Set of every `scheduled_at` datetime previously logged as a scheduled
    pin. Lets iter_future_slots avoid double-booking slots that Buffer is
    already holding from earlier runs."""
    out: set = set()
    if not LOG_FILE.exists():
        return out
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("event") != "pin" or ev.get("status") != "scheduled":
                continue
            ts = ev.get("scheduled_at", "")
            if not ts:
                continue
            try:
                out.add(datetime.fromisoformat(ts))
            except Exception:
                continue
    return out


def load_boards_config() -> dict:
    with open(BOARDS_FILE) as f:
        return json.load(f)


def _name_variants(name: str) -> list[str]:
    """Yield every spelling variant we might see for a product name:
    canonical, no-App suffix, '&' ↔ 'and' swap, all four combinations."""
    base = name.removesuffix(" App").strip()
    candidates = {name, base}
    for n in list(candidates):
        if "&" in n:
            candidates.add(n.replace("&", "and"))
        if " and " in n:
            candidates.add(n.replace(" and ", " & "))
    return [c for c in candidates if c]


def load_product_etsy_urls() -> dict:
    """Build product-name → etsy_url map from products.json with alias variants
    so we match whatever the pin draft footer carries (canonical / no-App /
    '&' vs 'and')."""
    with open(PRODUCTS_FILE) as f:
        data = json.load(f)
    out: dict[str, str] = {}
    for p in data.get("products", []):
        url = p.get("etsy_url", "")
        name = p.get("name", "")
        if not url or not name:
            continue
        for variant in _name_variants(name):
            out[variant] = url
    return out


def etsy_url_for(product: str, etsy_map: dict) -> str:
    """Resolve a pin's product name to its Etsy listing URL."""
    if not product:
        return ""
    for variant in _name_variants(product):
        if variant in etsy_map:
            return etsy_map[variant]
    return ""


# ── Buffer GraphQL API ─────────────────────────────────────────────────────
CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt channel { name } } }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on UnexpectedError { message }
    ... on RestProxyError { message link code }
    ... on LimitReachedError { message }
    ... on InvalidInputError { message }
  }
}
""".strip()


def post_to_buffer(token: str, channel_id: str, board_service_id: str,
                   text: str, title: str, link: str, image_url: str,
                   alt_text: str, scheduled_at: datetime) -> tuple[bool, str]:
    """Schedule a Pinterest pin via Buffer GraphQL.  Returns (ok, response_body).

    NOTE: Buffer's GraphQL schema (as of 2026-05-24) does not expose Pinterest
    alt text on either ImageAssetInput or PinterestPostMetadataInput. We still
    generate alt text locally so it can be added manually on Pinterest after
    the pin publishes — see the Telegram summary."""
    due_at_utc = scheduled_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    variables = {
        "input": {
            "channelId":      channel_id,
            "text":           text,
            "schedulingType": "automatic",
            "dueAt":          due_at_utc,
            "mode":           "customScheduled",
            "assets":         [{"image": {"url": image_url}}],
            "metadata": {
                "pinterest": {
                    "title":          title,
                    "url":            link,
                    "boardServiceId": board_service_id,
                }
            },
            "source":      "clearfolks-pinterest-poster",
        }
    }
    payload = json.dumps({"query": CREATE_POST_MUTATION, "variables": variables}).encode()
    req = urllib.request.Request(
        BUFFER_API_URL, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        return False, body or f"HTTPError {e.code} (no body)"
    except Exception as e:
        return False, f"exception: {e}"
    parsed = json.loads(body) if body else {}
    if parsed.get("errors"):
        return False, body
    node = (parsed.get("data") or {}).get("createPost") or {}
    if node.get("__typename") != "PostActionSuccess":
        return False, body
    return True, body


# ── Telegram ───────────────────────────────────────────────────────────────
def send_telegram(message: str) -> None:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("Telegram credentials not set — skipping notification.")
        return
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       message,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Telegram send failed: {e}")


# ── Main pipeline ──────────────────────────────────────────────────────────
def run(dry_run: bool, limit: int | None = None) -> int:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    drafts = sorted(p for p in DRAFTS_DIR.glob("*.md") if p.is_file())
    if not drafts:
        log("No pin drafts found — nothing to do.")
        return 0

    cfg            = load_boards_config()
    boards         = cfg.get("boards", {})
    channel        = cfg.get("channel", {})
    fallback_board = cfg.get("fallback_board", {})
    channel_id     = channel.get("id", "")
    buffer_token   = os.environ.get("BUFFER_TOKEN", "")
    etsy_map       = load_product_etsy_urls()

    safe_mode = False
    if not dry_run and (not buffer_token or not channel_id):
        log("BUFFER_TOKEN or channel.id missing — switching to safe (no-post) mode.")
        safe_mode = True

    today_label = date.today().strftime("%b %d")
    scheduled: list[dict] = []
    skipped:   list[dict] = []

    effective_limit = limit if limit is not None else MAX_PER_RUN
    log(f"Found {len(drafts)} draft(s); will schedule up to {effective_limit}.")

    # Fill any gaps in the schedule, skipping slots already booked in prior
    # runs. The iterator starts from "now" and yields the next open slot,
    # so today's remaining slots get used before rolling into tomorrow.
    reserved = scheduled_slot_times_from_log()
    if reserved:
        log(f"Avoiding {len(reserved)} already-scheduled slot(s) from prior runs.")
    slot_iter = iter_future_slots(reserved=reserved)

    for draft_path in drafts[:effective_limit]:
        draft = parse_draft(draft_path)
        if not draft:
            log(f"  Skipping {draft_path.name} — missing TITLE/DESCRIPTION.")
            skipped.append({"file": draft_path.name, "reason": "unparseable"})
            continue

        cluster = PRODUCT_TO_CLUSTER.get(draft["product"], "generic")
        etsy_url = etsy_url_for(draft["product"], etsy_map)
        if not etsy_url:
            log(f"  ⚠ No etsy_url for product '{draft['product']}' — skipping.")
            skipped.append({"file": draft_path.name, "status": "skipped:no_etsy_url",
                            "product": draft["product"]})
            continue

        image_path = IMAGES_DIR / f"{cluster}.png"
        # Buffer/Pinterest reject "Whoops, you've posted that one recently" when
        # the same image URL gets reused. Append a per-pin query string so each
        # scheduling attempt has a unique URL. (Image bytes are the same; if
        # Buffer hashes bytes too, we'll need per-pin image rendering next.)
        pin_token = slugify(draft["title"])[:40] or "pin"
        image_url = f"{IMAGES_BASE_URL}/{cluster}.png?p={pin_token}"

        # Sanitize forbidden words in the caption + hashtags
        clean_desc,    bad_desc    = strip_forbidden(draft["description"])
        clean_cta,     bad_cta     = strip_forbidden(draft["cta"])
        clean_hash,    bad_hash    = strip_forbidden(draft["hashtags"])
        draft["description"], draft["cta"], draft["hashtags"] = clean_desc, clean_cta, clean_hash
        all_bad = sorted(set(bad_desc + bad_cta + bad_hash))

        caption = build_post_text(draft, etsy_url)
        alt_text = build_alt_text(draft["product"], draft.get("pain_point", ""))
        scheduled_at = next(slot_iter)

        board_meta       = boards.get(cluster, {})
        board_name       = board_meta.get("board", "")
        board_service_id = board_meta.get("board_service_id", "REPLACE_ME")
        used_fallback    = False
        if board_service_id == "REPLACE_ME":
            board_service_id = fallback_board.get("board_service_id", "REPLACE_ME")
            board_name       = f"{fallback_board.get('board','?')} (fallback for {cluster})"
            used_fallback    = True

        record = {
            "file":             draft_path.name,
            "product":          draft["product"],
            "cluster":          cluster,
            "board":            board_name,
            "board_service_id": board_service_id,
            "used_fallback":    used_fallback,
            "title":            draft["title"],
            "etsy_url":         etsy_url,
            "alt_text":         alt_text,
            "image_path":       str(image_path),
            "image_url":        image_url,
            "scheduled_at":     scheduled_at.isoformat(timespec="minutes"),
            "forbidden_stripped": all_bad,
            "caption":          caption,
        }

        if not image_path.exists():
            log(f"  ⚠ Image not found for cluster '{cluster}' — {image_path}")
            record["status"] = "skipped:no_image"
            skipped.append(record)
            continue

        if dry_run:
            log(f"  [DRY-RUN] would schedule pin from {draft_path.name}")
            log(f"    cluster      : {cluster}")
            log(f"    product      : {draft['product']}")
            log(f"    board        : {board_name}  (board_service_id={board_service_id})")
            log(f"    title        : {draft['title']}")
            log(f"    etsy url     : {etsy_url}")
            log(f"    alt text     : {alt_text}")
            log(f"    image (file) : {image_path}  ({'exists' if image_path.exists() else 'MISSING'})")
            log(f"    image (url)  : {image_url}")
            log(f"    scheduled_at : {record['scheduled_at']}")
            if all_bad:
                log(f"    ⚠ forbidden words stripped: {', '.join(all_bad)}")
            log(f"    caption ↓↓↓")
            for ln in caption.split("\n"):
                log(f"      {ln}")
            log(f"    caption ↑↑↑ ({len(caption)} chars)")
            record["status"] = "dry-run"
            scheduled.append(record)
            continue

        if safe_mode or board_service_id == "REPLACE_ME":
            log(f"  ⏸ Safe mode (no token/channel or placeholder board) — not posting {cluster}.")
            record["status"] = "skipped:safe_mode"
            skipped.append(record)
            continue

        ok, body = post_to_buffer(
            token=buffer_token,
            channel_id=channel_id,
            board_service_id=board_service_id,
            text=caption,
            title=draft["title"],
            link=etsy_url,
            image_url=image_url,
            alt_text=alt_text,
            scheduled_at=scheduled_at,
        )
        try:
            pretty_body = json.dumps(json.loads(body), indent=2)
        except Exception:
            pretty_body = body
        if ok:
            log(f"  ✓ Scheduled {cluster} on Buffer @ {record['scheduled_at']}")
            log("  Buffer response ↓↓↓")
            for ln in pretty_body.split("\n"):
                log(f"    {ln}")
            log("  Buffer response ↑↑↑")
            record["status"] = "scheduled"
            scheduled.append(record)
            shutil.move(str(draft_path), str(PROCESSED_DIR / draft_path.name))
        else:
            log(f"  ✗ Buffer error for {draft_path.name}")
            log("  Buffer response ↓↓↓")
            for ln in pretty_body.split("\n"):
                log(f"    {ln}")
            log("  Buffer response ↑↑↑")
            record["status"] = f"error: {body[:120]}"
            skipped.append(record)

    # Append structured records
    with open(LOG_FILE, "a") as f:
        for r in scheduled + skipped:
            f.write(json.dumps({"event": "pin", **{k: v for k, v in r.items() if k != "caption"}}) + "\n")

    # Telegram summary
    lines = [f"📌 <b>Pinterest Report — {today_label}</b>", ""]
    if dry_run:
        lines.append("<i>DRY RUN — nothing was posted.</i>")
        lines.append("")
    if scheduled:
        lines.append(f"✅ Scheduled {len(scheduled)} pin(s):")
        for r in scheduled:
            fb = "  (fallback board)" if r.get("used_fallback") else ""
            lines.append(f"  • [{r['cluster']}] {r['title']}{fb}")
            lines.append(f"     board: {r.get('board','?')}")
            lines.append(f"     → {r['etsy_url']}")
            if r.get("alt_text"):
                lines.append(f"     alt (paste on Pinterest): {r['alt_text']}")
    if skipped:
        lines.append("")
        lines.append(f"⚠️ Skipped {len(skipped)}:")
        for r in skipped:
            lines.append(f"  • {r.get('file','?')} — {r.get('status','?')}")
    lines.append("")
    lines.append(BRAND_CLOSE)
    summary = "\n".join(lines)

    if dry_run:
        log("--- TELEGRAM SUMMARY (not sent in dry-run) ---")
        for ln in summary.split("\n"):
            log(ln)
    else:
        send_telegram(summary)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Schedule Pinterest pins via Buffer.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                     help="Show what would be scheduled without calling Buffer.")
    mode.add_argument("--live", action="store_true",
                     help="Explicit opt-in for live posting (same as default; useful for ad-hoc runs).")
    parser.add_argument("--limit", type=int, default=None,
                        help=f"Cap drafts processed this run (default {MAX_PER_RUN}).")
    args = parser.parse_args()

    log("=" * 60)
    log(f"Pinterest poster starting (dry_run={args.dry_run}, live={args.live}, limit={args.limit})")
    log("=" * 60)

    rc = run(dry_run=args.dry_run, limit=args.limit)

    log("Pinterest poster complete.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
