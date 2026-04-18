#!/usr/bin/env python3
"""Scrapes Canadian freebie sources for real mailed samples and product trials.

Strategy:
- Direct sample-program scrapers (SampleSource, Peekage, Home Tester Club,
  Social Nature, Butterly) are TRUSTED — entries they surface are kept unless
  they clearly match a blocked category.
- Aggregator scrapers (CanadianFreeStuff, SmartCanucks, RFD) are noisy, so
  entries from those sources must pass is_real_freebie() — a keyword filter
  that demands mailed-sample / trial signals and blocks coupons, rebates,
  pet/baby, articles, and birthday deals.
"""

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
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# Category names produced by the old scraper before categorize() was added
LEGACY_CATS = {'free-sample', 'free-product', 'freebie', 'deal'}

# Direct sample-program sources — their entries bypass the keyword-gate filter
TRUSTED_SOURCES = {
    'samplesource.com', 'peekage.ca', 'peekage.com', 'hometesterclub.ca',
    'hometesterclub.com', 'socialnature.com', 'butterly.ca',
    'pggoodeveryday.ca', 'shoppersvoice.ca', 'smiley360.com',
}

# Keywords that mean this entry is NOT a real mailed-sample freebie
BLOCKED_KEYWORDS = [
    # Coupons and discounts
    'coupon', 'save $', '% off', 'percent off', 'rebate', 'bogo',
    'buy one get', 'discount', 'cashback', 'cash back',
    # Birthday / reward club perks (not mailed)
    'birthday', 'birthday freebie', 'birthday offer',
    # Articles, listicles, guides
    'list of', 'best 6', 'best 7', 'best 8', 'best 10', 'best 11',
    'best 12', 'best 15', 'best 20', 'how to', 'tips for', 'guide to',
    'ways to', 'roundup', 'what to do', 'things to',
    # Pet — explicit user exclusion
    ' pet ', 'dog food', 'dog treat', 'cat food', 'cat treat', 'kibble',
    'litter', 'purina', 'pedigree', 'whiskas', 'iams', 'hartz',
    'temptations', 'friskies', 'pounce', 'meow mix', 'paw ',
    # Baby — explicit user exclusion
    'baby', 'infant', 'toddler', 'diaper', 'formula', 'pampers', 'huggies',
    'enfamil', 'similac', 'nursery', 'newborn', 'pull-up', 'pull ups',
    'pull-ups', 'pullups', 'baby registry', 'baby shower',
    # Subscription boxes that aren't really free
    'first box free', 'first month free', 'trial subscription',
]

# Phrases that confirm a real mailed-sample or free-product offer.
# Aggregator entries must contain at least one.
REAL_FREEBIE_SIGNALS = [
    'mailed', 'mail-out', 'mail out', 'by mail', 'ships to',
    'free sample', 'free samples', 'free product', 'free trial',
    'full size', 'full-size', 'claim sample', 'request sample',
    'request a sample', 'order sample', 'get a sample', 'try for free',
    'free-of-charge', 'no purchase', 'no cost',
    'trial offer', 'apply for free', 'apply for a free', 'apply for',
    'starter kit', 'sample kit', 'sample pack',
    # Name-drops of trusted sample programs in aggregator titles
    'samplesource', 'sample source', 'social nature', 'home tester club',
    'peekage', 'butterly', 'pg good everyday', 'smiley360',
    "shopper's voice",
]

# Updated category keywords — pets and baby removed per user request
CATEGORY_KEYWORDS = {
    'food':      ['food', 'grocery', 'snack', 'drink', 'coffee', 'tea', 'meal', 'juice',
                  'fruit', 'vegetable', 'chips', 'protein', 'bar', 'cereal', 'sauce',
                  'spice', 'seaweed', 'chocolate', 'candy'],
    'restaurant':['restaurant', 'pizza', 'burger', 'cafe', 'tim horton', 'mcdonald',
                  'subway', 'wendy', 'a&w', 'kfc', 'dairy queen', 'starbucks', 'taco',
                  'sushi', 'dine'],
    'beauty':    ['shampoo', 'conditioner', 'skincare', 'skin care', 'makeup', 'beauty',
                  'cosmetic', 'lotion', 'soap', 'deodorant', 'perfume', 'cream', 'serum',
                  'moisturizer', 'mascara', 'foundation', 'lipstick', 'hair care',
                  'haircare', 'fragrance', 'nail'],
    'household': ['household', 'cleaning', 'detergent', 'cleaner', 'laundry', 'dish',
                  'toilet', 'paper towel', 'garbage bag', 'storage', 'air freshener',
                  'fabric softener', 'denture'],
    'clothing':  ['clothing', 'shirt', 'pants', 'dress', 'jacket', 'fashion', 'apparel',
                  'shoes', 'boots', 'socks', 'underwear', 'jeans', 'sweater', 'coat'],
    'health':    ['vitamin', 'supplement', 'health', 'medical', 'pharmacy', 'medicine',
                  'probiotic', 'omega', 'mineral', 'wellness', 'first aid', 'contact lens',
                  'eye drop'],
}


