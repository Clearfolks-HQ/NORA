"""
OrganicOS Dashboard — Flask backend.

Parses pipeline logs/signals/drafts on demand and exposes them to the
single-page dashboard frontend. Writes Reddit actions back to disk.
"""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import sys
sys.path.insert(0, "/root/clearfolks")
from reddit_drafts import (  # noqa: E402
    all_drafts as load_reddit_drafts,
    history as reddit_history,
    mark_action as mark_reddit_action,
    load_draft as load_reddit_draft,
)

ROOT = Path("/root/clearfolks")
SIGNALS_DIR = ROOT / "signals"
LOGS_DIR = ROOT / "logs"
DRAFTS_DIR = ROOT / "drafts"
DATA_DIR = ROOT / "data"
BLOG_PUBLIC = Path("/var/www/clearfolks-blog/public")

ACTIONS_FILE = LOGS_DIR / "reddit_posted.json"
LEGACY_ACTIONS_FILE = LOGS_DIR / "reddit_actions.json"
CONTENT_POSTED_FILE = LOGS_DIR / "content_posted.json"

BACKLOG_VALUE_DIR    = DRAFTS_DIR / "reddit" / "value-posts"
BACKLOG_PROBLEM_DIR  = DRAFTS_DIR / "reddit" / "problem-posts"
BACKLOG_BLOG_DIR     = DRAFTS_DIR / "reddit" / "blog-posts"
PINTEREST_DRAFTS_DIR = DRAFTS_DIR / "pinterest"
BLOG_OUTLINES_DIR    = DRAFTS_DIR / "blog" / "processed"

AGENTS = [
    {"key": "pulse",     "label": "Pulse",     "schedule": "Daily 7:00am",   "log": "pulse.log"},
    {"key": "echo",      "label": "Echo",      "schedule": "Daily 7:30am",   "log": "echo.log"},
    {"key": "sofia",     "label": "Sofia",     "schedule": "Monday 8:00am",  "log": "sofia.log"},
    {"key": "research",  "label": "Research",  "schedule": "Monthly 1st",    "log": None},
    {"key": "discover",  "label": "Discover",  "schedule": "Sunday 6:00am",  "log": "discover.log"},
    {"key": "pinterest", "label": "Pinterest", "schedule": "Daily 10:00am",  "log": "pinterest.log"},
    {"key": "quora",     "label": "Quora",     "schedule": "Daily 8:30am",   "log": "quora.log"},
    {"key": "sofia_blog","label": "Sofia Blog","schedule": "Daily 9:00am",   "log": "sofia_blog.log"},
    {"key": "outreach",  "label": "Outreach",  "schedule": "Daily 8:00am",   "log": "outreach.log"},
]

app = Flask(__name__, static_folder=None)


# ───────────── Signal parser ─────────────

def _parse_signal_block(idx: int, block: str) -> dict | None:
    """Pull the user-facing fields out of one '## Signal N' chunk of markdown."""
    def first(pattern):
        m = re.search(pattern, block, re.DOTALL)
        return m.group(1).strip() if m else ""

    score_match = re.search(r"Score (\d+)/10", block)
    subreddit = first(r"\*\*Subreddit:\*\*\s*(r/[^\n]+)")
    cat = first(r"\*\*Category:\*\*\s*([^\n]+)")
    post_link = re.search(r"\*\*Post:\*\*\s*\[([^\]]+)\]\(([^)]+)\)", block, re.DOTALL)
    post_title = post_link.group(1).strip() if post_link else ""
    post_url = post_link.group(2).strip() if post_link else ""
    quote = first(r"\*\*Key quote:\*\*\s*\"([^\"]+)\"")
    pain = first(r"\*\*Pain point:\*\*\s*([^\n]+)")
    product = first(r"\*\*Product match:\*\*\s*([^\n]+)")
    reply = first(r"\*\*Suggested response:\*\*\s*\n+([\s\S]+?)(?:\n\n\*\*Discussion thread|\n\n---|\Z)")
    discussion_thread = first(r"\*\*Discussion thread:\*\*\s*([^\n]+)")
    discussion_post = first(r"\*\*Discussion thread post:\*\*\s*\n+([\s\S]+?)(?:\n\n---|\Z)")

    if not post_title and not subreddit:
        return None

    return {
        "id": f"S{idx}",
        "score": int(score_match.group(1)) if score_match else None,
        "category": cat,
        "subreddit": subreddit,
        "post_title": post_title,
        "post_url": post_url,
        "key_quote": quote,
        "pain_point": pain,
        "product_match": product,
        "suggested_reply": reply.strip(),
        "discussion_thread": discussion_thread,
        "discussion_post": discussion_post.strip() if discussion_post else "",
    }


