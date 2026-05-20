#!/usr/bin/env python3
"""Batch asset renderer + listing bundler for Clearfolks.

Calls deliver.py / mockup.py / video.py for each product and assembles a
per-slug bundle at /root/clearfolks/listings/<slug>/.

- Minimal bundle (`full_bundle=False`): just images/ + both videos.
- Full bundle:                          + delivery.pdf + README.md packet.

README packet pulls description/tags from Sofia drafts when present, falling
back to a generic template. Does not invoke forge — forge must be run
separately for products not yet in products.json.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path("/root/clearfolks")
DELIVER = HOME / "deliver.py"
MOCKUP = HOME / "mockup.py"
VIDEO = HOME / "video.py"


def _run(*args, env=None):
    print(f"    $ python3 {' '.join(str(a) for a in args)}")
    result = subprocess.run(["python3"] + [str(a) for a in args], env=env)
    if result.returncode != 0:
        raise SystemExit(f"FAILED: {args}")


def render_assets(slug, name, tagline, app_url, etsy_url):
    _run(MOCKUP, name, tagline, slug)
    _run(VIDEO, name, tagline, etsy_url, slug)
    env = os.environ.copy()
    env["CLEARFOLKS_SCENE_SECONDS"] = "2"
    _run(VIDEO, name, tagline, etsy_url, f"{slug}-etsy", env=env)


def render_pdf(slug, name, tagline, app_url):
    _run(DELIVER, name, tagline, app_url, slug)


def stage_bundle(slug, *, include_pdf):
    bundle = HOME / "listings" / slug
    images = bundle / "images"
    images.mkdir(parents=True, exist_ok=True)

    for i in range(1, 6):
        shutil.copy2(HOME / "mockups" / slug / f"image-{i}.png", images / f"image-{i}.png")

    shutil.copy2(HOME / "videos" / f"{slug}-listing.mp4",      bundle / "video-long.mp4")
    shutil.copy2(HOME / "videos" / f"{slug}-etsy-listing.mp4", bundle / "video-etsy-short.mp4")

    if include_pdf:
        shutil.copy2(HOME / "delivery" / f"{slug}-delivery.pdf", bundle / "delivery.pdf")

    return bundle


# ---------------------------------------------------------------------------
# Sofia draft parser (best-effort — extracts TITLE / DESCRIPTION / BULLETS
# / TAGS / SECTION blocks from the markdown format Sofia emits).
# ---------------------------------------------------------------------------
def parse_sofia_draft(slug):
    path = HOME / "drafts" / "listings" / f"{slug}-listing.md"
    if not path.exists():
        return {}
    text = path.read_text()
    out = {}
    patterns = {
        "title":       r"TITLE:\s*(.+?)\n",
        "price":       r"PRICE SUGGESTION:\s*(.+?)\n",
        "section":     r"SECTION:\s*(.+?)\n",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            out[key] = m.group(1).strip()

    m = re.search(r"DESCRIPTION:\s*\n?(.*?)\nBULLET POINTS", text, re.DOTALL)
    if m:
        out["description"] = m.group(1).strip()

    m = re.search(r"BULLET POINTS:?\**\s*\n?(.*?)\n\s*\**TAGS", text, re.DOTALL)
    if m:
        bullets = [ln.strip(" -*") for ln in m.group(1).splitlines() if ln.strip().startswith("-")]
        out["bullets"] = bullets

    m = re.search(r"TAGS:?\**\s*\n?(.*?)(\n\s*\**SECTION|\n---)", text, re.DOTALL)
    if m:
        tag_str = m.group(1).replace("\n", " ").strip()
        tags = [t.strip() for t in tag_str.split(",") if t.strip()]
        out["tags"] = tags[:13]

    return out


GENERIC_BULLETS = [
    "Stop juggling multiple apps and notebooks — everything in one place",
    "Works offline after first load — your data stays on your device",
    "Share with partners or household members, no account required",
    "One payment, lifetime access — no subscriptions, no ads",
    "Installs like a native app on iPhone, Android, iPad, or desktop",
]
GENERIC_TAGS = [
    "digital planner app", "offline planner", "household organizer",
    "household tracker", "productivity app", "mobile planner",
    "digital tool download", "shared family app", "no subscription app",
    "pwa install", "lifetime access", "planner app gift", "home management",
]


def _enforce_tag_limit(tags, max_chars=20, max_count=13):
    """Etsy caps tags at 20 chars each, 13 max. Drop too-long ones rather than
    silently truncating (truncation creates word-fragments that hurt SEO)."""
    out = []
    for t in tags:
        t = t.strip()
        if 0 < len(t) <= max_chars and t not in out:
            out.append(t)
        if len(out) >= max_count:
            break
    return out


def _enforce_section_limit(section, max_chars=24):
    """Etsy shop sections cap at 24 chars."""
    section = section.strip()
    if len(section) <= max_chars:
        return section
    # If a shorter natural form fits, prefer it. Otherwise hard-truncate at a
    # word boundary so we don't leave a partial word.
    words = section.split()
    rolled = ""
    for w in words:
        candidate = (rolled + " " + w).strip()
        if len(candidate) > max_chars:
            break
        rolled = candidate
    return rolled or section[:max_chars]


def build_readme(slug, name, tagline, app_url, etsy_url):
    draft = parse_sofia_draft(slug)
    title       = draft.get("title",       f"{name} | Digital Planner & Tracker | Lifetime Access")
    price       = draft.get("price",       "$29")
    description = draft.get("description", f"{tagline}\n\nA digital app built for the moments when you need clarity, not chaos. Track, plan, and share — offline capable, lifetime access, no subscriptions.")
    bullets     = draft.get("bullets",     GENERIC_BULLETS)
    raw_tags    = draft.get("tags",        GENERIC_TAGS)
    raw_section = draft.get("section",     "Digital Planners")

    tags = _enforce_tag_limit(raw_tags)
    dropped = [t for t in raw_tags if t.strip() not in tags and t.strip()]
    section = _enforce_section_limit(raw_section)

    bullets_block = "\n".join(f"• {b}" for b in bullets)
    tags_block = "\n".join(tags)
    dropped_block = ""
    if dropped:
        dropped_block = "\n\n*Dropped (>20 chars): " + ", ".join(dropped) + "*"

    return f"""# Etsy Listing Packet — {name}

