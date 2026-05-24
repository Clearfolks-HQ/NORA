#!/usr/bin/env python3
"""
backfill_pins.py — one-shot: create Pinterest pin drafts for every published
blog post that doesn't already have a pin draft.

Walks /var/www/clearfolks-blog/site/content/<cluster>/*.md, reads the YAML
frontmatter (title, description, product), and writes a pinterest pin draft
to ~/clearfolks/drafts/pinterest/ in the exact format pinterest_poster.py
expects.

Programmatic only — no Claude calls. Uses cluster-specific hashtag/CTA
templates plus the post's own title and description (both already SEO-tuned
by sofia_blog).

Idempotent: skips posts that already have a pin draft (matched by slug).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path


BLOG_CONTENT = Path("/var/www/clearfolks-blog/site/content")
PINS_DIR     = Path("/root/clearfolks/drafts/pinterest")
PINS_PROCESSED = PINS_DIR / "processed"


# Cluster -> 10-tag set. Lowercased, no spaces inside tags.
HASHTAGS = {
    "wedding":       "#weddingplanning #weddingvenue #engaged #weddingorganization #bridetobe #weddingchecklist #weddingbudget #weddingvendors #weddingideas #weddinginspiration",
    "baby":          "#babytracker #newparent #postpartum #newborn #babysleep #newbornlife #motherhood #babyroutine #parenthood #babylife",
    "caregiver":     "#caregiver #caregiving #eldercare #aginginplace #familycaregiver #seniorcare #caregiverlife #caregiversupport #dementiacare #elderlycare",
    "medication":    "#medicationtracker #medicationmanagement #pillorganizer #healthcare #medreminders #seniorlife #chronicillness #healthtips #medicaltracking #medicinemanagement",
    "iep":           "#iep #specialneeds #specialeducation #specialneedsparenting #iepmeeting #autismparent #adhdmom #parentadvocate #neurodivergent #iephelp",
    "etsy-seller":   "#etsyshop #etsyseller #etsybusiness #handmadebusiness #smallbusiness #etsysuccess #etsysellertips #shopowner #ecommerce #onlinebusiness",
    "homeschool":    "#homeschool #homeschoolmom #homeschooling #homeschoolfamily #homeschoolplanner #homeschoollife #homeschoolingmom #homeschooler #unschooling #homeschoolblog",
    "pet-care":      "#petcare #petparents #petowners #petorganization #dogmom #catmom #petlife #petowner #vetvisit #pethealth",
    "meal-planning": "#mealplan #mealplanning #grocerylist #mealprep #weeklymealplan #familymeals #budgetmeals #mealideas #grocerybudget #mealplanner",
    "moving":        "#moving #movingtips #movingday #movinghacks #relocation #newhome #movingchecklist #organizing #packingtips #homeorganization",
    "travel":        "#travelplanning #travel #familytravel #traveltips #travelplanner #tripplanning #vacationideas #traveljournal #travelbudget #travelinspiration",
    "generic":       "#organize #organizinglife #homeorganization #productivity #lifehacks #planner #adulting #household #lifehack #routines",
}

CTA = {
    "wedding":       "Get organized before the next vendor meeting",
    "baby":          "Start tracking tonight",
    "caregiver":     "Get the system that keeps everything in one place",
    "medication":    "Stop missing doses today",
    "iep":           "Walk into the next IEP meeting prepared",
    "etsy-seller":   "See your real profit numbers",
    "homeschool":    "Plan tomorrow tonight",
    "pet-care":      "Get your pet's records sorted",
    "meal-planning": "Plan the week in 10 minutes",
    "moving":        "Get the moving system that actually works",
    "travel":        "Plan the trip in one place",
    "generic":       "Get organized today",
}

BOARD_NAME = {
    "wedding":       "Wedding Planning & Organization",
    "baby":          "New Baby & Postpartum",
    "caregiver":     "Caregiver Support & Organization",
    "medication":    "Medication Management Tips",
    "iep":           "Special Education & IEP Resources",
    "etsy-seller":   "Etsy Seller Tips & Tools",
    "homeschool":    "Homeschool Planning & Organization",
    "pet-care":      "Pet Care & Organization",
    "meal-planning": "Meal Planning & Grocery Tips",
    "moving":        "Moving Day & Home Organization",
    "travel":        "Travel Planning & Organization",
    "generic":       "Household Organization",
}


FRONTMATTER_RX = re.compile(r"^---\n(.*?)\n---\n", re.S)


def parse_frontmatter(raw: str) -> dict:
    """Minimal YAML-ish parser tailored to sofia_blog's frontmatter shape."""
    m = FRONTMATTER_RX.match(raw)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        m2 = re.match(r'^([a-z_]+):\s*"?([^"\n]*?)"?\s*$', line)
        if m2:
            out[m2.group(1)] = m2.group(2).strip()
    return out