def load_signals_for(d: date) -> tuple[list[dict], str | None]:
    """Return (signals, path_used). Falls back to most-recent file if none for today."""
    target = SIGNALS_DIR / f"signals-{d.isoformat()}.md"
    used = target if target.exists() else None
    if used is None:
        candidates = sorted(SIGNALS_DIR.glob("signals-*.md"), reverse=True)
        if candidates:
            used = candidates[0]
    if used is None or not used.exists():
        return [], None

    text = used.read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n## Signal \d+", text)[1:]
    signals = []
    for i, block in enumerate(blocks, 1):
        parsed = _parse_signal_block(i, "## Signal " + block)
        if parsed:
            signals.append(parsed)
    return signals, str(used)


# ───────────── Actions log ─────────────

def _load_actions() -> list[dict]:
    """Merge the new actions file with the legacy one, treating both as source-of-truth."""
    out = []
    for path in (LEGACY_ACTIONS_FILE, ACTIONS_FILE):
        if path.exists():
            try:
                data = json.loads(path.read_text() or "[]")
                if isinstance(data, list):
                    out.extend(data)
            except json.JSONDecodeError:
                pass
    return out


def _action_status_map(signal_date: str) -> dict[str, str]:
    """Map signal_id → most-recent action for the given signal report date."""
    actions = _load_actions()
    same_day = [a for a in actions if (a.get("ts") or "").startswith(signal_date)]
    same_day.sort(key=lambda a: a.get("ts", ""))
    status = {}
    for a in same_day:
        sid = a.get("signal_id")
        act = a.get("action")
        if sid and act:
            status[sid] = act
    return status


# ───────────── Pipeline status ─────────────

def _file_mtime_iso(p: Path) -> str | None:
    if not p.exists():
        return None
    return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")


def _next_run_for(schedule: str, now: datetime) -> str:
    """Compute a human-readable next-run from the agent's schedule string."""
    if "Monday" in schedule:
        days_ahead = (0 - now.weekday()) % 7 or 7
        target = (now + timedelta(days=days_ahead)).replace(hour=8, minute=0, second=0, microsecond=0)
    elif "Sunday" in schedule:
        days_ahead = (6 - now.weekday()) % 7 or 7
        target = (now + timedelta(days=days_ahead)).replace(hour=6, minute=0, second=0, microsecond=0)
    elif "Monthly" in schedule:
        if now.month == 12:
            target = now.replace(year=now.year + 1, month=1, day=1, hour=5, minute=0, second=0, microsecond=0)
        else:
            target = now.replace(month=now.month + 1, day=1, hour=5, minute=0, second=0, microsecond=0)
    elif "Daily" in schedule:
        m = re.search(r"(\d+):(\d+)", schedule)
        if not m:
            return ""
        hh, mm = int(m.group(1)), int(m.group(2))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
    else:
        return ""
    return target.isoformat(timespec="minutes")


