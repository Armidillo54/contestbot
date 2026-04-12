# ContestBot

Free automated Canadian NPN (No Purchase Necessary) contest tracker with a daily dashboard hosted on GitHub Pages.

## Live Dashboard

View your daily contests and freebies at:
**https://armidillo54.github.io/contestbot/**

## Features

- **Auto-Scraping**: Scrapes ContestGirl and RedFlagDeals daily for new Canadian NPN contests
- **Legal Compliance**: Province eligibility checking, age verification, entry frequency tracking
- **Daily Dashboard**: Live GitHub Pages dashboard showing all active contests, new finds, and daily entry opportunities
- **Junk Cleaning**: Automatically removes invalid/duplicate entries from the database
- **GitHub Actions**: Runs daily at 8 AM EDT via cron, auto-commits updated database and deploys dashboard
- **100% Free**: No paid APIs or services required

## Files

| File | Purpose |
|------|--------|
| `dashboard.html` | Daily contests & freebies dashboard (deployed to GitHub Pages) |
| `config.json` | User settings and personal info (EDIT THIS FIRST) |
| `contests_database.json` | Active contest database (auto-updated by scraper) |
| `contest_scraper.py` | Scrapes contest aggregator sites |
| `entry_bot.py` | Selenium bot that fills and submits contest forms |
| `legal_compliance.py` | Province/age/frequency eligibility checker |
| `run_all.py` | Master pipeline orchestrator |
| `notifier.py` | Email notification sender |
| `.github/workflows/daily_scraper.yml` | GitHub Actions daily cron workflow |

## Quick Start

1. Edit `config.json` with your personal info
2. Go to Settings > Pages and set source to GitHub Actions
3. Optionally add `SMTP_USER`, `SMTP_PASS`, `NOTIFY_EMAIL` secrets for email notifications
4. Run the workflow manually from Actions tab or wait for the daily 8 AM cron
5. Visit your dashboard at `https://armidillo54.github.io/contestbot/`

## Dashboard Tabs

- **All Contests**: Every active NPN contest in the database
- **New Today**: Contests discovered in today's scrape
- **Daily Entry**: Contests you can enter every day
- **High Value**: Contests with prizes worth $5,000+
