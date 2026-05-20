#!/usr/bin/env python3
"""
Spend Tracker — tracks Anthropic API usage and costs per agent.
Run after each agent or weekly for a summary.
Usage: spend.py --log agent_name input_tokens output_tokens model
       spend.py --report
       spend.py --weekly  (sends Telegram summary)
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

SPEND_LOG = "/root/clearfolks/logs/spend.json"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Anthropic pricing per million tokens (as of April 2026)
PRICING = {
    "claude-haiku-4-5": {
        "input": 0.80,   # $0.80 per million input tokens
        "output": 4.00   # $4.00 per million output tokens
    },
    "claude-sonnet-4-5": {
        "input": 3.00,   # $3.00 per million input tokens
        "output": 15.00  # $15.00 per million output tokens
    }
}

def load_spend():
    if not Path(SPEND_LOG).exists():
        return {"entries": []}
    with open(SPEND_LOG) as f:
        return json.load(f)

def save_spend(data):
    with open(SPEND_LOG, "w") as f:
        json.dump(data, f, indent=2)

def calc_cost(model, input_tokens, output_tokens):
    pricing = PRICING.get(model, PRICING["claude-haiku-4-5"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)

def log_usage(agent, input_tokens, output_tokens, model):
    data = load_spend()
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "agent": agent,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_usd": calc_cost(model, int(input_tokens), int(output_tokens))
    }
    data["entries"].append(entry)
    save_spend(data)
    print(f"Logged: {agent} — ${entry['cost_usd']:.4f}")

def generate_report(days=30):
    data = load_spend()
    entries = data.get("entries", [])
    if not days:
        relevant = entries
    else:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        relevant = [e for e in entries if e["date"] >= cutoff]

    if not relevant:
        return "No spend data found."

    total_cost = sum(e["cost_usd"] for e in relevant)
    by_agent = {}
    by_model = {}

    for e in relevant:
        agent = e["agent"]
        model = e["model"]
        cost = e["cost_usd"]
        by_agent[agent] = by_agent.get(agent, 0) + cost
        by_model[model] = by_model.get(model, 0) + cost

    lines = [f"Clearfolks API spend — last {days} days"]
    lines.append(f"Total: ${total_cost:.4f}")
    lines.append(f"Runs: {len(relevant)}")
    lines.append("")
    lines.append("By agent:")
    for agent, cost in sorted(by_agent.items(), key=lambda x: -x[1]):
        lines.append(f"  {agent}: ${cost:.4f}")
    lines.append("")
    lines.append("By model:")
    for model, cost in sorted(by_model.items(), key=lambda x: -x[1]):
        lines.append(f"  {model}: ${cost:.4f}")

    return "\n".join(lines)

def send_weekly_report():
    report = generate_report(days=7)
    if not TOKEN or not CHAT_ID:
        print("No Telegram config — printing report:")
        print(report)
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": f"*Clearfolks weekly spend*\n\n```\n{report}\n```",
        "parse_mode": "Markdown"
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
        print("Weekly report sent to Telegram")
    except Exception as e:
        print(f"Telegram error: {e}")
        print(report)

def main():
    if len(sys.argv) < 2:
        print(generate_report(days=30))
        return

    cmd = sys.argv[1]

    if cmd == "--log" and len(sys.argv) >= 6:
        log_usage(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "--report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print(generate_report(days=days))
    elif cmd == "--weekly":
        send_weekly_report()
    else:
        print("Usage:")
        print("  spend.py --log agent_name input_tokens output_tokens model")
        print("  spend.py --report [days]")
        print("  spend.py --weekly")

if __name__ == "__main__":
    main()
