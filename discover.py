#!/usr/bin/env python3
"""
Layer 2 — Forum Discovery Agent
Runs weekly (Sunday). Reads categories.json, finds best subreddits for each.
Outputs subreddits.json consumed by Pulse (Layer 3).
"""

import os
import sys
import json
import urllib.request
from datetime import datetime
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
CATEGORIES_FILE = "/root/clearfolks/categories.json"
SUBREDDITS_FILE = "/root/clearfolks/subreddits.json"
LOGS_DIR = "/root/clearfolks/logs"

DISCOVER_PROMPT = """You are a community research analyst for Clearfolks Templates, an Etsy store selling PWA digital organizer apps.

For each product category below, identify the 3 best subreddits where the TARGET BUYER actively discusses their problems.

TARGET BUYER PROFILE:
- Unpaid, non-professional person managing a complex life situation
- Currently overwhelmed and disorganized
- Would buy a practical digital tool if they knew it existed
- Active on Reddit asking for advice and recommendations

SUBREDDIT SCORING CRITERIA:
- Active community (posts daily or weekly, not abandoned)
- Members discuss real pain points, not just news or theory
- Buyer language present: "how do I track", "I need a system", "overwhelmed", "help me organize"
- NOT professional communities (no nurses forums, no enterprise software communities)

For each category output a JSON object. Respond only with a JSON array, no other text:
[
  {
    "category": "exact category name from input",
    "subreddits": [
      {
        "name": "subreddit name without r/",
        "why": "one sentence on why this community has buyers",
        "buyer_language_examples": ["example phrase 1", "example phrase 2"],
        "confidence": "high/medium/low"
      }
    ]
  }
]

Categories to research:
CATEGORIES_PLACEHOLDER"""

def validate_subreddit(name):
    url = f"https://www.reddit.com/r/{name}/new/.rss?limit=1"
    headers = {"User-Agent": "ClearfolksBot/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except:
        return False

def run_discover():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Layer 2 discovery running — {date_str}")

    if not os.path.exists(CATEGORIES_FILE):
        print("ERROR: categories.json not found. Run research.py first.")
        sys.exit(1)

    with open(CATEGORIES_FILE) as f:
        data = json.load(f)

    categories = data.get("categories", [])
    if not categories:
        print("ERROR: No active categories found.")
        sys.exit(1)

    print(f"Found {len(categories)} categories to research...")
    category_list = "\n".join([f"- {c['category']}" for c in categories])
    prompt = DISCOVER_PROMPT.replace("CATEGORIES_PLACEHOLDER", category_list)

    print("Asking Claude for subreddit recommendations...")
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()

    try:
        results = json.loads(clean)
    except Exception as e:
        print(f"ERROR: Could not parse response: {e}")
        print(f"Raw preview: {raw[:300]}")
        sys.exit(1)

    print(f"Validating subreddits against Reddit...")
    validated = []
    skipped = []
    for cat_result in results:
        cat_name = cat_result["category"]
        good_subs = []
        for sub in cat_result.get("subreddits", []):
            name = sub["name"]
            is_live = validate_subreddit(name)
            status = "OK" if is_live else "DEAD"
            print(f"  r/{name} ({cat_name}): {status}")
            if is_live:
                good_subs.append(sub)
            else:
                skipped.append(name)
        if good_subs:
            validated.append({
                "category": cat_name,
                "subreddits": good_subs
            })

    # Build flat unique subreddit list for Pulse
    seen = set()
    flat_list = []
    for cat_result in validated:
        for sub in cat_result["subreddits"]:
            name = sub["name"]
            if name not in seen:
                seen.add(name)
                flat_list.append({
                    "name": name,
                    "category": cat_result["category"],
                    "confidence": sub.get("confidence", "medium"),
                    "why": sub.get("why", "")
                })

    # Sort by confidence
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    flat_list.sort(key=lambda x: confidence_order.get(x["confidence"], 3))

    output = {
        "updated": date_str,
        "total": len(flat_list),
        "skipped": skipped,
        "by_category": validated,
        "flat_list": flat_list
    }

    with open(SUBREDDITS_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSummary:")
    print(f"  Categories researched: {len(results)}")
    print(f"  Subreddits validated: {len(flat_list)}")
    print(f"  Dead/skipped: {len(skipped)}")
    print(f"\nTop subreddits for Pulse:")
    for s in flat_list[:10]:
        print(f"  [{s['confidence'].upper()}] r/{s['name']} — {s['category']}")

    print(f"\nSaved: {SUBREDDITS_FILE}")

    log_path = f"{LOGS_DIR}/discover.log"
    with open(log_path, "a") as log:
        log.write(f"{date_str}: {len(categories)} categories → {len(flat_list)} subreddits validated\n")

if __name__ == "__main__":
    run_discover()
