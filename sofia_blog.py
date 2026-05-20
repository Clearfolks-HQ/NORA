#!/usr/bin/env python3
"""
sofia_blog.py — Sofia's second job: blog post writer.

Reads Echo's daily outline files from ~/clearfolks/drafts/blog/
Expands each outline into a full 1,400-1,800 word post with:
  - Hugo frontmatter (title, description, date, clusters, product, faqs, toc)
  - 6 expanded body sections (~220 words each)
  - 3-4 FAQ items (drawn from Echo's section titles)
  - Brand voice: warm, practical, no hype
  - Forbidden: revolutionary, seamless, intuitive, game-changing, simply,
    just, PWA, Progressive Web App
  - Required where natural: offline capability, one payment lifetime access,
    household sharing

Writes the completed .md file to the Hugo content directory.
Calls rebuild-blog.sh after writing.
Marks processed outlines by moving to drafts/blog/processed/
Sends Telegram summary.

Schedule: daily at 9:00am (after Echo runs at 7:30am)
Cron: 0 9 * * * /root/clearfolks/venv/bin/python /root/clearfolks/sofia_blog.py >> /root/clearfolks/logs/sofia_blog.log 2>&1
"""

import os, re, json, shutil, subprocess, sys, glob
from datetime import datetime, date
from pathlib import Path
import anthropic

# ── Config ──────────────────────────────────────────────────────────────
BASE          = Path("/root/clearfolks")
DRAFTS_IN     = BASE / "drafts" / "blog"
DRAFTS_DONE   = BASE / "drafts" / "blog" / "processed"
HUGO_CONTENT  = Path("/var/www/clearfolks-blog/site/content")
REBUILD_SCRIPT= Path("/var/www/clearfolks-blog/site/../..") / "scripts" / "rebuild-blog.sh"
# Actual rebuild script location after install:
REBUILD_SCRIPT= Path("/root/clearfolks-blog-pass1/scripts/rebuild-blog.sh")  # fixed below
LOG_FILE      = BASE / "logs" / "sofia_blog.log"

# Cluster slug mapping — matches Echo's "Product:" tag to Hugo cluster slug
PRODUCT_TO_CLUSTER = {
    "Caregiver Command Center":       "caregiver",
    "Medication Tracker":             "medication",
    "IEP Parent Binder":              "iep",
    "IEP Meeting Prep Kit":           "iep",
    "Etsy Seller Business System":    "etsy-seller",
    "Wedding Planning App":           "wedding",
    "Baby Tracker and Postpartum App":"baby",
    "Baby Tracker & Postpartum App":  "baby",
    "Homeschool Planner App":         "homeschool",
    "Pet Care Organizer":             "pet-care",
    "Meal Planner and Grocery":       "meal-planning",
    "Meal Planner & Grocery":         "meal-planning",
    "Moving Day Organizer":           "moving",
    "Travel Planner":                 "travel",
}

FORBIDDEN = [
    "revolutionary", "seamless", "intuitive", "game-changing",
    "simply", "game changer", "PWA", "Progressive Web App",
]

BRAND_CLOSE = "Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com"

# ── Anthropic client ─────────────────────────────────────────────────────
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def parse_outline(text: str) -> dict:
    """Extract structured fields from Echo's outline format."""
    result = {
        "headline": "",
        "meta": "",
        "sections": [],
        "product_mention": "",
        "takeaway": "",
        "product": "",
        "source_reddit": "",
        "pain_point": "",
    }

    lines = text.splitlines()
    current_section = None
    section_text = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("HEADLINE:"):
            result["headline"] = stripped[len("HEADLINE:"):].strip()
        elif stripped.startswith("META:"):
            result["meta"] = stripped[len("META:"):].strip()
        elif stripped.startswith("PRODUCT MENTION:"):
            result["product_mention"] = stripped[len("PRODUCT MENTION:"):].strip()
        elif stripped.startswith("TAKEAWAY:"):
            result["takeaway"] = stripped[len("TAKEAWAY:"):].strip()
        elif stripped.startswith("*Generated:") and "Product:" in stripped:
            m = re.search(r"Product:\s*(.+?)(?:\*|$)", stripped)
            if m:
                result["product"] = m.group(1).strip().rstrip("*").strip()
        elif stripped.startswith("**Source:**"):
            m = re.search(r"\*\*Source:\*\*\s*(r/\S+)", stripped)
            if m:
                result["source_reddit"] = m.group(1)
        elif stripped.startswith("**Pain point:**"):
            result["pain_point"] = stripped[len("**Pain point:**"):].strip()
        elif re.match(r"^\d+\.\s", stripped):
            if current_section is not None:
                result["sections"].append({
                    "title": current_section,
                    "brief": " ".join(section_text).strip(),
                })
            parts = stripped.split("—", 1)
            if len(parts) == 2:
                current_section = parts[0].split(".", 1)[1].strip()
                section_text = [parts[1].strip()]
            else:
                current_section = stripped.split(".", 1)[1].strip()
                section_text = []
        elif current_section and stripped:
            section_text.append(stripped)

    if current_section is not None:
        result["sections"].append({
            "title": current_section,
            "brief": " ".join(section_text).strip(),
        })

    return result


