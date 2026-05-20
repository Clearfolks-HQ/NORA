#!/usr/bin/env python3
"""Screenshot — capture real screenshots of each live Clearfolks PWA.

Writes to /root/clearfolks/screenshots/:
    <slug>-mobile.png             — 390×844, default dashboard view
    <slug>-mobile-<section>.png   — up to 3 other sections (for feature cards)
    <slug>-desktop.png            — 1280×800, for video Ken Burns + feature crops

Cache-busts the URL with ?v=<timestamp> so Playwright always gets the latest
HTML and seeded state. Waits for networkidle + a short hydration delay so
state-driven renders have fired before the screenshot.
"""
import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks"))
SHOTS = HOME / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
PRODUCTS_FILE = HOME / "products.json"

MOBILE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}

# Common section-switch function names across the 12 generated PWAs.
SWITCH_CANDIDATES = [
    "switchSection", "navigate", "showSection", "go", "goTo",
    "app.switchSection", "app.navigate", "app.showSection", "app.go",
]

# A section ID we'd want to capture for feature cards (in priority order, after
# the dashboard). We pick the first 3 that exist per product.
SECTION_HINTS = [
    "feeding", "feed", "sleep", "diapers", "diaper", "milestones", "milestone",
    "health", "postpartum", "meals", "recipes", "grocery", "family",
    "vendors", "budget", "guests", "timeline",
    "schedule", "assignments", "children", "subjects", "progress",
    "pets", "medications", "appointments", "grooming",
    "rooms", "packing", "addresses", "utilities",
    "itinerary", "accommodation", "activities",
    "goals", "meetings", "services", "sales", "expenses", "listings",
    "questions", "actions", "notes", "contacts", "documents",
    "trips", "shared",
]

# Sections that usually *are* the default landing view — skip them so the
# three feature-card shots show real secondary views, not duplicates of the
# hero dashboard.
SKIP_AS_FEATURE = {"dashboard", "home", "overview"}


def bust(url: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={int(time.time())}"


def discover_sections(page):
    """Return ordered list of section IDs in this PWA.

    Handles three common conventions produced by forge:
      - <section id="X" class="section">             (forge v2/v3)
      - <div id="page-X" class="page">              (forge v1 compact style)
      - [data-section="X"] markers
    For page-X patterns, the 'page-' prefix is stripped so callers pass the
    bare section name (the pattern used by the generated `go(id,…)` function).
    """
    ids = page.evaluate(
        """() => {
            const sel = '.section, section.section, .page, [id^="page-"], [data-section]';
            const els = Array.from(document.querySelectorAll(sel));
            return Array.from(new Set(
                els.map(el => {
                    let id = el.id || el.getAttribute('data-section');
                    if (!id) return null;
                    if (id.startsWith('page-')) id = id.slice(5);
                    return id;
                }).filter(Boolean)
            ));
        }"""
    )
    return ids


def try_switch(page, section_id: str) -> bool:
    """Attempt to navigate to a section via any of the known function names.
    Returns True if at least one call succeeded without exception."""
    for fn in SWITCH_CANDIDATES:
        try:
            res = page.evaluate(
                f"() => typeof {fn} === 'function' ? ({fn}('{section_id}'), true) : false"
            )
            if res:
                return True
        except Exception:
            pass
    # Last resort — click a nav item whose onclick references the section.
    try:
        sel = f"[onclick*=\"{section_id}\"]"
        el = page.query_selector(sel)
        if el:
            el.click()
            return True
    except Exception:
        pass
    return False


def capture(page, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=False)


def shoot_product(browser, slug: str, url: str) -> dict:
    """Capture a product. Returns dict of shot paths."""
    result = {"slug": slug, "url": url, "mobile": None, "desktop": None, "sections": []}

    # --- Mobile ---
    ctx = browser.new_context(viewport=MOBILE, device_scale_factor=2)
    page = ctx.new_page()
    try:
        page.goto(bust(url), wait_until="networkidle", timeout=30000)
    except Exception as e:
        print(f"  [mobile] goto failed: {e}")
    page.wait_for_timeout(1800)

    mobile_path = SHOTS / f"{slug}-mobile.png"
    capture(page, mobile_path)
    result["mobile"] = str(mobile_path)

    # --- Extra section shots (for image-2 feature cards) ---
    sections = discover_sections(page)
    # Never re-shoot the default landing view.
    sections = [s for s in sections if s.lower() not in SKIP_AS_FEATURE]
    preferred = [s for s in SECTION_HINTS if s in sections]
    rest = [s for s in sections if s not in preferred]
    ordered = preferred + rest
    picks = []
    for sec in ordered:
        if len(picks) >= 3:
            break
        if try_switch(page, sec):
            page.wait_for_timeout(700)
            out = SHOTS / f"{slug}-mobile-{sec}.png"
            capture(page, out)
            picks.append((sec, str(out)))
    result["sections"] = picks
    ctx.close()

    # --- Desktop ---
    ctx2 = browser.new_context(viewport=DESKTOP, device_scale_factor=1)
    page2 = ctx2.new_page()
    try:
        page2.goto(bust(url), wait_until="networkidle", timeout=30000)
    except Exception as e:
        print(f"  [desktop] goto failed: {e}")
    page2.wait_for_timeout(1800)
    desktop_path = SHOTS / f"{slug}-desktop.png"
    capture(page2, desktop_path)
    result["desktop"] = str(desktop_path)
    ctx2.close()

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="capture only this slug (default: all from products.json)")
    args = parser.parse_args()

    products = json.loads(PRODUCTS_FILE.read_text())["products"]
    if args.slug:
        products = [p for p in products if p["slug"] == args.slug]
        if not products:
            raise SystemExit(f"slug {args.slug} not found in products.json")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for product in products:
                slug = product["slug"]
                name = product["name"]
                url = product["url"]
                print(f"\n--- {slug} : {name} ---")
                result = shoot_product(browser, slug, url)
                print(f"  mobile  : {result['mobile']}")
                for sec, path in result["sections"]:
                    print(f"  section : {sec:14s} -> {path}")
                print(f"  desktop : {result['desktop']}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
