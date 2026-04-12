# ContestBot

Automated Canadian NPN (No Purchase Necessary) contest entry bot with daily scheduling via GitHub Actions.

## Features

- **Auto-Scraping**: Scrapes ContestGirl and RedFlagDeals daily for new Canadian NPN contests
- **Legal Compliance**: Province eligibility checking, age verification, entry frequency tracking
- **Smart Entry Bot**: Selenium-based form filler with human-like delays and retry logic
- **GitHub Actions**: Runs daily at 8 AM EDT via cron, auto-commits updated database
- **Contest Database**: 7 verified active contests pre-loaded (April 2026)

## Files

| File | Purpose |
|------|--------|
| `config.json` | User settings and personal info (EDIT THIS FIRST) |
| `contests_database.json` | Active contest database (auto-updated by scraper) |
| `contest_scraper.py` | Scrapes contest aggregator sites |
| `entry_bot.py` | Selenium bot that fills and submits contest forms |
| `legal_compliance.py` | Province/age/frequency eligibility checker |
| `requirements.txt` | Python dependencies |
| `.github/workflows/daily_scraper.yml` | GitHub Actions daily cron workflow |

## Quick Start

1. **Edit `config.json`** - Replace all `CHANGE_ME` fields with your real info
2. **Install deps**: `pip install -r requirements.txt`
3. **Run scraper**: `python contest_scraper.py`
4. **Run entry bot**: `python entry_bot.py`

## GitHub Actions (Automated)

The workflow runs daily at 12:00 UTC (8:00 AM EDT):
- Scrapes new contests from aggregator sites
- Runs compliance checks against your config
- Auto-commits updated database back to repo
- Trigger manually via Actions > Run workflow

## Active Contests (April 2026)

| Contest | Prize Value | Ends |
|---------|-----------|------|
| G Adventures Travel Voucher | $43,000 | May 6 |
| J.D. Power Sweepstakes | $20,000 | Dec 31 |
| Excel Concert Experience | $15,000 | May 31 |
| Coca-Cola FIFA World Cup | $8,820 | Jun 30 |
| Doritos F1 Las Vegas | $8,300 | Apr 28 |
| Best Buy 25th Anniversary | $5,000 | Apr 24 |
| Avocados from Mexico OLED TV | $3,100 | May 13 |

**Total Prize Pool: $103,220**

## Requirements

- Python 3.11+
- Chrome browser + ChromeDriver (for entry_bot.py)
- GitHub account (for Actions scheduling)

## Legal Note

This bot only enters NPN (No Purchase Necessary) contests that are legal in Ontario, Canada. It respects entry frequency limits and contest rules. Use responsibly.