def title_to_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def generate_post(outline: dict) -> str:
    """Call Claude to expand the outline into a full blog post."""

    sections_text = "\n".join(
        f"{i+1}. {s['title']}\n   Brief: {s['brief']}"
        for i, s in enumerate(outline["sections"])
    )

    product = outline.get("product", "")
    cluster = PRODUCT_TO_CLUSTER.get(product, "generic")

    system_prompt = f"""You are Sofia, the content writer for Clearfolks. Your voice is warm, practical, and direct. You write for real people in difficult, complicated moments of life — not for content mills.

BRAND VOICE RULES (non-negotiable):
- Warm but not saccharine. Practical but not cold.
- Never use these words: {", ".join(FORBIDDEN)}
- Where it fits naturally, mention: offline capability, one payment lifetime access, household sharing. Never force them.
- No exclamation marks in body copy.
- Short paragraphs. Real sentences. No bullet walls.
- Write for humans first. SEO structure second.

OUTPUT FORMAT — return a valid Hugo markdown file with this exact structure:

---
title: "[post title]"
description: "[150-160 char meta description for Google]"
date: {date.today().isoformat()}
clusters: ["{cluster}"]
product: "{product}"
toc: true
source_reddit: "{outline.get('source_reddit', '')}"
faqs:
  - q: "[question]"
    a: "[concise answer, 2-3 sentences]"
  - q: "[question]"
    a: "[concise answer, 2-3 sentences]"
  - q: "[question]"
    a: "[concise answer, 2-3 sentences]"
og_image: ""
---

[Opening paragraph — 60-80 words. Name the real situation the reader is in. No preamble, no "In this article we will". Start with their reality.]

## [Section 1 title]

[~220 words expanding the section brief. Concrete, specific, useful.]

## [Section 2 title]

[~220 words]

## [Section 3 title]

[~220 words]

## [Section 4 title]

[~220 words — this is where you mention the NORA product naturally as a tool that helps with this specific section's problem. One sentence, not a pitch.]

## [Section 5 title]

[~220 words]

## [Section 6 title / closing action]

[~150 words — end with the TAKEAWAY restated as a concrete first step. No "in conclusion".]"""

    user_prompt = f"""Expand this Echo outline into a full blog post.

HEADLINE: {outline['headline']}
META: {outline['meta']}
SOURCE: {outline.get('source_reddit', 'Reddit')}
PAIN POINT: {outline.get('pain_point', '')}

SECTIONS:
{sections_text}

PRODUCT MENTION GUIDANCE: {outline['product_mention']}
TAKEAWAY: {outline['takeaway']}
PRODUCT: {product}

Write the full Hugo markdown post now. Follow the output format exactly. Total word count: 1,400-1,800 words."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=3000,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=system_prompt,
    )

    return message.content[0].text


def check_forbidden_words(content: str) -> list:
    found = []
    content_lower = content.lower()
    for word in FORBIDDEN:
        if word.lower() in content_lower:
            found.append(word)
    return found


def write_post(content: str, cluster: str, slug: str) -> Path:
    """Write the post to the Hugo content directory."""
    dest_dir = HUGO_CONTENT / cluster
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{slug}.md"

    # Don't overwrite if already exists
    if dest_file.exists():
        ts = datetime.now().strftime("%H%M%S")
        dest_file = dest_dir / f"{slug}-{ts}.md"

    dest_file.write_text(content, encoding="utf-8")
    return dest_file


def rebuild_blog():
    """Run the Hugo rebuild script."""
    rebuild = Path("/root/clearfolks-blog-pass1/scripts/rebuild-blog.sh")
    if rebuild.exists():
        result = subprocess.run(["bash", str(rebuild)], capture_output=True, text=True)
        if result.returncode != 0:
            log(f"Rebuild error: {result.stderr}")
        else:
            log("Blog rebuilt successfully.")
    else:
        log(f"Rebuild script not found at {rebuild} — skipping rebuild.")


def send_telegram(message: str):
    """Send a summary to @Cf_pwa_bot."""
    import urllib.request, urllib.parse
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("Telegram credentials not set — skipping notification.")
        return
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"Telegram send failed: {e}")


def process_outlines():
    """Main loop — find unprocessed outlines and expand each one."""
    DRAFTS_DONE.mkdir(parents=True, exist_ok=True)

    outlines = sorted(DRAFTS_IN.glob("*.md"))
    if not outlines:
        log("No outline files found in drafts/blog/ — nothing to do.")
        return

    log(f"Found {len(outlines)} outline(s) to process.")

    published = []
    errors = []

    for outline_path in outlines:
        log(f"Processing: {outline_path.name}")
        try:
            raw = outline_path.read_text(encoding="utf-8")
            outline = parse_outline(raw)

            if not outline["headline"]:
                log(f"  Skipping {outline_path.name} — no headline found.")
                continue

            product = outline.get("product", "")
            cluster = PRODUCT_TO_CLUSTER.get(product, "generic")
            slug = title_to_slug(outline["headline"])

            log(f"  Headline : {outline['headline']}")
            log(f"  Cluster  : {cluster}")
            log(f"  Product  : {product}")

            # Generate the full post
            content = generate_post(outline)

            # Check for forbidden words
            bad_words = check_forbidden_words(content)
            if bad_words:
                log(f"  WARNING: Forbidden words found: {bad_words}")
                # Clean them automatically where possible
                for word in bad_words:
                    replacements = {
                        "revolutionary": "meaningful",
                        "seamless": "straightforward",
                        "intuitive": "clear",
                        "game-changing": "useful",
                        "simply": "",
                        "game changer": "real help",
                        "PWA": "app",
                        "Progressive Web App": "app",
                    }
                    if word in replacements:
                        content = re.sub(
                            re.escape(word),
                            replacements[word],
                            content,
                            flags=re.IGNORECASE,
                        )
                log(f"  Auto-replaced forbidden words.")

            # Write to Hugo content dir
            dest = write_post(content, cluster, slug)
            log(f"  Written : {dest}")

            # Move outline to processed
            shutil.move(str(outline_path), str(DRAFTS_DONE / outline_path.name))
            log(f"  Outline moved to processed/")

            published.append({
                "title": outline["headline"],
                "cluster": cluster,
                "slug": slug,
            })

        except Exception as e:
            log(f"  ERROR processing {outline_path.name}: {e}")
            errors.append(str(outline_path.name))
            continue

    # Rebuild once after all posts are written
    if published:
        log("Triggering Hugo rebuild...")
        rebuild_blog()

    # Telegram summary
    if published or errors:
        lines = [f"📝 <b>Sofia Blog Report — {date.today().strftime('%b %d')}</b>\n"]
        if published:
            lines.append(f"✅ Published {len(published)} post(s):")
            for p in published:
                lines.append(f"  • [{p['cluster']}] {p['title']}")
        if errors:
            lines.append(f"\n⚠️ {len(errors)} error(s):")
            for e in errors:
                lines.append(f"  • {e}")
        lines.append(f"\nclearfolks.com/blog")
        send_telegram("\n".join(lines))


if __name__ == "__main__":
    log("=" * 60)
    log("Sofia Blog Writer starting")
    log("=" * 60)
    process_outlines()
    log("Sofia Blog Writer complete.")
