#!/usr/bin/env python3
"""
Sofia — Etsy Listing Copy Agent
Generates complete Etsy listing copy for a given product.
Usage: sofia.py "Wedding Planning App"
       sofia.py --all  (generates for all products missing etsy copy)
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
PRODUCTS_FILE = "/root/clearfolks/products.json"
LISTINGS_DIR = "/root/clearfolks/drafts/listings"
LOGS_DIR = "/root/clearfolks/logs"

SOFIA_PROMPT = """You are Sofia, an Etsy listing copywriter for Clearfolks Templates.

Write a complete, high-converting Etsy listing for the product below.

ETSY LISTING RULES:
- Title: 120-140 chars, front-load keywords, pipe-separated sections
- Price positioning: significantly cheaper than competitors (BCRI, TechnoBridge, ICRI charge $150-400 for courses/tools — we charge a fraction)
- Description: lead with the buyer's pain, not the product features
- Use short paragraphs — Etsy buyers skim
- Required mentions in description: offline capability, one payment lifetime access no subscription, household sharing
- 5 bullet points: each starts with a benefit, ends with a feature
- 13 tags: mix of long-tail and short keywords
- Forbidden words: revolutionary, seamless, intuitive, game-changing, simply, just, solution (alone), PWA, Progressive Web App
- Brand close: "Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com"
- Tone: warm, practical, no hype

PRODUCT:
Name: {NAME}
Category: {CATEGORY}
Pain summary: {PAIN}
URL: {URL}

COMPETITOR CONTEXT:
Similar tools cost $50-200+. Our product is a one-time purchase significantly under that.

OUTPUT FORMAT:
TITLE: [etsy title]

PRICE SUGGESTION: $[price]

DESCRIPTION:
[full description, 150-200 words]

BULLET POINTS:
- [benefit — feature]
- [benefit — feature]
- [benefit — feature]
- [benefit — feature]
- [benefit — feature]

TAGS:
[tag1], [tag2], [tag3], [tag4], [tag5], [tag6], [tag7], [tag8], [tag9], [tag10], [tag11], [tag12], [tag13]

SECTION: [suggested Etsy shop section]"""

def load_products():
    if not os.path.exists(PRODUCTS_FILE):
        print("ERROR: products.json not found")
        sys.exit(1)
    with open(PRODUCTS_FILE) as f:
        return json.load(f)

def load_categories():
    cats_file = "/root/clearfolks/categories.json"
    if not os.path.exists(cats_file):
        return {}
    with open(cats_file) as f:
        data = json.load(f)
    return {c["suggested_product_name"]: c for c in data.get("categories", [])}

def generate_listing(product, category_data):
    name = product["name"]
    url = product["url"]
    category = product.get("category", "")
    pain = category_data.get("pain_summary", f"People managing {category.lower()} need a better organizational system")

    prompt = SOFIA_PROMPT.replace("{NAME}", name)
    prompt = prompt.replace("{CATEGORY}", category)
    prompt = prompt.replace("{PAIN}", pain)
    prompt = prompt.replace("{URL}", url)

    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()

def save_listing(product, content, date_str):
    os.makedirs(LISTINGS_DIR, exist_ok=True)
    slug = product["slug"]
    path = f"{LISTINGS_DIR}/{slug}-listing.md"
    with open(path, "w") as f:
        f.write(f"# Etsy Listing — {product['name']}\n\n")
        f.write(f"**Product ID:** {product['id']}\n")
        f.write(f"**URL:** {product['url']}\n")
        f.write(f"**Generated:** {date_str}\n\n")
        f.write("---\n\n")
        f.write(content)
        f.write("\n\n---\n")
        f.write(f"*Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com*\n")
    return path

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Sofia running — {date_str}")

    data = load_products()
    products = data.get("products", [])
    categories = load_categories()

    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        print("Available products:")
        for p in products:
            etsy = p.get("etsy_listing", "unknown")
            print(f"  [{p['id']}] {p['name']} — etsy: {etsy}")
        print("\nUsage:")
        print('  sofia.py "Wedding Planning App"')
        print("  sofia.py --all")
        print("  sofia.py --pending  (only products missing etsy listing)")
        return

    if sys.argv[1] == "--all":
        targets = products
    elif sys.argv[1] == "--pending":
        targets = [p for p in products if p.get("etsy_listing") in ("pending", "unknown", "")]
    else:
        name = " ".join(sys.argv[1:])
        targets = [p for p in products if p["name"].lower() == name.lower()]
        if not targets:
            print(f"Product '{name}' not found. Run --list to see options.")
            sys.exit(1)

    print(f"Generating listings for {len(targets)} product(s)...")

    for product in targets:
        name = product["name"]
        print(f"\n  [{product['id']}] {name}...")
        cat_data = categories.get(name, {})
        content = generate_listing(product, cat_data)
        path = save_listing(product, content, date_str)
        print(f"  Saved: {Path(path).name}")

    with open(f"{LOGS_DIR}/sofia.log", "a") as log:
        log.write(f"{date_str}: Generated listings for {[p['name'] for p in targets]}\n")

    print(f"\nSofia done. Listings saved to {LISTINGS_DIR}/")

if __name__ == "__main__":
    main()
