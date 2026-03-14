# 🧳 LinkedIn Leather Goods Outreach Bot

> Automated LinkedIn crawler + email outreach system for leather goods requirements.
> Built for compliance with LinkedIn ToS, GDPR, and CCPA.

---

## 📐 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR (main.py)                     │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  MODULE 1    │  │  MODULE 2    │  │     MODULE 3         │  │
│  │  CRAWLER     │→ │  DATA        │→ │  EMAIL GENERATOR     │  │
│  │              │  │  EXTRACTION  │  │                      │  │
│  │ LinkedIn API │  │ + Validation │  │ Jinja2 HTML + Text   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│          ↓                ↓                     ↓               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                MODULE 4: LOGGING SYSTEM                  │   │
│  │         SQLite DB  +  JSON Logs  +  CSV Logs             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

LinkedIn Official API (OAuth 2.0)
    ↓
crawler.py — Searches UGC posts by keyword + country
    ↓
LinkedInPost dataclass (normalized)
    ↓
email_generator.py — Renders Jinja2 HTML + plain text
    ↓
EmailSender — SMTP or SendGrid
    ↓
database.py — SQLAlchemy (SQLite / PostgreSQL)
    ↓
logger.py — JSON + CSV logs with rotation
```

---

## 📁 Project Structure

```
linkedin_bot/
├── main.py                        # Orchestrator entry point
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variable template
├── config/
│   └── config.yaml                # Full configuration
├── modules/
│   ├── crawler.py                 # LinkedIn API crawler
│   ├── email_generator.py         # Email rendering + sending
│   ├── logger.py                  # Activity logging + rotation
│   └── database.py                # SQLAlchemy models + DB init
├── templates/
│   ├── email_template.html        # HTML email (Jinja2)
│   └── email_template.txt         # Plain text email (Jinja2)
├── tests/
│   └── test_bot.py                # Full pytest test suite
├── logs/
│   └── requirements_log_SAMPLE.json  # Sample log format
└── data/                          # Auto-created, holds SQLite DB
```

---

## ⚙️ Setup Instructions

### 1. Clone & Install

```bash
git clone https://github.com/yourrepo/linkedin-leather-bot.git
cd linkedin-leather-bot
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium    # Optional: only for fallback scraping
```

### 2. LinkedIn API Setup

1. Go to https://developer.linkedin.com/
2. Create a new application
3. Request access to: **Marketing Developer Platform**
4. Enable scopes: `r_ugcposts`, `r_organization_social`, `r_basicprofile`
5. Generate OAuth 2.0 access token
6. Add credentials to `.env`

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your actual credentials
nano .env
```

### 4. Update Company Info

Edit `config/config.yaml`:
```yaml
company:
  name: "Your Leather Co."
  website: "https://yourcompany.com"
  catalog_url: "https://yourcompany.com/catalog"
  contact_email: "sales@yourcompany.com"
  contact_phone: "+91-XXXXXXXXXX"
```

---

## 🚀 Running the Bot

```bash
# Full run (all regions, all keywords)
python main.py

# Dry run (no emails sent — safe for testing)
python main.py --dry-run

# Filter by region
python main.py --region europe
python main.py --region india

# Filter by single keyword
python main.py --keyword "leather bags"

# Combine filters
python main.py --dry-run --region east_asia --keyword "leather sourcing"
```

---

## 🧪 Running Tests

```bash
pytest tests/test_bot.py -v
pytest tests/test_bot.py -v --cov=modules --cov-report=html
```

---

## ⏰ Scheduling (Cron)

Run daily at 9:00 AM:
```bash
crontab -e
# Add:
0 9 * * * /path/to/venv/bin/python /path/to/linkedin_bot/main.py >> /path/to/linkedin_bot/logs/cron.log 2>&1
```

Or using APScheduler (in-process):
```python
from apscheduler.schedulers.blocking import BlockingScheduler
scheduler = BlockingScheduler()
scheduler.add_job(run_bot, 'cron', hour=9, minute=0, args=[config])
scheduler.start()
```

---

## 📊 Log File Format

Location: `./logs/requirements_log_YYYY-MM-DD.json`

| Field          | Type    | Description                        |
|----------------|---------|------------------------------------|
| timestamp      | ISO8601 | When the record was logged         |
| post_url       | string  | LinkedIn post URL                  |
| company_name   | string  | Posting company name               |
| poster_name    | string  | LinkedIn user who posted           |
| region         | string  | Europe / India / East Asia / etc.  |
| country_code   | string  | ISO 2-letter country code          |
| contact_email  | string  | Extracted email (if found)         |
| email_valid    | bool    | Whether email passed validation    |
| keyword_match  | string  | Which keyword triggered this post  |
| email_sent     | Y / N   | Whether outreach email was sent    |
| email_sent_at  | ISO8601 | Timestamp of email send            |
| opted_out      | bool    | Whether contact is on opt-out list |

Logs rotate after **30 days** and are archived as `.gz` files.

---

## ⚠️ Compliance Notes

| Requirement       | Implementation                                     |
|-------------------|----------------------------------------------------|
| LinkedIn ToS      | Uses Official API only — no scraping               |
| Rate Limiting     | Max 100 req/hour with 3s polite delay              |
| GDPR              | Opt-out list, data retention limit (90 days)       |
| CCPA              | Unsubscribe link in every email                    |
| robots.txt        | N/A — using official API endpoints only            |
| Data Minimization | Only business-relevant fields stored               |

---

## 🔐 Security Checklist

- [ ] `.env` added to `.gitignore`
- [ ] LinkedIn API keys rotated every 90 days
- [ ] Database not exposed to public internet
- [ ] Email SMTP uses App Passwords (not main password)
- [ ] Opt-out requests processed within 48 hours

---

## 📬 Email Template Customization

Edit `templates/email_template.html` — it uses Jinja2 syntax:

```html
Dear {{ recipient_name }},

We noticed your post about {{ requirement_summary }}...
```

Available variables: `recipient_name`, `company_name`, `requirement_summary`,
`post_snippet`, `catalog_url`, `certifications`, `unsubscribe_url` and more.

---

## 🛠️ Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Expired token | Refresh LinkedIn OAuth token |
| 429 Too Many Requests | Rate limit hit | Bot auto-backs off; check RATE_LIMIT in config |
| SMTP Auth Error | Wrong credentials | Use App Password for Gmail |
| No posts found | Low API permissions | Request Marketing API access on LinkedIn |
