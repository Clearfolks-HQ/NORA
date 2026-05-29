"""
Shared module for Reddit post drafts (value posts + blog link posts).

Used by:
- pulse.py --value-posts        → writes weekly value post drafts (one/category)
- sofia_blog.py                  → writes a blog link draft per verified post
- telegram_bot.py                → handles ✅ post / ⏭ skip / 📋 copy callbacks
- dashboard/app.py               → serves drafts + history to the web UI

Drafts live as one JSON file per draft in ~/clearfolks/drafts/reddit/pending/.
When the user acts on one via Telegram or the dashboard, the file is moved to
~/clearfolks/drafts/reddit/processed/ with status filled in, and a row is
appended to ~/clearfolks/logs/reddit_posts.json (the history log).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DRAFTS_DIR = Path("/root/clearfolks/drafts/reddit")
PENDING_DIR = DRAFTS_DIR / "pending"
PROCESSED_DIR = DRAFTS_DIR / "processed"
HISTORY_LOG = Path("/root/clearfolks/logs/reddit_posts.json")

# Category → list of suggested subreddits. Sourced from the user's spec.
# Keys here are the canonical category slug used everywhere (filename, draft.id).
CATEGORY_SUBREDDITS: dict[str, list[str]] = {
    "caregiver":     ["r/caregivers", "r/aging", "r/dementia"],
    "medication":    ["r/caregivers", "r/chronicillness"],
    "iep":           ["r/specialeducation", "r/autism", "r/parentsofkidswithspecialneeds"],
    "wedding":       ["r/weddingplanning"],   # daily-discussion-only — strict
    "baby":          ["r/beyondthebump"],     # daily-discussion-only — strict
    "homeschool":    ["r/homeschool", "r/unschooling"],
    "pet-care":      ["r/dogs", "r/cats", "r/petadvice"],
    "meal-planning": ["r/mealprepsunday", "r/budgetfood", "r/eatcheapandhealthy"],
    "moving":        ["r/moving", "r/firsttimehomebuyer"],
    "travel":        ["r/solotravel", "r/travel", "r/digitalnomad"],
    "etsy-seller":   ["r/etsy", "r/etsysellers"],
    "iep-meeting":   ["r/specialeducation"],
}

# Friendly topic labels for the value post prompt — what the post is "about".
CATEGORY_TOPICS: dict[str, str] = {
    "caregiver":     "caregiving for an aging parent",
    "medication":    "managing medications for a family member with chronic illness",
    "iep":           "IEP meetings and parent rights in special education",
    "wedding":       "planning a wedding",
    "baby":          "the postpartum / newborn months",
    "homeschool":    "homeschooling more than one kid",
    "pet-care":      "managing pet health and vet records",
    "meal-planning": "meal planning and grocery shopping on a budget",
    "moving":        "moving house with a family",
    "travel":        "planning longer trips and travel logistics",
    "etsy-seller":   "running a small Etsy shop",
    "iep-meeting":   "preparing for and surviving an IEP meeting",
}

# Subreddits that allow article/blog links in self-posts (Type 2 blog link posts).
PERMISSIVE_SUBREDDITS: set[str] = {
    "r/homeschool",
    "r/petadvice",
    "r/moving",
    "r/budgetfood",
    "r/eatcheapandhealthy",
    "r/etsysellers",
}

# Sofia blog cluster → which permissive subs to target for a blog link post.
# A cluster may have zero permissive subs; in that case no blog draft is created.
CLUSTER_PERMISSIVE: dict[str, list[str]] = {
    "homeschool":    ["r/homeschool"],
    "pet-care":      ["r/petadvice"],
    "moving":        ["r/moving"],
    "meal-planning": ["r/budgetfood", "r/eatcheapandhealthy"],
    "etsy-seller":   ["r/etsysellers"],
}


def _ensure_dirs() -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def draft_path(draft_id: str) -> Path | None:
    """Find a draft file by id in either pending/ or processed/."""
    for d in (PENDING_DIR, PROCESSED_DIR):
        p = d / f"{draft_id}.json"
        if p.exists():
            return p
    return None


def load_draft(draft_id: str) -> dict | None:
    p = draft_path(draft_id)
    if not p:
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_draft(draft: dict) -> Path:
    _ensure_dirs()
    p = PENDING_DIR / f"{draft['id']}.json"
    p.write_text(json.dumps(draft, indent=2))
    return p


def all_drafts(status: str | None = None) -> list[dict]:
    """Return every draft on disk (pending + processed), newest first."""
    _ensure_dirs()
    out: list[dict] = []
    for d in (PENDING_DIR, PROCESSED_DIR):
        for f in d.glob("*.json"):
            try:
                rec = json.loads(f.read_text())
                rec["_loc"] = d.name
                out.append(rec)
            except (OSError, json.JSONDecodeError):
                continue
    if status:
        out = [r for r in out if r.get("status") == status]
    out.sort(key=lambda r: r.get("created", ""), reverse=True)
    return out


def mark_action(draft_id: str, action: str, source: str = "telegram") -> dict | None:
    """Record an action on a draft. action ∈ {posted, skipped, copied, reminded}.

    For posted/skipped, the draft is moved to processed/ and its status updated.
    For copied, no move (the user just wanted the text — still pending).
    The action is appended to the history log either way.
    """
    if action not in {"posted", "skipped", "copied", "reminded"}:
        return None

    draft = load_draft(draft_id)
    if not draft:
        return None

    now = datetime.now().isoformat(timespec="seconds")
    draft.setdefault("history", []).append({"action": action, "ts": now, "source": source})

    if action in {"posted", "skipped"}:
        draft["status"] = action
        draft["acted_at"] = now
        # Move pending → processed
        src = PENDING_DIR / f"{draft_id}.json"
        dst = PROCESSED_DIR / f"{draft_id}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(draft, indent=2))
        if src.exists() and src.resolve() != dst.resolve():
            src.unlink(missing_ok=True)
    else:
        # No move — just rewrite in-place
        p = draft_path(draft_id)
        if p:
            p.write_text(json.dumps(draft, indent=2))

    _append_history({
        "draft_id": draft_id,
        "type": draft.get("type"),
        "category": draft.get("category"),
        "title": draft.get("title"),
        "subreddits": draft.get("subreddits"),
        "action": action,
        "source": source,
        "ts": now,
    })
    return draft


def _append_history(entry: dict) -> None:
    HISTORY_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(HISTORY_LOG.read_text())
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    data.append(entry)
    HISTORY_LOG.write_text(json.dumps(data, indent=2))


def history() -> list[dict]:
    try:
        d = json.loads(HISTORY_LOG.read_text())
        return d if isinstance(d, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", text.lower())
    return re.sub(r"-+", "-", s).strip("-")[:60]


# ── Draft constructors ───────────────────────────────────────────────────────

def make_value_draft(category: str, title: str, body: str,
                     created: str | None = None) -> dict:
    created = created or datetime.now().isoformat(timespec="seconds")
    return {
        "id": f"value-{category}-{created[:10]}",
        "type": "value",
        "category": category,
        "title": title.strip(),
        "body": body.strip(),
        "subreddits": list(CATEGORY_SUBREDDITS.get(category, [])),
        "created": created,
        "status": "draft",
    }


def make_blog_link_draft(cluster: str, blog_title: str, blog_url: str,
                         intro: str, created: str | None = None) -> dict:
    created = created or datetime.now().isoformat(timespec="seconds")
    slug = slugify(blog_title) or "post"
    return {
        "id": f"blog-{cluster}-{slug}-{created[:10]}",
        "type": "blog_link",
        "category": cluster,
        "title": blog_title.strip().lower(),
        "intro": intro.strip(),
        "blog_url": blog_url,
        "body": f"{intro.strip()}\n\n{blog_url}",
        "subreddits": list(CLUSTER_PERMISSIVE.get(cluster, [])),
        "created": created,
        "status": "draft",
    }
