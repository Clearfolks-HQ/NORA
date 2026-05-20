# Clearfolks PWA — Autonomous Marketing & Product Pipeline

**Owner:** Zoiver Holding LLC (Debajit)
**Brand:** Clearfolks Templates
**Platform:** Etsy + custom PWA hosting
**Last updated:** 2026-04-23

---

## What This Is

An autonomous pipeline that runs on a DigitalOcean droplet and:

1. Finds buyers on Reddit before they've found a product
2. Drafts Reddit responses, Pinterest pins, and blog outlines
3. Generates Etsy listing copy for new products
4. Builds new PWA products from a category spec
5. Pushes daily signal reports to Telegram with reply text and buy links

No paid ads. No email blasts. Signal-first, human-reviewed, draft-only.

---

## Architecture

```
Layer 1 — Monthly (1st of month, 5am)
  research.py → categories.json
  "Which Etsy categories should we build for?"

Layer 2 — Weekly (Sunday, 6am)
  discover.py → subreddits.json
  "Which subreddits have buyers for each category?"

Layer 3 — Daily (7am)
  pulse.py → signals-YYYY-MM-DD.md
  "Who posted today showing buying intent?"

Layer 3b — Daily (7:30am)
  echo.py → drafts/pinterest/ + drafts/blog/
  "Draft Pinterest pins and blog outlines from signals"

Layer 4 — Weekly (Monday, 8am)
  sofia.py → drafts/listings/
  "Write Etsy listing copy for pending products"

Layer 5 — On demand
  forge.py → /var/www/clearfolk/[slug]/
  "Build and deploy a new PWA product"

Control layer — Always on
  telegram_bot.py → Telegram @Cf_pwa_bot
  Commands: /signals /categories /products /status /add /remove
```

---

## Infrastructure

| Component | Detail |
|---|---|
| Droplet | gurukul-prod, 4GB/80GB, Ubuntu 24.04, NYC3 |
| IP | 159.65.47.63 |
| Domain | app.clearfolks.com (SSL via Let's Encrypt) |
| Web server | Nginx |
| Python | 3.12 via venv at ~/clearfolks/venv |
| Bot | @Cf_pwa_bot on Telegram |

---

## Live Products

| ID | Name | URL | Etsy |
|---|---|---|---|
| P0001 | Caregiver Command Center | app.clearfolks.com/caregiver | [listing](https://www.etsy.com/listing/4490826785) |
| P0002 | Medication Tracker | app.clearfolks.com/cf-bqs4r8e9 | [listing](https://www.etsy.com/listing/4490844238) |
| P0003 | IEP Parent Binder | app.clearfolks.com/cf-9x25jxsc | [listing](https://www.etsy.com/listing/4490835131) |
| P0004 | IEP Meeting Prep Kit | app.clearfolks.com/cf-qatxssg7 | [listing](https://www.etsy.com/listing/4490828563) |
| P0005 | Etsy Seller Business System | app.clearfolks.com/cf-63nja3ht | [listing](https://www.etsy.com/listing/4490841158) |
| P0006 | Wedding Planning App | app.clearfolks.com/cf-2465sd9i | pending |

---

## Directory Structure on Droplet

```
~/clearfolks/
├── pulse.py          — signal detection agent
├── echo.py           — content draft agent
├── sofia.py          — Etsy listing copy agent
├── forge.py          — PWA builder agent
├── research.py       — category research agent
├── discover.py       — subreddit discovery agent
├── qa.py             — product QA checker
├── telegram_bot.py   — Telegram control bot
├── categories.json   — active product categories
├── subreddits.json   — active subreddit scan list
├── products.json     — product registry
├── venv/             — Python virtual environment
├── signals/          — daily signal reports
├── drafts/
│   ├── pinterest/    — Pinterest pin drafts
│   ├── blog/         — blog outline drafts
│   └── listings/     — Etsy listing drafts
└── logs/
    ├── pulse.log
    ├── echo.log
    ├── sofia.log
    ├── forge.log
    ├── discover.log
    └── cron.log

/var/www/clearfolk/
├── index.html        — product index page
├── manifest.json     — shared PWA manifest
├── sw.js             — shared service worker
├── icons/            — shared PWA icons
├── caregiver/        — P0001
├── cf-bqs4r8e9/      — P0002
├── cf-9x25jxsc/      — P0003
├── cf-qatxssg7/      — P0004
├── cf-63nja3ht/      — P0005
└── cf-2465sd9i/      — P0006
```

---

## Environment Variables Required

```bash
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=8670918186
```

Set in `~/.bashrc` on the droplet. Also set in `/etc/systemd/system/clearfolks-bot.service`.

---

## Forbidden Words (all agent output)

PWA, Progressive Web App, revolutionary, seamless, intuitive, solution (alone), simply, just, game-changing

## Required Mentions (product copy)

offline capability, one payment lifetime access no subscription, household sharing

## Brand Close

Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com