def pipeline_status() -> list[dict]:
    now = datetime.now()
    rows = []
    for a in AGENTS:
        log_path = LOGS_DIR / a["log"] if a["log"] else None
        last_run = _file_mtime_iso(log_path) if log_path else None
        # Research has no dedicated log; check signals dir for a research-* file
        if a["key"] == "research":
            files = sorted(SIGNALS_DIR.parent.glob("logs/research-*.json"), reverse=True)
            if files:
                last_run = _file_mtime_iso(files[0])
        rows.append({
            "key": a["key"],
            "label": a["label"],
            "schedule": a["schedule"],
            "last_run": last_run,
            "next_run": _next_run_for(a["schedule"], now),
        })
    return rows


# ───────────── Pinterest pins posted today ─────────────

_PIN_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}) [\d:]+\]\s+✓ Scheduled (\S+) on Buffer @ (\S+)")


def pinterest_today() -> list[dict]:
    """Each line in pinterest.log: '[ts] ✓ Scheduled <board> on Buffer @ <due>'."""
    today_iso = date.today().isoformat()
    log = LOGS_DIR / "pinterest.log"
    if not log.exists():
        return []
    pins = []
    seen = set()
    for line in log.read_text(errors="ignore").splitlines():
        m = _PIN_RE.search(line)
        if not m:
            continue
        ran, board, due = m.group(1), m.group(2), m.group(3)
        # Show pins scheduled to go out today
        if due.startswith(today_iso):
            key = (board, due)
            if key in seen:
                continue
            seen.add(key)
            pins.append({"board": board, "scheduled_at": due, "scheduled_by_run_on": ran})
    return pins


# ───────────── Blog posts this week ─────────────

