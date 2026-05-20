#!/usr/bin/env python3
"""
Echo — Community Voice Publisher
Reads latest signal report, generates Pinterest pins and blog outlines.
Saves drafts to ~/clearfolks/drafts/
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
SIGNALS_DIR = "/root/clearfolks/signals"
PINTEREST_DIR = "/root/clearfolks/drafts/pinterest"
BLOG_DIR = "/root/clearfolks/drafts/blog"
LOGS_DIR = "/root/clearfolks/logs"

PRODUCT_NAMES = {
    "Caregiver Organizer App": "Caregiver Organizer App",
    "Caregiver Command Center": "Caregiver Organizer App",
    "Medication Tracker": "Medication Tracker",
    "IEP Parent Binder": "IEP Parent Binder",
    "IEP Meeting Prep Kit": "IEP Meeting Prep Kit",
    "Etsy Seller Business System": "Etsy Seller Business System",
    "Wedding Planning App": "Wedding Planning App",
    "Homeschool Planner App": "Homeschool Planner App",
    "Baby Tracker": "Baby Tracker and Postpartum App",
    "Baby Tracker and Postpartum App": "Baby Tracker and Postpartum App",
    "Meal Planner": "Meal Planner and Grocery App",
    "Meal Planner and Grocery App": "Meal Planner and Grocery App",
    "Moving Day Organizer App": "Moving Day Organizer App",
    "Travel Planner App": "Travel Planner App",
}

PINTEREST_PROMPT = """You are Echo, a content creator for Clearfolks Templates.

Write a Pinterest pin draft for the signal below.

RULES:
- Title: 6-10 words, practical and specific, no hype
- Description: 2-3 sentences max. Lead with the pain, offer the solution.
- Call to action: one line, direct
- Hashtags: 8-10 relevant hashtags
- Forbidden words: revolutionary, seamless, intuitive, game-changing, simply, just, solution (alone)
- Required mentions: at least one of: offline capability, one payment lifetime access, household sharing
- Use exact product name from PRODUCT MATCH — never invent a new name
- Tone: warm, practical, like advice from a friend who found a good tool

SIGNAL:
{SIGNAL}

Output format:
TITLE: [title]
DESCRIPTION: [description]
CTA: [call to action]
HASHTAGS: [hashtags]
BOARD: [suggested Pinterest board name]"""

BLOG_PROMPT = """You are Echo, a content strategist for Clearfolks Templates.

Write a blog post outline for the signal below.

RULES:
- Target reader: the exact person in the signal
- Headline: specific, problem-focused, no clickbait
- 5-7 sections with clear subheadings
- Each section: 1-2 sentence description of what it covers
- Natural product mention in section 3 or 4 — not the focus, just one option among practical advice
- Use exact product name — never invent a new name
- Forbidden words: revolutionary, seamless, game-changing, simply, just
- Required: mention offline capability OR one payment lifetime access OR household sharing
- End with a practical takeaway section
- Estimated read time: 4-6 minutes

SIGNAL:
{SIGNAL}

Output format:
HEADLINE: [headline]
META: [one sentence meta description for SEO]
SECTIONS:
1. [Section title] — [what it covers]
2. [Section title] — [what it covers]
...
PRODUCT MENTION: [exact line where product gets mentioned naturally]
TAKEAWAY: [closing practical advice]"""

def load_latest_signals():
    sig_files = sorted(Path(SIGNALS_DIR).glob("signals-*.md"))
    if not sig_files:
        print("No signal reports found")
        return None, []
    
    latest = sig_files[-1]
    print(f"Reading: {latest.name}")
    
    with open(latest) as f:
        content = f.read()
    
    # Parse signals from markdown
    signals = []
    current = {}
    for line in content.split("\n"):
        if line.startswith("## Signal"):
            if current and current.get("pain_point"):
                signals.append(current)
            current = {"header": line}
        elif line.startswith("**Category:**"):
            current["category"] = line.replace("**Category:**", "").strip()
        elif line.startswith("**Subreddit:**"):
            current["subreddit"] = line.replace("**Subreddit:**", "").strip()
        elif line.startswith("**Post:**"):
            current["post"] = line.replace("**Post:**", "").strip()
        elif line.startswith("**Key quote:**"):
            current["quote"] = line.replace("**Key quote:**", "").strip()
        elif line.startswith("**Pain point:**"):
            current["pain_point"] = line.replace("**Pain point:**", "").strip()
        elif line.startswith("**Product match:**"):
            raw = line.replace("**Product match:**", "").strip()
            current["product_match"] = PRODUCT_NAMES.get(raw.replace("Upcoming: ", ""), raw)
        elif line.startswith("**Score:**") or "Score" in line and "/10" in line:
            current["score"] = line
    if current and current.get("pain_point"):
        signals.append(current)
    
    return latest.stem, signals

def format_signal(s):
    return f"""Subreddit: {s.get('subreddit', '')}
