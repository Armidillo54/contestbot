#!/usr/bin/env python3
"""ContestBot Scraper - Scrapes Canadian NPN contest aggregators."""

import json
import logging
import re
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path('contests_database.json')
CONFIG_PATH = Path('config.json')


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_database():
    if DB_PATH.exists():
        with open(DB_PATH) as f:
            return json.load(f)
    return {'contests': [], 'last_updated': None, 'total_active': 0, 'total_prize_value': 0}


def save_database(db):
    db['last_updated'] = date.today().isoformat()
    db['total_active'] = len([c for c in db['contests'] if c['status'] == 'active'])
    db['total_prize_value'] = sum(c.get('prize_value', 0) for c in db['contests'] if c['status'] == 'active')
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Database saved: {db['total_active']} active contests, ${db['total_prize_value']:,} total value")


def scrape_contestgirl(config):
    """Scrape ContestGirl for Canadian contests."""
    contests = []
    urls = [
        'https://www.contestgirl.com/contests/contests.pl?f=d&c=ca&b=nb&sort=p&ar=na&s=_',
        'https://www.contestgirl.com/contests/contests.pl?f=w&c=ca&b=nb&sort=p&ar=na&s=_',
        'https://www.contestgirl.com/contests/contests.pl?f=s&c=ca&b=nb&sort=p&ar=na&s=_',
    ]
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            for row in soup.select('tr'):
                text = row.get_text(separator=' ', strip=True)
                link = row.find('a', href=True)
                if not link:
                    continue

                end_match = re.search(r'End Date:\s*(\w+ \d+,\s*\d{4})', text)
                if not end_match:
                    continue

                try:
                    end_date = datetime.strptime(end_match.group(1).strip(), '%B %d, %Y').date()
                except ValueError:
                    continue

                if end_date < date.today():
                    continue

                prize_match = re.search(r'\$([\d,]+)', text)
                prize_value = int(prize_match.group(1).replace(',', '')) if prize_match else 0

                provinces_ok = True
                province_filters = config.get('filters', {}).get('provinces', ['Ontario', 'All Canada'])
                exclude_kw = config.get('filters', {}).get('exclude_keywords', [])
                for kw in exclude_kw:
                    if kw.lower() in text.lower():
                        provinces_ok = False
                        break

                if not provinces_ok:
                    continue

                freq = 'daily'
                if 'f=w' in url:
                    freq = 'weekly'
                elif 'f=s' in url:
                    freq = 'single'
                elif 'f=m' in url:
                    freq = 'monthly'

                contest_id = re.sub(r'[^a-z0-9]', '-', link.text.lower().strip())[:50]

                contests.append({
                    'id': contest_id,
                    'name': link.text.strip(),
                    'url': link['href'] if link['href'].startswith('http') else f"https://www.contestgirl.com{link['href']}",
                    'prize': text[:200],
                    'prize_value': prize_value,
                    'entry_method': 'online_form',
                    'entry_frequency': freq,
                    'npn': True,
                    'npn_note': 'Scraped from ContestGirl',
                    'restrictions': '',
                    'provinces': ['All Canada'],
                    'end_date': end_date.isoformat(),
                    'source': 'contestgirl.com',
                    'status': 'active',
                    'last_entered': None
                })

            logger.info(f"Scraped {len(contests)} contests from {url}")

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")

    return contests


def scrape_redflagdeals():
    """Scrape RedFlagDeals contest section."""
    contests = []
    url = 'https://www.redflagdeals.com/deals/category/contests/'
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        for item in soup.select('.list_item, .deal_container, article'):
            link = item.find('a', href=True)
            if not link:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            contest_id = re.sub(r'[^a-z0-9]', '-', title.lower())[:50]
            href = link['href']
            if not href.startswith('http'):
                href = f"https://www.redflagdeals.com{href}"

            contests.append({
                'id': f"rfd-{contest_id}",
                'name': title,
                'url': href,
                'prize': title,
                'prize_value': 0,
                'entry_method': 'online_form',
                'entry_frequency': 'single',
                'npn': True,
                'npn_note': 'From RedFlagDeals - verify NPN status',
                'restrictions': '',
                'provinces': ['All Canada'],
                'end_date': '',
                'source': 'redflagdeals.com',
                'status': 'unverified',
                'last_entered': None
            })

        logger.info(f"Scraped {len(contests)} from RedFlagDeals")

    except Exception as e:
        logger.error(f"Error scraping RFD: {e}")

    return contests


def merge_contests(db, new_contests):
    """Merge new contests into database, avoiding duplicates."""
    existing_ids = {c['id'] for c in db['contests']}
    added = 0
    for contest in new_contests:
        if contest['id'] not in existing_ids:
            db['contests'].append(contest)
            existing_ids.add(contest['id'])
            added += 1
            logger.info(f"NEW: {contest['name']} (${contest['prize_value']:,})")
    return added


def expire_old_contests(db):
    """Mark expired contests."""
    today = date.today().isoformat()
    expired = 0
    for contest in db['contests']:
        if contest['status'] == 'active' and contest.get('end_date') and contest['end_date'] < today:
            contest['status'] = 'expired'
            expired += 1
            logger.info(f"EXPIRED: {contest['name']}")
    return expired


def run_scraper():
    """Main scraper entry point."""
    logger.info("=== ContestBot Scraper Starting ===")
    config = load_config()
    db = load_database()

    cg_contests = scrape_contestgirl(config)
    rfd_contests = scrape_redflagdeals()

    all_new = cg_contests + rfd_contests
    added = merge_contests(db, all_new)
    expired = expire_old_contests(db)

    save_database(db)
    logger.info(f"=== Scraper Done: {added} new, {expired} expired ===")
    return db


if __name__ == '__main__':
    run_scraper()