def _scan_blog_posts() -> list[dict]:
    """Each post's index.html has '<time datetime=YYYY-MM-DD itemprop=datePublished>' from Hugo."""
    if not BLOG_PUBLIC.exists():
        return []
    posts = []
    # Top-level category/section pages have no '-' in slug (e.g. /wedding/, /baby/, /homeschool/).
    # Real post slugs are long and hyphenated, so we skip directories whose name has no hyphen.
    skip = {"css", "categories", "clusters", "tags", "page"}
    for d in BLOG_PUBLIC.iterdir():
        if not d.is_dir() or d.name in skip or d.name.startswith("."):
            continue
        if "-" not in d.name:
            continue
        idx = d / "index.html"
        if not idx.exists():
            continue
        try:
            head = idx.read_text(errors="ignore")[:6000]
        except OSError:
            continue
        date_m = (
            re.search(r'article:published_time"\s+content="(\d{4}-\d{2}-\d{2})', head)
            or re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', head)
            or re.search(r'<time[^>]*datetime=["\']?(\d{4}-\d{2}-\d{2})', head)
        )
        if not date_m:
            continue
        title_m = re.search(r"<title>([^<]+)</title>", head)
        title = title_m.group(1).replace(" | Clearfolks", "").strip() if title_m else d.name.replace("-", " ").title()
        # Strip trailing " — Clearfolks Blog" style suffixes
        title = re.sub(r"\s*[—–-]\s*Clearfolks(\s*Blog)?\s*$", "", title)
        posts.append({
            "title": title,
            "url": f"https://blog.clearfolks.com/{d.name}/",
            "date": date_m.group(1),
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def blog_week() -> list[dict]:
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    return [p for p in _scan_blog_posts() if p["date"] >= cutoff]


# ───────────── Stats ─────────────

def quick_stats() -> dict:
    products = []
    try:
        products = json.loads((DATA_DIR / "products.json").read_text()).get("products", [])
    except (OSError, json.JSONDecodeError):
        pass
    live = sum(1 for p in products if p.get("status") == "live")
    etsy_live = sum(1 for p in products if p.get("etsy_listing") == "live")

    sub_count = 0
    try:
        sd = json.loads((DATA_DIR / "subreddits.json").read_text())
        # New format: products map, each with primary + secondary subreddits
        if "products" in sd:
            uniq = set()
            for p in sd["products"].values():
                if p.get("primary_subreddit"):
                    uniq.add(p["primary_subreddit"].lower())
                for s in p.get("secondary_subreddits", []) or []:
                    uniq.add(s.lower())
            sub_count = len(uniq)
        else:
            flat = sd.get("flat_list") or []
            sub_count = len(flat) if flat else sum(len(v) for v in sd.get("by_category", {}).values() if isinstance(v, list))
    except (OSError, json.JSONDecodeError):
        pass

    blog_count = len(_scan_blog_posts())

    boards = 0
    try:
        b = json.loads((ROOT / "pinterest_boards.json").read_text())
        boards = len(b) if isinstance(b, list) else len(b.keys())
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "products_total": len(products),
        "products_live": live,
        "etsy_live": etsy_live,
        "blog_posts": blog_count,
        "pinterest_boards": boards,
        "subreddits": sub_count,
    }


# ───────────── Action tracker (this week) ─────────────

def action_tracker() -> dict:
    monday = date.today() - timedelta(days=date.today().weekday())
    monday_iso = monday.isoformat()

    actions = _load_actions()
    reddit_posted = sum(1 for a in actions if a.get("action") == "posted" and (a.get("ts") or "") >= monday_iso)
    reddit_skipped = sum(1 for a in actions if a.get("action") == "skipped" and (a.get("ts") or "") >= monday_iso)
    reddit_remind = sum(1 for a in actions if a.get("action") == "remind" and (a.get("ts") or "") >= monday_iso)

    # Today's signals minus today's actions = pending
    sigs, _ = load_signals_for(date.today())
    today_actions = _action_status_map(date.today().isoformat())
    pending = sum(1 for s in sigs if s["id"] not in today_actions)

    pins_this_week = 0
    pin_log = LOGS_DIR / "pinterest.log"
    if pin_log.exists():
        for line in pin_log.read_text(errors="ignore").splitlines():
            m = _PIN_RE.search(line)
            if m and m.group(1) >= monday_iso:
                pins_this_week += 1

    blog_this_week = len(blog_week())

    # Quora: count processed drafts moved this week
    quora_count = 0
    proc = DRAFTS_DIR / "quora" / "processed"
    if proc.exists():
        for f in proc.iterdir():
            if f.is_file():
                mt = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
                if mt >= monday_iso:
                    quora_count += 1

    return {
        "week_start": monday_iso,
        "reddit_posted": reddit_posted,
        "reddit_skipped": reddit_skipped,
        "reddit_remind": reddit_remind,
        "reddit_pending": pending,
        "pinterest_pins": pins_this_week,
        "blog_posts": blog_this_week,
        "quora_answers": quora_count,
    }


# ───────────── Content Backlog (value / problem / blog_link / pinterest / blog) ─────────────

PRODUCT_CATALOG: dict[str, str] = {}
PRODUCT_URLS: dict[str, str] = {}


def _load_products():
    """Load product names + URLs from products.json (try data/ then root)."""
    global PRODUCT_CATALOG, PRODUCT_URLS
    if PRODUCT_CATALOG:
        return
    for path in (DATA_DIR / "products.json", ROOT / "products.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        items = data if isinstance(data, list) else data.get("products", [])
        for p in items:
            slug = (p.get("url", "") or "").rstrip("/").split("/")[-1]
            for key in (p.get("id"), p.get("slug"), slug):
                if key:
                    PRODUCT_CATALOG.setdefault(key, p.get("name", ""))
                    if p.get("url"):
                        PRODUCT_URLS.setdefault(key, p["url"])
            if p.get("name"):
                PRODUCT_CATALOG.setdefault(p["name"], p["name"])


def _load_subreddit_map() -> dict:
    """Return the products->subreddit map from subreddits.json (new format)."""
    try:
        sd = json.loads((DATA_DIR / "subreddits.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return sd.get("products", {}) if isinstance(sd, dict) else {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for a yaml-fronted markdown file."""
    fm: dict = {}
    body = text
    if text.startswith("---"):
        try:
            end = text.index("\n---", 3)
        except ValueError:
            return fm, body
        head = text[3:end].strip()
        body = text[end + 4:].lstrip("\n")
        for line in head.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def _backlog_status_map() -> dict[str, str]:
    """draft_filename → most-recent status (posted/skipped/scheduled) from content_posted.json."""
    if not CONTENT_POSTED_FILE.exists():
        return {}
    try:
        data = json.loads(CONTENT_POSTED_FILE.read_text() or "[]")
    except json.JSONDecodeError:
        return {}
    status: dict[str, str] = {}
    for entry in data if isinstance(data, list) else []:
        key = entry.get("file") or entry.get("draft_id")
        if key:
            status[key] = entry.get("status", "posted")
    return status


def _backlog_title(body: str, fallback: str) -> str:
    """First markdown heading or the fallback filename."""
    for line in body.splitlines():
        m = re.match(r"^#+\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return fallback


def _backlog_first_lines(body: str, n: int = 3) -> str:
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
        if len(lines) >= n:
            break
    return "\n".join(lines)


def _read_backlog(dir_path: Path, kind: str) -> list[dict]:
    if not dir_path.exists():
        return []
    _load_products()
    sub_map = _load_subreddit_map()
    status_map = _backlog_status_map()
    out = []
    for f in sorted(dir_path.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        fm, body = _parse_frontmatter(text)
        product_key = fm.get("product", "")
        product_name = fm.get("product_name") or PRODUCT_CATALOG.get(product_key, product_key)
        subreddit = fm.get("subreddit") or (sub_map.get(product_key, {}) or {}).get("primary_subreddit", "")
        title = _backlog_title(body, f.stem)
        status = status_map.get(f.name, fm.get("status", "draft"))
        entry = {
            "file": f.name,
            "product": product_key,
            "product_name": product_name,
            "subreddit": subreddit,
            "title": title,
            "preview": _backlog_first_lines(body, 3),
            "body": body,
            "status": status,
            "type": kind,
            "created": fm.get("created", ""),
        }
        if kind == "blog_link":
            entry["blog_url"] = fm.get("blog_url", "")
        out.append(entry)
    return out


def backlog_value_posts() -> list[dict]:
    return _read_backlog(BACKLOG_VALUE_DIR, "value_post")


def backlog_problem_posts() -> list[dict]:
    return _read_backlog(BACKLOG_PROBLEM_DIR, "problem_post")


def backlog_blog_posts() -> list[dict]:
    return _read_backlog(BACKLOG_BLOG_DIR, "blog_link")


_PIN_TITLE_RE   = re.compile(r"^TITLE:\s*(.+)$", re.MULTILINE)
_PIN_BOARD_RE   = re.compile(r"^BOARD:\s*(.+)$", re.MULTILINE)
_PIN_PRODUCT_RE = re.compile(r"\| Product:\s*([^|*\n]+)")
_PIN_DESC_RE    = re.compile(r"^DESCRIPTION:\s*(.+)$", re.MULTILINE)


def backlog_pinterest() -> list[dict]:
    """Pinterest pin drafts queued for posting."""
    if not PINTEREST_DRAFTS_DIR.exists():
        return []
    _load_products()
    out = []
    posted_log = LOGS_DIR / "pinterest_posted.json"
    posted_files: set[str] = set()
    if posted_log.exists():
        try:
            d = json.loads(posted_log.read_text() or "[]")
            posted_files = {x.get("file") for x in d if isinstance(d, list) and x.get("file")}
        except json.JSONDecodeError:
            pass

    for f in sorted(PINTEREST_DRAFTS_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        title_m  = _PIN_TITLE_RE.search(text)
        board_m  = _PIN_BOARD_RE.search(text)
        prod_m   = _PIN_PRODUCT_RE.search(text)
        desc_m   = _PIN_DESC_RE.search(text)
        # Extract Etsy URL if present anywhere in the file
        etsy_m = re.search(r"https?://(?:www\.)?etsy\.com/\S+", text)
        if not etsy_m:
            etsy_m = re.search(r"https?://app\.clearfolks\.com/\S+", text)
        status = "posted" if f.name in posted_files else "queued"
        out.append({
            "file": f.name,
            "title": title_m.group(1).strip() if title_m else f.stem,
            "board": board_m.group(1).strip() if board_m else "",
            "product_name": prod_m.group(1).strip() if prod_m else "",
            "description": desc_m.group(1).strip() if desc_m else "",
            "etsy_url": etsy_m.group(0).strip() if etsy_m else "",
            "status": status,
        })
    return out


def _blog_outline_meta(path: Path) -> dict:
    """Map blog outline filename to a {title, product} dict."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"file": path.name, "title": path.stem.replace("-", " "), "product": ""}
    # Outlines tend to have a # heading near the top
    title = path.stem.replace("-", " ")
    for line in text.splitlines()[:30]:
        m = re.match(r"^#+\s+(.+)$", line.strip())
        if m:
            title = m.group(1).strip()
            break
    # Product tag in name like "homeschool-1.md" → homeschool
    base = path.stem
    # Strip leading date YYYY-MM-DD-NN- and trailing -N
    base = re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-", "", base)
    base = re.sub(r"-\d+$", "", base)
    return {"file": path.name, "title": title, "product": base, "date": path.stem[:10] if path.stem[:4].isdigit() else ""}


def backlog_blog_published() -> dict:
    """Published posts (from /var/www) plus unpublished outlines (from drafts/blog/processed)."""
    published = _scan_blog_posts()
    published_slugs = {p["url"].rstrip("/").rsplit("/", 1)[-1] for p in published}

    outlines: list[dict] = []
    if BLOG_OUTLINES_DIR.exists():
        for f in sorted(BLOG_OUTLINES_DIR.glob("*.md"), reverse=True):
            meta = _blog_outline_meta(f)
            # If a published slug contains a meaningful chunk of the outline filename, treat as published.
            stem_norm = re.sub(r"^\d{4}-\d{2}-\d{2}-\d{2}-", "", f.stem)
            if any(stem_norm in s or s in stem_norm for s in published_slugs):
                continue
            outlines.append(meta)

    return {"published": published, "outlines": outlines}


# ───────────── Posted log + Performance ─────────────


def _content_posted_records() -> list[dict]:
    if not CONTENT_POSTED_FILE.exists():
        return []
    try:
        data = json.loads(CONTENT_POSTED_FILE.read_text() or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _record_content_action(entry: dict) -> dict:
    records = _content_posted_records()
    records.append(entry)
    CONTENT_POSTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_POSTED_FILE.write_text(json.dumps(records, indent=2))
    return entry


def performance_summary() -> dict:
    """Best post this week, total reach, posted/pending, products with nothing posted."""
    _load_products()
    monday = date.today() - timedelta(days=date.today().weekday())
    monday_iso = monday.isoformat()
    records = _content_posted_records()
    this_week = [r for r in records if (r.get("date") or "") >= monday_iso and r.get("status") == "posted"]

    best = None
    for r in this_week:
        u = r.get("upvotes")
        if isinstance(u, int) and (best is None or (best.get("upvotes") or 0) < u):
            best = r

    total_views = sum((r.get("views") or 0) for r in this_week if isinstance(r.get("views"), int))

    total_drafts = (
        len(backlog_value_posts())
        + len(backlog_problem_posts())
        + len(backlog_blog_posts())
    )
    posted_count = sum(1 for r in this_week)
    pending = max(total_drafts - posted_count, 0)

    # Products that have published nothing this week
    posted_products = {r.get("product") for r in this_week}
    sub_map = _load_subreddit_map()
    cold = []
    for pid, meta in sub_map.items():
        if pid in posted_products:
            continue
        cold.append({"product": pid, "product_name": meta.get("name", pid)})

    return {
        "week_start": monday_iso,
        "best_post": best,
        "total_views": total_views,
        "posted": posted_count,
        "pending": pending,
        "cold_products": cold,
    }


# ───────────── Routes ─────────────

@app.route("/api/signals")
def api_signals():
    sigs, path = load_signals_for(date.today())
    status_map = _action_status_map(date.today().isoformat())
    for s in sigs:
        s["status"] = status_map.get(s["id"], "pending")
    return jsonify({
        "date": date.today().isoformat(),
        "source": path,
        "count": len(sigs),
        "signals": sigs,
    })


@app.route("/api/pipeline")
def api_pipeline():
    return jsonify({"agents": pipeline_status()})


@app.route("/api/pinterest-today")
def api_pinterest_today():
    return jsonify({"pins": pinterest_today()})


@app.route("/api/blog-week")
def api_blog_week():
    return jsonify({"posts": blog_week()})


@app.route("/api/actions")
def api_actions():
    return jsonify(action_tracker())


@app.route("/api/stats")
def api_stats():
    return jsonify(quick_stats())


@app.route("/api/action", methods=["POST"])
def api_action():
    payload = request.get_json(silent=True) or {}
    sid = payload.get("signal_id")
    act = payload.get("action")
    if not sid or act not in ("posted", "skipped", "remind"):
        return jsonify({"ok": False, "error": "invalid signal_id or action"}), 400
    entry = {
        "signal_id": sid,
        "action": act,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "source": "dashboard",
    }
    existing = []
    if ACTIONS_FILE.exists():
        try:
            existing = json.loads(ACTIONS_FILE.read_text() or "[]")
        except json.JSONDecodeError:
            existing = []
    existing.append(entry)
    ACTIONS_FILE.write_text(json.dumps(existing, indent=2))
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/reddit-posts")
def api_reddit_posts():
    """Drafts (pending + processed) + the full action history."""
    drafts = load_reddit_drafts()
    return jsonify({
        "drafts": drafts,
        "history": reddit_history(),
        "counts": {
            "draft":   sum(1 for d in drafts if d.get("status") == "draft"),
            "posted":  sum(1 for d in drafts if d.get("status") == "posted"),
            "skipped": sum(1 for d in drafts if d.get("status") == "skipped"),
        },
    })


@app.route("/api/reddit-action", methods=["POST"])
def api_reddit_action():
    payload = request.get_json(silent=True) or {}
    did = payload.get("draft_id")
    act = payload.get("action")
    if not did or act not in ("posted", "skipped"):
        return jsonify({"ok": False, "error": "invalid draft_id or action"}), 400
    if not load_reddit_draft(did):
        return jsonify({"ok": False, "error": "draft not found"}), 404
    result = mark_reddit_action(did, act, source="dashboard")
    return jsonify({"ok": True, "draft": result})


@app.route("/api/content-backlog")
def api_content_backlog():
    blog = backlog_blog_published()
    return jsonify({
        "value_posts":   backlog_value_posts(),
        "problem_posts": backlog_problem_posts(),
        "blog_posts":    backlog_blog_posts(),
        "pinterest":     backlog_pinterest(),
        "blog_published": blog["published"],
        "blog_outlines":  blog["outlines"],
    })


@app.route("/api/content-action", methods=["POST"])
def api_content_action():
    payload = request.get_json(silent=True) or {}
    file_   = payload.get("file")
    kind    = payload.get("type") or "value_post"
    product = payload.get("product") or ""
    subreddit = payload.get("subreddit") or ""
    title   = payload.get("title") or ""
    status  = payload.get("status")
    if not file_ or status not in ("posted", "skipped", "scheduled"):
        return jsonify({"ok": False, "error": "invalid file or status"}), 400
    entry = {
        "date": date.today().isoformat(),
        "type": kind,
        "product": product,
        "subreddit": subreddit,
        "title": title,
        "file": file_,
        "status": status,
        "views": None,
        "upvotes": None,
        "comments": None,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    _record_content_action(entry)
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/performance")
def api_performance():
    return jsonify(performance_summary())


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "time": datetime.now().isoformat(timespec="seconds")})


# ───────────── Static frontend ─────────────

STATIC = Path(__file__).parent / "static"


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8090, debug=True)