def existing_pin_slugs() -> set:
    """Slugs of pins that already have an active OR processed draft.
    Slug here is whatever pinterest_poster.slugify() would produce from the
    TITLE: line of the draft, which mirrors the blog post title."""
    slugs = set()
    for d in (PINS_DIR, PINS_PROCESSED):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            m = re.search(r"^TITLE:\s*(.+)$", txt, re.M)
            if m:
                slugs.add(_slugify(m.group(1)))
    return slugs


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def build_draft(post: dict) -> str:
    cluster = post["cluster"]
    title = post["title"]
    desc  = post["description"]
    product = post.get("product", "")
    source  = post.get("source_reddit", "")
    pain    = desc  # description doubles as a one-line pain summary

    # Shorten title to Pinterest sweet-spot (6-10 words, <=80 chars)
    pin_title = title
    if len(pin_title) > 80:
        pin_title = pin_title[:77].rsplit(" ", 1)[0] + "..."

    # Two-sentence description sourced from the blog meta. If meta is already
    # punchy enough we leave it alone; otherwise pad with a brief framing line.
    pin_desc = desc.strip()
    if not pin_desc.endswith("."):
        pin_desc += "."

    today = date.today().isoformat()
    return (
        f"# Pinterest Pin Draft — Backfill\n\n"
        f"**Source:** {source} | backfill\n\n"
        f"**Pain point:** {pain}\n\n"
        f"---\n\n"
        f"TITLE: {pin_title}\n\n"
        f"DESCRIPTION: {pin_desc}\n\n"
        f"CTA: {CTA.get(cluster, CTA['generic'])}\n\n"
        f"HASHTAGS: {HASHTAGS.get(cluster, HASHTAGS['generic'])}\n\n"
        f"BOARD: {BOARD_NAME.get(cluster, BOARD_NAME['generic'])}\n\n"
        f"---\n"
        f"*Generated: {today} | Product: {product}*\n"
    )


def main() -> int:
    PINS_DIR.mkdir(parents=True, exist_ok=True)
    skipped = existing_pin_slugs()
    print(f"Skipping {len(skipped)} slugs already attempted as pins.")

    created = 0
    skipped_existing = 0
    skipped_unparsed = 0

    for cluster_dir in sorted(BLOG_CONTENT.iterdir()):
        if not cluster_dir.is_dir():
            continue
        cluster = cluster_dir.name
        if cluster not in BOARD_NAME:
            continue
        for post_path in sorted(cluster_dir.glob("*.md")):
            if post_path.name == "_index.md":
                continue
            raw = post_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(raw)
            if not fm.get("title") or not fm.get("description"):
                skipped_unparsed += 1
                continue

            title = fm["title"]
            slug = _slugify(title)
            if slug in skipped:
                skipped_existing += 1
                continue

            post = {
                "cluster": cluster,
                "title": title,
                "description": fm["description"],
                "product": fm.get("product", ""),
                "source_reddit": fm.get("source_reddit", ""),
            }
            out_path = PINS_DIR / f"backfill-{cluster}-{slug[:50]}.md"
            out_path.write_text(build_draft(post), encoding="utf-8")
            created += 1

    print(f"Created {created} new pin drafts.")
    print(f"Skipped {skipped_existing} already-attempted titles.")
    if skipped_unparsed:
        print(f"Skipped {skipped_unparsed} posts missing title/description in frontmatter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