Category: {s.get('category', '')}
Post: {s.get('post', '')}
Key quote: {s.get('quote', '')}
Pain point: {s.get('pain_point', '')}
Product match: {s.get('product_match', '')}"""

def generate_pinterest(signal, date_str, index):
    prompt = PINTEREST_PROMPT.replace("{SIGNAL}", format_signal(signal))
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    content = msg.content[0].text.strip()
    
    category_slug = signal.get("category", "general").lower().replace(" ", "-").replace("/", "-")[:30]
    path = f"{PINTEREST_DIR}/{date_str}-{index:02d}-{category_slug}.md"
    
    with open(path, "w") as f:
        f.write(f"# Pinterest Pin Draft — Signal {index}\n\n")
        f.write(f"**Source:** {signal.get('subreddit', '')} | {signal.get('score', '')}\n\n")
        f.write(f"**Pain point:** {signal.get('pain_point', '')}\n\n")
        f.write("---\n\n")
        f.write(content)
        f.write("\n\n---\n")
        f.write(f"*Generated: {date_str} | Product: {signal.get('product_match', '')}*\n")
    
    return path

def generate_blog(signal, date_str, index):
    prompt = BLOG_PROMPT.replace("{SIGNAL}", format_signal(signal))
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    content = msg.content[0].text.strip()
    
    category_slug = signal.get("category", "general").lower().replace(" ", "-").replace("/", "-")[:30]
    path = f"{BLOG_DIR}/{date_str}-{index:02d}-{category_slug}.md"
    
    with open(path, "w") as f:
        f.write(f"# Blog Outline — Signal {index}\n\n")
        f.write(f"**Source:** {signal.get('subreddit', '')} | {signal.get('score', '')}\n\n")
        f.write(f"**Pain point:** {signal.get('pain_point', '')}\n\n")
        f.write("---\n\n")
        f.write(content)
        f.write("\n\n---\n")
        f.write(f"*Generated: {date_str} | Product: {signal.get('product_match', '')}*\n")
    
    return path

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"Echo running — {date_str}")
    
    os.makedirs(PINTEREST_DIR, exist_ok=True)
    os.makedirs(BLOG_DIR, exist_ok=True)
    
    report_name, signals = load_latest_signals()
    if not signals:
        print("No signals to process")
        return
    
    # Filter to top signals only (score 7+)
    top_signals = [s for s in signals if "8" in s.get("score", "") or "7" in s.get("score", "") or "9" in s.get("score", "")]
    if not top_signals:
        top_signals = signals[:3]
    
    print(f"Processing {len(top_signals)} top signals...")
    
    pinterest_paths = []
    blog_paths = []
    
    for i, signal in enumerate(top_signals, 1):
        print(f"  Signal {i}: {signal.get('category', '?')} — {signal.get('subreddit', '?')}")
        
        p_path = generate_pinterest(signal, date_str, i)
        pinterest_paths.append(p_path)
        print(f"    Pinterest: {Path(p_path).name}")
        
        b_path = generate_blog(signal, date_str, i)
        blog_paths.append(b_path)
        print(f"    Blog: {Path(b_path).name}")
    
    # Log
    with open(f"{LOGS_DIR}/echo.log", "a") as log:
        log.write(f"{date_str}: {len(top_signals)} signals → {len(pinterest_paths)} pins + {len(blog_paths)} blogs\n")
    
    print(f"\nEcho done: {len(pinterest_paths)} Pinterest pins, {len(blog_paths)} blog outlines")
    print(f"Drafts saved to ~/clearfolks/drafts/")

if __name__ == "__main__":
    main()
