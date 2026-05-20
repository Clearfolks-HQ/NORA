# Clearfolks Operations Playbook

**Purpose:** Complete operating guide for running, managing, and triaging the Clearfolks pipeline without Claude's help.

---

## Daily Routine (10 minutes)

Every morning at ~7am Telegram sends you 3 signal messages automatically.

**For each signal:**
1. Read the pain point — does this person clearly need the product?
2. Read the suggested reply — edit if needed (max 2-3 sentences tweak)
3. Tap the Reddit link → open the post → paste the reply
4. Check the Etsy buy link is correct for the product mentioned

That's it. The pipeline handles everything else.

---

## Weekly Routine (10 minutes, Sunday)

```bash
ssh root@159.65.47.63
cat ~/clearfolks/logs/pulse.log | tail -7       # last 7 days of signal counts
cat ~/clearfolks/logs/cron.log | tail -20        # check for cron errors
~/clearfolks/venv/bin/python ~/clearfolks/qa.py  # QA all products
```

Check Telegram `/status` for pipeline summary.

---

## Telegram Commands

| Command | What it does |
|---|---|
| `/signals` | Show today's top signals |
| `/products` | Show all live products with URLs |
| `/categories` | Show tracked category list |
| `/status` | Pipeline last-run summary |
| `/add Garden Planner` | Add a new category to track |
| `/remove Garden Planner` | Remove a category |

---

## How to Build a New PWA Product

```bash
ssh root@159.65.47.63

# See what's available to build
~/clearfolks/venv/bin/python ~/clearfolks/forge.py --list

# Build a specific product
~/clearfolks/venv/bin/python ~/clearfolks/forge.py "Homeschool Planner App"

# Build next in queue
~/clearfolks/venv/bin/python ~/clearfolks/forge.py --next
```

Forge will:
- Generate the PWA (two-pass: HTML then JS)
- Deploy to /var/www/clearfolk/[slug]/
- Add nginx route and reload nginx
- Register in products.json
- Send you a Telegram message with the live URL

After Forge runs:
1. Open the URL on your phone — test all nav buttons
2. Run QA: `~/clearfolks/venv/bin/python ~/clearfolks/qa.py`
3. Run Sofia to generate the Etsy listing copy:
   `~/clearfolks/venv/bin/python ~/clearfolks/sofia.py "Product Name"`
4. Review draft in `~/clearfolks/drafts/listings/`
5. Create the Etsy listing manually — paste the copy

---

## How to Add a New Subreddit Manually

```bash
ssh root@159.65.47.63
cat ~/clearfolks/subreddits.json | python3 -m json.tool | head -40
```

Edit subreddits.json to add:
```json
{
  "name": "subredditname",
  "category": "Category Name",
  "confidence": "high",
  "why": "Why this community has buyers"
}
```

Or just wait for Sunday — Discover runs automatically and refreshes the list.

---

## How to Update Etsy URLs in products.json

```bash
ssh root@159.65.47.63
nano ~/clearfolks/products.json
```

Find the product by ID, update the `etsy_url` field with the full public Etsy listing URL.

---

## Cron Schedule

```
0 7 * * *    pulse.py      — daily signal scan
30 7 * * *   echo.py       — daily content drafts
0 6 * * 0    discover.py   — weekly subreddit refresh
0 8 * * 1    sofia.py      — weekly listing copy for pending products
0 5 1 * *    research.py   — monthly category research
```

---

## Triage Guide

### Problem: No Telegram message this morning

```bash
ssh root@159.65.47.63
systemctl status clearfolks-bot       # is the bot running?
cat ~/clearfolks/logs/cron.log | tail -20   # did pulse run?
cat ~/clearfolks/logs/pulse.log | tail -5   # last pulse run
```

If bot is down:
```bash
systemctl restart clearfolks-bot
systemctl status clearfolks-bot
```

If pulse didn't run — check cron:
```bash
crontab -l
grep CRON /var/log/syslog | tail -20
```

---

### Problem: Pulse finds 0 signals

This is normal sometimes — posts change daily. Check if subreddits are still accessible:

```bash
~/clearfolks/venv/bin/python ~/clearfolks/discover.py
```

