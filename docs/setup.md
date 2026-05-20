# Droplet Setup Guide — Clearfolks Pipeline

Use this to rebuild the entire pipeline from scratch on a new droplet.

## Prerequisites

- Ubuntu 24.04 droplet (4GB RAM minimum)
- Domain pointed to droplet IP
- Anthropic API key
- Telegram bot token (create via @BotFather)

---

## Step 1 — Install dependencies

```bash
apt update && apt upgrade -y
apt install -y nginx certbot python3-certbot-nginx git
python3 -m venv ~/clearfolks/venv
~/clearfolks/venv/bin/pip install anthropic
```

## Step 2 — SSL certificate

```bash
certbot --nginx -d app.clearfolks.com
```

## Step 3 — Environment variables

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
echo 'export TELEGRAM_BOT_TOKEN="..."' >> ~/.bashrc
echo 'export TELEGRAM_CHAT_ID="..."' >> ~/.bashrc
source ~/.bashrc
```

## Step 4 — Clone repo and set up scripts

```bash
git clone https://github.com/git-clearfolks/clearfolks_pwa.git
cp clearfolks_pwa/agents/*.py ~/clearfolks/
cp clearfolks_pwa/data/*.json ~/clearfolks/
```

## Step 5 — Create folder structure

```bash
mkdir -p ~/clearfolks/{signals,logs,drafts/pinterest,drafts/blog,drafts/listings}
mkdir -p /var/www/clearfolk
```

## Step 6 — Nginx config

```bash
cp clearfolks_pwa/nginx/clearfolk /etc/nginx/sites-available/clearfolk
ln -s /etc/nginx/sites-available/clearfolk /etc/nginx/sites-enabled/clearfolk
nginx -t && systemctl reload nginx
```

## Step 7 — Telegram bot as systemd service

```bash
cat > /etc/systemd/system/clearfolks-bot.service << EOF
[Unit]
Description=Clearfolks HQ Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/clearfolks
Environment="ANTHROPIC_API_KEY=your-key"
Environment="TELEGRAM_BOT_TOKEN=your-token"
Environment="TELEGRAM_CHAT_ID=your-chat-id"
ExecStart=/root/clearfolks/venv/bin/python /root/clearfolks/telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable clearfolks-bot
systemctl start clearfolks-bot
```

## Step 8 — Cron schedule

```bash
crontab -e
```

Add:
```
0 7 * * * /root/clearfolks/venv/bin/python /root/clearfolks/pulse.py >> /root/clearfolks/logs/cron.log 2>&1
30 7 * * * /root/clearfolks/venv/bin/python /root/clearfolks/echo.py >> /root/clearfolks/logs/cron.log 2>&1
0 6 * * 0 /root/clearfolks/venv/bin/python /root/clearfolks/discover.py >> /root/clearfolks/logs/cron.log 2>&1
0 8 * * 1 /root/clearfolks/venv/bin/python /root/clearfolks/sofia.py --pending >> /root/clearfolks/logs/cron.log 2>&1
0 5 1 * * /root/clearfolks/venv/bin/python /root/clearfolks/research.py >> /root/clearfolks/logs/cron.log 2>&1
```

## Step 9 — Verify

```bash
~/clearfolks/venv/bin/python ~/clearfolks/pulse.py   # should find signals
~/clearfolks/venv/bin/python ~/clearfolks/qa.py      # should pass all products
systemctl status clearfolks-bot                       # should show active
```
