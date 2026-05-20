#!/usr/bin/env python3
"""
Layer 1 — Market Research Agent
Runs monthly. Identifies Etsy categories suitable for Clearfolks PWA products.
Outputs categories.json consumed by Layer 2 (discover.py).
"""

import os
import sys
import json
from datetime import datetime
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

RESEARCH_PROMPT = """You are a product strategist for Clearfolks Templates, an Etsy store selling PWA (Progressive Web App) digital organizer tools.

Our product format: a lightweight web app the buyer installs to their phone home screen from a link. Works offline. One payment, lifetime access, no subscription. Shareable across household. NOT a native app — no App Store involved. Think: smarter than a PDF printable, simpler than a full app.

Our current products:
- Caregiver Organizer App (family caregivers managing medications, appointments, care notes)
- Etsy Seller Organizer App (Etsy sellers managing orders, inventory, finances)

Your job: identify the best Etsy buyer categories we should target next for new PWA products OR confirm existing products fit well.

EVALUATION CRITERIA — a category scores well if:
1. Strong Etsy search demand for planners, organizers, trackers
2. Real coordination/tracking pain — managing something complex across time, people, or tasks
3. PWA sweet spot buyer — currently using binders, notebooks, spreadsheets, or printables. Frustrated. Not going to the App Store. Not a printables buyer either.
4. Evergreen OR reliably recurring seasonal demand
5. Household or team sharing makes sense

OUTPUT FORMAT — respond only with a JSON array, no other text:
[
  {
    "category": "category name",
    "type": "evergreen or seasonal",
    "seasonal_window": "e.g. Aug-Sep or null if evergreen",
    "pain_summary": "one sentence describing the core organizational pain",
    "pwa_fit": "high/medium/low",
    "pwa_fit_reason": "one sentence why PWA fits or does not",
    "etsy_demand": "high/medium/low",
    "etsy_demand_reason": "one sentence on Etsy search evidence",
    "existing_product_match": "Caregiver Organizer App or Etsy Seller Organizer App or none",
    "verdict": "build/validate/skip",
    "verdict_reason": "one sentence rationale",
    "suggested_product_name": "e.g. Wedding Planning App or null if skip"
  }
]

Evaluate these categories and add any strong ones you identify:
- Wedding planning
- Home renovation
- Pet care management
- Homeschool planning
- Rental property management
- Freelancer admin
- Fitness and nutrition tracking
- Tax season organizer
- School year planner
- Garden planner
- Meal planning and grocery
- Moving house organizer
- New baby and postpartum
- Event planning
- Travel planning

Be honest. Skip categories where PWA format is a poor fit or Etsy demand is clearly low."""

def run_research():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Layer 1 research running — {date_str}")
    print("Asking Claude to evaluate categories...")
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": RESEARCH_PROMPT}]
    )
    raw = message.content[0].text.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        categories = json.loads(clean)
    except Exception as e:
        print(f"ERROR: Could not parse response: {e}")
        print(f"Raw preview: {raw[:300]}")
        sys.exit(1)
    archive_path = f"/root/clearfolks/logs/research-{date_str}.json"
    with open(archive_path, "w") as f:
        json.dump(categories, f, indent=2)
    print(f"Research archived: {archive_path}")
    active = [c for c in categories if c.get("verdict") in ("build", "validate")]
    output_path = "/root/clearfolks/categories.json"
    with open(output_path, "w") as f:
        json.dump({"updated": date_str, "categories": active}, f, indent=2)
    print(f"Active categories saved: {output_path}")
    print(f"\nSummary:")
    print(f"  Total evaluated: {len(categories)}")
    print(f"  Build:    {len([c for c in categories if c['verdict'] == 'build'])}")
    print(f"  Validate: {len([c for c in categories if c['verdict'] == 'validate'])}")
    print(f"  Skip:     {len([c for c in categories if c['verdict'] == 'skip'])}")
    print(f"\nActive categories for Layer 2:")
    for c in active:
        print(f"  [{c['verdict'].upper()}] {c['category']} — {c.get('suggested_product_name') or c.get('existing_product_match')}")

if __name__ == "__main__":
    run_research()