Copy/paste this into Etsy's "Add a listing" UI. Fields are in Etsy's order.

---

## Product identity
- Slug:           **{slug}**
- Live app URL:   **{app_url}**  *(post-purchase — goes in the delivery PDF)*
- Tagline:        **{tagline}**

---

## 1. Photos  (order matters — photo 1 is the thumbnail)

Upload from `images/`:

| # | File         |
|---|--------------|
| 1 | image-1.png  |
| 2 | image-2.png  |
| 3 | image-3.png  |
| 4 | image-4.png  |
| 5 | image-5.png  |

2000×2000 PNGs, Etsy-ready.

## 2. Video

Upload **`video-etsy-short.mp4`** (14s, under Etsy's 15s cap).
Keep `video-long.mp4` (35s) for Pinterest / social / your site.

## 3. Title  (paste exactly)

```
{title}
```

## 4. About

- Who made it:        I did
- What is it:         A finished product
- When made:          2025–present
- **Digital**  (required — unlocks auto-delivery)

## 5. Category

`Paper & Party Supplies > Paper > Stationery > Planners & Organizers`  (or whichever bucket matches your existing listings)

## 6. Price / Quantity / Type

- Type:      Digital
- Price:     **{price}**
- Quantity:  999

## 7. Description  (paste — Etsy preserves newlines, strips markdown)

```
{description}

WHY IT WORKS
{bullets_block}

HOW IT WORKS
1. After purchase, you receive a one-page PDF with a link and QR code
2. Open the link on your phone or scan the QR — the app loads in your browser
3. Tap Share → Add to Home Screen — installs like a native app
4. Use it anywhere. Data stays on your device.

SUPPORT
Questions or issues? Message us on Etsy — we reply within 24 hours.

Made by Clearfolks — Practical tools for life's complicated moments — clearfolks.com
```

## 8. Tags  (13 max, ≤20 chars each — already validated)

```
{tags_block}
```
{dropped_block}

## 9. Section  (≤24 chars — already validated)

**{section}**

## 10. Digital file  (buyers download on purchase)

Upload **`delivery.pdf`** — 1-page branded 1-pager with QR → live app + 3-step install.

---

## After publishing

1. Copy the Etsy listing URL.
2. ssh root@159.65.47.63; nano /root/clearfolks/products.json — set `etsy_listing: "live"` + `etsy_url` for this product.
3. Regenerate the short video with the real listing URL so the QR lands buyers on the listing page instead of the shop:
   ```
   CLEARFOLKS_SCENE_SECONDS=2 python3 /root/clearfolks/video.py \\
       "{name}" "{tagline}" "<pasted listing URL>" "{slug}-etsy"
   ```

Pre-flight: 5 photos in order ✓ · short video uploaded ✓ · Type = Digital ✓ · delivery.pdf attached ✓ · tags 13 ✓
"""


def render_product(slug, name, tagline, app_url, etsy_url, full_bundle, *, readme_only=False):
    t0 = time.time()
    print(f"\n========== {slug}: {name}{' [readme-only]' if readme_only else ''} ==========")
    if not readme_only:
        render_assets(slug, name, tagline, app_url, etsy_url)
        if full_bundle:
            render_pdf(slug, name, tagline, app_url)
        bundle = stage_bundle(slug, include_pdf=full_bundle)
    else:
        bundle = HOME / "listings" / slug
        bundle.mkdir(parents=True, exist_ok=True)
    if full_bundle:
        (bundle / "README.md").write_text(build_readme(slug, name, tagline, app_url, etsy_url))
    elapsed = time.time() - t0
    print(f"  -> bundle at {bundle}  ({elapsed:.0f}s)")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
EXISTING = [
    # slug,           name,                            tagline,                                   app_url,                                        etsy_url,                                                                                full_bundle
    ("caregiver",     "Caregiver Command Center",     "Organized. Informed. Present.",          "https://app.clearfolks.com/caregiver",        "https://www.etsy.com/listing/4490826785/caregiver-organizer-app-medication",            False),
    ("cf-bqs4r8e9",   "Medication Tracker",            "Doses. Refills. Never missed.",          "https://app.clearfolks.com/cf-bqs4r8e9",      "https://www.etsy.com/listing/4490844238/medication-tracker-app-track-doses",            False),
    ("cf-9x25jxsc",   "IEP Parent Binder",             "Organised. Documented. Ready to advocate.", "https://app.clearfolks.com/cf-9x25jxsc", "https://www.etsy.com/listing/4490835131/iep-parent-binder-app-track-goals",             False),
    ("cf-qatxssg7",   "IEP Meeting Prep Kit",          "Questions ready. Rights known. Confident.", "https://app.clearfolks.com/cf-qatxssg7", "https://www.etsy.com/listing/4490828563/iep-meeting-prep-kit-28-questions-parent",     False),
    ("cf-63nja3ht",   "Etsy Seller Business System",   "Sales. Fees. Profit — clear.",           "https://app.clearfolks.com/cf-63nja3ht",      "https://www.etsy.com/listing/4490841158/etsy-profit-tracker-app-sales-fees",            False),
    ("cf-2465sd9i",   "Wedding Planning App",          "Planned. Booked. Unforgettable.",        "https://app.clearfolks.com/cf-2465sd9i",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-q1d4697v",   "Baby Tracker & Postpartum App", "Tracked. Rested. Ready for what's next.","https://app.clearfolks.com/cf-q1d4697v",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-ta6u0cjs",   "Homeschool Planner App",        "Scheduled. Taught. Thriving.",           "https://app.clearfolks.com/cf-ta6u0cjs",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-eog81o2l",   "Pet Care Organizer App",        "Fed. Walked. Cared for.",                "https://app.clearfolks.com/cf-eog81o2l",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-ex31190f",   "Meal Planner & Grocery App",    "Planned. Shopped. Served.",              "https://app.clearfolks.com/cf-ex31190f",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-ujpf3au3",   "Moving Day Organizer App",      "Packed. Labeled. Nothing lost.",         "https://app.clearfolks.com/cf-ujpf3au3",      "https://www.etsy.com/shop/clearfolk",                                                   True),
    ("cf-6juuqoo9",   "Travel Planner App",            "Booked. Packed. Wheels up.",             "https://app.clearfolks.com/cf-6juuqoo9",      "https://www.etsy.com/shop/clearfolk",                                                   True),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated slugs to render (default: all existing)")
    parser.add_argument("--product", nargs=6, metavar=("SLUG", "NAME", "TAGLINE", "APP_URL", "ETSY_URL", "FULL"),
                        help="render a single ad-hoc product; FULL must be 'yes' or 'no'")
    parser.add_argument("--readme-only", action="store_true",
                        help="rewrite README.md only, skip mockups/videos/PDF")
    args = parser.parse_args()

    if args.product:
        slug, name, tagline, app_url, etsy_url, full = args.product
        render_product(slug, name, tagline, app_url, etsy_url, full.lower() == "yes",
                       readme_only=args.readme_only)
        return

    targets = EXISTING
    if args.only:
        wanted = set(s.strip() for s in args.only.split(","))
        targets = [p for p in EXISTING if p[0] in wanted]

    for spec in targets:
        try:
            render_product(*spec, readme_only=args.readme_only)
        except SystemExit as e:
            print(f"  !! {spec[0]} failed: {e}")
            continue


if __name__ == "__main__":
    main()