def is_real_freebie(title, description='', source=''):
    """Return False if entry is clearly a coupon/pet/baby/article, etc."""
    text = f"{title} {description}".lower()
    padded = f" {text} "
    for bad in BLOCKED_KEYWORDS:
        if bad in padded:
            return False
    src = (source or '').lower()
    if any(trusted in src for trusted in TRUSTED_SOURCES):
        return True
    return any(sig in text for sig in REAL_FREEBIE_SIGNALS)


def categorize(name, description=''):
    text = (name + ' ' + description).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return 'other'


def make_freebie_id(prefix, title):
    slug = re.sub(r'[^a-z0-9]', '-', title.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')[:50]
    return f"{prefix}-{slug}"


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


def _fetch(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            return resp.text
        logger.debug(f"HTTP {resp.status_code} for {url}")
    except Exception as e:
        logger.debug(f"Fetch failed {url}: {e}")
    return None


def _build_freebie(prefix, title, href, desc, source):
    return {
        'id': make_freebie_id(prefix, title),
        'name': title,
        'description': desc[:200] if desc else title,
        'url': href,
        'category': categorize(title, desc),
        'source': source,
        'expiry': '',
        'status': 'active',
        'added_date': date.today().isoformat(),
        'provinces': ['ALL'],
        'link_valid': None,
        'link_checked': None,
    }


def _scrape_wordpress(urls, prefix, source):
    """Generic WordPress-style article-list scraper."""
    found = []
    seen = set()
    for url in (urls if isinstance(urls, list) else [urls]):
        html = _fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for article in soup.select('article, .post, .type-post, .sample, .product'):
            title_el = (article.find(class_=re.compile(r'entry-title|post-title|product-title|sample-title'))
                        or article.find(['h2', 'h1', 'h3']))
            if not title_el:
                continue
            link_el = title_el.find('a', href=True) or article.find('a', href=True)
            if not link_el:
                continue
            title = title_el.get_text(strip=True)
            href = link_el.get('href', '').strip()
            if not href.startswith('http') or len(title) < 5:
                continue
            desc_el = article.find(class_=re.compile(r'excerpt|summary|entry-summary|description'))
            desc = desc_el.get_text(strip=True) if desc_el else title
            if not is_real_freebie(title, desc, source):
                continue
            fb = _build_freebie(prefix, title, href, desc, source)
            if fb['id'] not in seen:
                seen.add(fb['id'])
                found.append(fb)
    logger.info(f"{source}: {len(found)} real freebies")
    return found


# ---------------------------------------------------------------------------
# Direct sample-program scrapers (TRUSTED)
# ---------------------------------------------------------------------------

def scrape_samplesource():
    """SampleSource.com — bi-annual Canadian sample box program."""
    found = []
    html = _fetch('https://www.samplesource.com/')
    if not html:
        return found
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(separator=' ', strip=True).lower()
    live = any(k in text for k in ['register', 'sign up', 'sign-up', 'signup now',
                                    'samples are live', 'get samples'])
    if live:
        found.append(_build_freebie(
            'ss', 'SampleSource Canada — Free Sample Box Registration',
            'https://www.samplesource.com/',
            'Free box of full-sized sample products mailed across Canada '
            '(bi-annual program).',
            'samplesource.com',
        ))
    logger.info(f"samplesource.com: {len(found)} real freebies")
    return found


def scrape_peekage():
    return _scrape_wordpress(
        ['https://peekage.ca/', 'https://peekage.ca/products/',
         'https://peekage.ca/blog/'],
        'pk', 'peekage.ca',
    )


def scrape_hometesterclub():
    return _scrape_wordpress(
        ['https://www.hometesterclub.com/ca/en/campaigns',
         'https://www.hometesterclub.com/ca/en/products'],
        'htc', 'hometesterclub.com',
    )


def scrape_socialnature():
    return _scrape_wordpress(
        ['https://www.socialnature.com/products',
         'https://www.socialnature.com/missions'],
        'sn', 'socialnature.com',
    )


def scrape_butterly():
    return _scrape_wordpress(
        ['https://butterly.ca/', 'https://butterly.ca/free-samples/',
         'https://butterly.ca/category/free-samples/'],
        'btr', 'butterly.ca',
    )


# ---------------------------------------------------------------------------
# Aggregator scrapers (NOISY — must pass is_real_freebie filter)
# ---------------------------------------------------------------------------

def scrape_canadianfreestuff():
    return _scrape_wordpress(
        ['https://www.canadianfreestuff.com/category/free-samples/',
         'https://www.canadianfreestuff.com/category/free-products/',
         'https://www.canadianfreestuff.com/category/freebies/'],
        'cfs', 'canadianfreestuff.com',
    )


def scrape_smartcanucks():
    return _scrape_wordpress(
        ['https://www.smartcanucks.ca/free-stuff-canada/',
         'https://www.smartcanucks.ca/category/free-samples/'],
        'sc', 'smartcanucks.ca',
    )


def scrape_rfd_freebies():
    freebies = []
    url = 'https://forums.redflagdeals.com/hot-deals-f9/?sk=topicdate&sd=d&tag=freebie'
    html = _fetch(url)
    if not html:
        return freebies
    soup = BeautifulSoup(html, 'html.parser')
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
        if not is_real_freebie(title, '', 'redflagdeals.com'):
            continue
        freebies.append(_build_freebie('rfd', title, href, title, 'redflagdeals.com'))
    logger.info(f"redflagdeals.com: {len(freebies)} real freebies")
    return freebies


# ---------------------------------------------------------------------------
# DB maintenance
# ---------------------------------------------------------------------------

def expire_old_freebies(db):
    today = date.today().isoformat()
    expired = 0
    for freebie in db['freebies']:
        if freebie['status'] == 'active' and freebie.get('expiry') and freebie['expiry'] < today:
            freebie['status'] = 'expired'
            expired += 1
    return expired


def prune_non_real_freebies(db):
    """Drop entries that no longer pass the real-freebie filter."""
    removed = 0
    kept = []
    for f in db.get('freebies', []):
        if is_real_freebie(f.get('name', ''), f.get('description', ''),
                           f.get('source', '')):
            kept.append(f)
        else:
            removed += 1
    db['freebies'] = kept
    if removed:
        logger.info(f"Pruned {removed} entries that no longer match real-freebie rules")
    return removed


def recategorize_existing(db):
    """Re-apply keyword categorization; pets/baby entries get dropped earlier."""
    updated = 0
    for freebie in db.get('freebies', []):
        old = freebie.get('category', '')
        if old in LEGACY_CATS or old in ('pets', 'baby') or (old not in CATEGORY_KEYWORDS and old != 'other'):
            freebie['category'] = categorize(
                freebie.get('name', ''), freebie.get('description', '')
            )
            updated += 1
    if updated:
        logger.info(f"Recategorized {updated} freebies")
    return updated


def merge_freebies(db, new_freebies):
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
    logger.info("=== Freebie Scraper Starting ===")
    db = load_freebies_db()

    prune_non_real_freebies(db)
    recategorize_existing(db)

    all_new = []
    all_new += scrape_samplesource()
    all_new += scrape_peekage()
    all_new += scrape_hometesterclub()
    all_new += scrape_socialnature()
    all_new += scrape_butterly()
    all_new += scrape_canadianfreestuff()
    all_new += scrape_smartcanucks()
    all_new += scrape_rfd_freebies()

    added = merge_freebies(db, all_new)
    expired = expire_old_freebies(db)
    save_freebies_db(db)
    logger.info(f"=== Freebie Scraper Done: {added} new, {expired} expired ===")
    return db


if __name__ == '__main__':
    run_freebie_scraper()