This re-validates all subreddits and refreshes the list.

---

### Problem: Forge builds a broken PWA (buttons not working)

```bash
# Run QA to see what's broken
~/clearfolks/venv/bin/python ~/clearfolks/qa.py

# Check what functions are missing
grep "MISSING FUNCTION" ~/clearfolks/logs/qa-report.json
```

If JS is missing entirely — the HTML was cut off. Rebuild:
```bash
~/clearfolks/venv/bin/python ~/clearfolks/forge.py "Product Name"
```

If specific functions are missing — patch manually:
```bash
nano /var/www/clearfolk/[slug]/index.html
# Add missing functions before </script>
nginx -t && systemctl reload nginx
```

---

### Problem: Nginx not serving a PWA

```bash
nginx -t                                    # test config
cat /etc/nginx/sites-available/clearfolk    # check routes
systemctl status nginx
systemctl reload nginx
```

If a route is missing — add it manually to nginx config:
```nginx
location /cf-[slug] {
    alias /var/www/clearfolk/cf-[slug];
    try_files $uri $uri/ /cf-[slug]/index.html;
    add_header Cache-Control "public, max-age=3600, must-revalidate";
}
```

Then: `nginx -t && systemctl reload nginx`

---

### Problem: Anthropic API errors

```bash
echo $ANTHROPIC_API_KEY | cut -c1-20    # verify key is set
# Key should start with sk-ant-api03-
```

If key is wrong or expired:
```bash
nano ~/.bashrc
# Update ANTHROPIC_API_KEY line
source ~/.bashrc
# Also update the systemd service:
nano /etc/systemd/system/clearfolks-bot.service
systemctl daemon-reload
systemctl restart clearfolks-bot
```

---

### Problem: Telegram bot not responding to commands

```bash
systemctl status clearfolks-bot
journalctl -u clearfolks-bot -n 50 --no-pager
systemctl restart clearfolks-bot
```

---

### Problem: SSL certificate expired

```bash
certbot renew
systemctl reload nginx
```

---

## How to Run Each Agent Manually

```bash
ssh root@159.65.47.63
cd ~/clearfolks

# Pulse — scan signals now
~/clearfolks/venv/bin/python pulse.py

# Echo — draft content from latest signals
~/clearfolks/venv/bin/python echo.py

# Sofia — write Etsy listing for specific product
~/clearfolks/venv/bin/python sofia.py "Wedding Planning App"
~/clearfolks/venv/bin/python sofia.py --pending   # all without listings
~/clearfolks/venv/bin/python sofia.py --all       # all products

# Research — run category research now
~/clearfolks/venv/bin/python research.py

# Discover — refresh subreddit list now
~/clearfolks/venv/bin/python discover.py

# QA — check all products
~/clearfolks/venv/bin/python qa.py

# Forge — build new PWA
~/clearfolks/venv/bin/python forge.py --list
~/clearfolks/venv/bin/python forge.py "Product Name"
~/clearfolks/venv/bin/python forge.py --next
```

---

## Reddit Response Strategy

When you post a reply to a signal:

1. Lead with empathy — acknowledge their pain first
2. Give one practical tip that works even without the product
3. Mention the product naturally — don't make it the focus
4. Include one differentiator: offline capability / one payment / household sharing
5. Never say: PWA, Progressive Web App, revolutionary, seamless, game-changing
6. Keep it under 150 words — Reddit readers skim

Good signal score to act on: 7+
Great signal score: 8-9 — prioritize these first

---

## When to Add a New Category

Use `/add Category Name` on Telegram when:
- You see repeated Reddit posts about a specific pain with no good digital tool
- A category has high Etsy search volume (check Etsy search bar suggestions)
- Someone asks you directly "do you have something for X?"

The next monthly research run will evaluate it properly.

---

## Key Principles

1. Cash before growth — respond to buyers, not browsers
2. Numbers before narratives — check signal scores, don't guess
3. Honesty before comfort — if a product isn't ready, don't list it
4. All agents are draft-only — nothing publishes without human approval
5. Mom Test — would a real person pay for this? Would they recommend it?
