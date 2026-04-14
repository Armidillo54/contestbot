#!/usr/bin/env python3
"""Scrapes Canadian freebie aggregator sites for free samples and deals."""

import json
import logging
import re
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FREEBIES_DB_PATH = Path('freebies_database.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def load_freebies_db():
    if FREEBIES_DB_PATH.exists():
        with open(FREEBIES_DB_PATH) as f:
            return json.load(f)
    return {'freebies': [], 'last_updated': None, 'total_freebies': 0}


def save_freebies_db(db):
    db['last_updated'] = date.today().isoformat()
    db['total_freebies'] = len([f for f in db['freebies'] if f['status'] == 'active'])
    with open(FREEBIES_DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Freebies DB saved: {db['total_freebies']} active")


def make_freebie_id(prefix, title):
    slug = re.sub(r'[^a-z0-9]', '-', title.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')[:50]
    return f"{prefix}-{slug}"


def scrape_canadianfreestuff():
    """Scrape CanadianFreeStuff.com for free samples and free products."""
    freebies = []
    urls = [
        ('https://www.canadianfreestuff.com/category/free-samples/', 'free-sample'),
        ('https://www.canadianfreestuff.com/category/free-products/', 'free-product'),
        ('https://www.canadianfreestuff.com/category/freebies/', 'freebie'),
    ]
    for page_url, category in urls:
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            # WordPress-style article listings
            for article in soup.select('article, .post, .type-post'):
                # Get title element
                title_el = (
                    article.find(class_=re.compile(r'entry-title|post-title')) or
                    article.find(['h2', 'h1', 'h3'])
                )
                if not title_el:
                    continue
                link_el = title_el.find('a', href=True) or article.find('a', href=True)
                if not link_el:
                    continue
                title = title_el.get_text(strip=True)
                href = link_el.get('href', '')
                if not href.startswith('http') or len(title) < 5:
                    continue
                # Try to get a description from excerpt
                desc_el = article.find(class_=re.compile(r'excerpt|summary|entry-summary'))
                desc = desc_el.get_text(strip=True)[:200] if desc_el else title
                freebies.append({
                    'id': make_freebie_id('cfs', title),
                    'name': title,
                    'description': desc,
                    'url': href,
                    'category': category,
                    'source': 'canadianfreestuff.com',
                    'expiry': '',
                    'status': 'active',
                    'added_date': date.today().isoformat(),
                    'provinces': ['ALL'],
                    'link_valid': None,
                    'link_checked': None,
                })
            logger.info(f"Scraped {len(freebies)} from canadianfreestuff.com ({category})")
        except Exception as e:
            logger.error(f"Error scraping {page_url}: {e}")
    return freebies


def scrape_smartcanucks():
    """Scrape SmartCanucks.ca for Canadian free stuff."""
    freebies = []
    urls = [
        'https://www.smartcanucks.ca/free-stuff-canada/',
        'https://www.smartcanucks.ca/category/free-samples/',
    ]
    for page_url in urls:
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for article in soup.select('article, .post, .type-post'):
                title_el = (
                    article.find(class_=re.compile(r'entry-title|post-title')) or
                    article.find(['h2', 'h1', 'h3'])
                )
                if not title_el:
                    continue
                link_el = title_el.find('a', href=True) or article.find('a', href=True)
                if not link_el:
                    continue
                title = title_el.get_text(strip=True)
                href = link_el.get('href', '')
                if not href.startswith('http') or len(title) < 5:
                    continue
                desc_el = article.find(class_=re.compile(r'excerpt|summary|entry-summary'))
                desc = desc_el.get_text(strip=True)[:200] if desc_el else title
                freebies.append({
                    'id': make_freebie_id('sc', title),
                    'name': title,
                    'description': desc,
                    'url': href,
                    'category': 'free-sample',
                    'source': 'smartcanucks.ca',
                    'expiry': '',
                    'status': 'active',
                    'added_date': date.today().isoformat(),
                    'provinces': ['ALL'],
                    'link_valid': None,
                    'link_checked': None,
                })
            logger.info(f"Scraped {len(freebies)} from smartcanucks.ca")
        except Exception as e:
            logger.error(f"Error scraping {page_url}: {e}")
    return freebies


def scrape_rfd_freebies():
    """Scrape RedFlagDeals freebies category."""
    freebies = []
    url = 'https://forums.redflagdeals.com/hot-deals-f9/?sk=topicdate&sd=d&tag=freebie'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        # RFD forum threads
        for item in soup.select('.topic_title_link, h3.topictitle, .topic_title'):
            link_el = item if item.name == 'a' else item.find('a', href=True)
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            href = link_el.get('href', '')
            if not href.startswith('http'):
                href = f"https://forums.redflagdeals.com{href}"
            freebies.append({
                'id': make_freebie_id('rfd', title),
                'name': title,
                'description': title,
                'url': href,
                'category': 'deal',
                'source': 'redflagdeals.com',
                'expiry': '',
                'status': 'active',
                'added_date': date.today().isoformat(),
                'provinces': ['ALL'],
                'link_valid': None,
                'link_checked': None,
            })
        logger.info(f"Scraped {len(freebies)} from RedFlagDeals freebies")
    except Exception as e:
        logger.error(f"Error scraping RFD freebies: {e}")
    return freebies


def expire_old_freebies(db):
    """Mark freebies past their expiry date as expired."""
    today = date.today().isoformat()
    expired = 0
    for freebie in db['freebies']:
        if freebie['status'] == 'active' and freebie.get('expiry') and freebie['expiry'] < today:
            freebie['status'] = 'expired'
            expired += 1
    return expired


def merge_freebies(db, new_freebies):
    """Merge new freebies into database without duplicates."""
    existing_ids = {f['id'] for f in db['freebies']}
    added = 0
    for freebie in new_freebies:
        if freebie['id'] not in existing_ids:
            db['freebies'].append(freebie)
            existing_ids.add(freebie['id'])
            added += 1
            logger.info(f"NEW FREEBIE: {freebie['name']}")
    return added


def run_freebie_scraper():
    """Main freebie scraper entry point."""
    logger.info("=== Freebie Scraper Starting ===")
    db = load_freebies_db()

    cfs = scrape_canadianfreestuff()
    sc = scrape_smartcanucks()
    rfd = scrape_rfd_freebies()

    all_new = cfs + sc + rfd
    added = merge_freebies(db, all_new)
    expired = expire_old_freebies(db)
    save_freebies_db(db)
    logger.info(f"=== Freebie Scraper Done: {added} new, {expired} expired ===")
    return db


if __name__ == '__main__':
    run_freebie_scraper()
