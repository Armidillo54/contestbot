#!/usr/bin/env python3
"""ContestBot Scraper - Scrapes Canadian NPN contest aggregators for Ontario-eligible contests."""

import json
import logging
import os
import re
from datetime import datetime, date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = Path('contests_database.json')
CONFIG_PATH = Path('config.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Keywords that indicate a contest explicitly excludes Ontario or requires purchase
ONTARIO_EXCLUDE_PATTERNS = [
    r'\bquebec\s+only\b', r'\bqc\s+only\b', r'\bbc\s+only\b',
    r'\balberta\s+only\b', r'\bab\s+only\b', r'\bmanitoba\s+only\b',
    r'\bsaskatchewan\s+only\b', r'\batlantic\s+only\b',
    r'\bpurchase\s+required\b', r'\bpurchase\s+necessary\b',
    r'\bno\s+ontario\b', r'\bexclude[sd]?\s+ontario\b',
    r'\bnot\s+(available|open|valid)\s+(in|to)\s+ontario\b',
    # Quebec-targeted listings from Canadian aggregators
    r'\b(open|exclusive|limited)\s+to\s+quebec\b',
    r'\bquebec\s+(residents?|only|exclusive)\b',
    r'\b(pour|au)\s+(le\s+)?qu[ée]bec\b',
    r'\bconcours\s+(pour|au)\b',
    r'\bcadeaux?\s+gratuits?\s+pour\b',
    # US-only contests that slip in via Canadian aggregators
    r'\b(us|u\.s\.|usa|united\s+states)\s+(only|residents?\s+only)\b',
    r'\b(open|limited)\s+to\s+(us|u\.s\.|usa|united\s+states)\s+residents?\b',
]

# Keywords that confirm Ontario or Canada-wide eligibility
ONTARIO_INCLUDE_PATTERNS = [
    r'\ball\s+canada\b', r'\bcanada[- ]wide\b', r'\bnational\b',
    r'\bontario\b', r'\bon\b',
    r'\bcanadiansonly\b', r'\bopen\s+to\s+canadians\b',
]


def load_config():
    """Load config from file, then overlay any env vars for personal fields."""
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    env_map = {
        'USER_FIRST_NAME': 'first_name',
        'USER_LAST_NAME': 'last_name',
        'USER_EMAIL': 'email',
        'USER_PHONE': 'phone',
        'USER_POSTAL_CODE': 'postal_code',
        'USER_DOB': 'date_of_birth',
    }
    for env_key, config_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config.setdefault('user', {})[config_key] = val
    return config


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


def is_ontario_eligible(text):
    """
    Return False if the text explicitly excludes Ontario or requires purchase.
    Return True if Ontario or all-Canada is mentioned, or no province restriction found.
    """
    lower = text.lower()
    for pattern in ONTARIO_EXCLUDE_PATTERNS:
        if re.search(pattern, lower):
            return False
    return True


def make_contest_id(prefix, name):
    slug = re.sub(r'[^a-z0-9]', '-', name.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')[:50]
    return f"{prefix}-{slug}" if prefix else slug


def scrape_contestgirl(config):
    """Scrape ContestGirl for Canadian NPN contests open to Ontario residents."""
    contests = []
    # d=daily, w=weekly, s=single entry, m=monthly; c=ca means Canada; b=nb = no blacklist
    urls = [
        ('https://www.contestgirl.com/contests/contests.pl?f=d&c=ca&b=nb&sort=p&ar=na&s=_', 'daily'),
        ('https://www.contestgirl.com/contests/contests.pl?f=w&c=ca&b=nb&sort=p&ar=na&s=_', 'weekly'),
        ('https://www.contestgirl.com/contests/contests.pl?f=s&c=ca&b=nb&sort=p&ar=na&s=_', 'single'),
        ('https://www.contestgirl.com/contests/contests.pl?f=m&c=ca&b=nb&sort=p&ar=na&s=_', 'monthly'),
    ]
    exclude_kw = config.get('filters', {}).get('exclude_keywords', [])

    for url, freq in urls:
        batch = []
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for row in soup.select('tr'):
                text = row.get_text(separator=' ', strip=True)
                link = row.find('a', href=True)
                if not link:
                    continue
                # Must have an end date to be considered valid
                end_match = re.search(r'End Date:\s*(\w+ \d+,\s*\d{4})', text)
                if not end_match:
                    continue
                try:
                    end_date = datetime.strptime(end_match.group(1).strip(), '%B %d, %Y').date()
                except ValueError:
                    continue
                if end_date < date.today():
                    continue
                # Ontario eligibility check
                if not is_ontario_eligible(text):
                    continue
                # User-defined exclude keywords
                if any(kw.lower() in text.lower() for kw in exclude_kw):
                    continue
                prize_match = re.search(r'\$([\d,]+)', text)
                prize_value = int(prize_match.group(1).replace(',', '')) if prize_match else 0
                name = link.text.strip()
                href = link['href']
                if not href.startswith('http'):
                    href = f"https://www.contestgirl.com{href}"
                batch.append({
                    'id': make_contest_id('cg', name),
                    'name': name,
                    'url': href,
                    'prize': text[:200],
                    'prize_value': prize_value,
                    'entry_method': 'online_form',
                    'entry_frequency': freq,
                    'npn': True,
                    'npn_note': 'Scraped from ContestGirl (NPN required)',
                    'restrictions': '',
                    'provinces': ['All Canada'],
                    'end_date': end_date.isoformat(),
                    'source': 'contestgirl.com',
                    'status': 'active',
                    'added_date': date.today().isoformat(),
                    'link_valid': None,
                    'link_checked': None,
                    'last_entered': None,
                })
            contests.extend(batch)
            logger.info(f"ContestGirl ({freq}): {len(batch)} contests")
        except Exception as e:
            logger.error(f"Error scraping ContestGirl {url}: {e}")
    return contests


def scrape_redflagdeals():
    """Scrape RedFlagDeals contest section."""
    contests = []
    url = 'https://www.redflagdeals.com/deals/category/contests/'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for item in soup.select('.list_item, .deal_container, article, .js-post-list-item'):
            link = item.find('a', href=True)
            if not link:
                continue
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            if not is_ontario_eligible(title):
                continue
            href = link['href']
            if not href.startswith('http'):
                href = f"https://www.redflagdeals.com{href}"
            contests.append({
                'id': make_contest_id('rfd', title),
                'name': title,
                'url': href,
                'prize': title,
                'prize_value': 0,
                'entry_method': 'online_form',
                'entry_frequency': 'single',
                'npn': True,
                'npn_note': 'From RedFlagDeals — verify NPN status',
                'restrictions': '',
                'provinces': ['All Canada'],
                'end_date': '',
                'source': 'redflagdeals.com',
                'status': 'active',
                'added_date': date.today().isoformat(),
                'link_valid': None,
                'link_checked': None,
                'last_entered': None,
            })
        logger.info(f"RedFlagDeals: {len(contests)} contests")
    except Exception as e:
        logger.error(f"Error scraping RedFlagDeals: {e}")
    return contests


def scrape_canadianfreestuff_contests():
    """Scrape CanadianFreeStuff.com contests category."""
    contests = []
    url = 'https://www.canadianfreestuff.com/category/contests/'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
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
            if not is_ontario_eligible(title):
                continue
            # Try to extract prize value from title/description
            prize_match = re.search(r'\$([\d,]+)', title)
            prize_value = int(prize_match.group(1).replace(',', '')) if prize_match else 0
            contests.append({
                'id': make_contest_id('cfs', title),
                'name': title,
                'url': href,
                'prize': title,
                'prize_value': prize_value,
                'entry_method': 'online_form',
                'entry_frequency': 'single',
                'npn': True,
                'npn_note': 'From CanadianFreeStuff.com',
                'restrictions': '',
                'provinces': ['All Canada'],
                'end_date': '',
                'source': 'canadianfreestuff.com',
                'status': 'active',
                'added_date': date.today().isoformat(),
                'link_valid': None,
                'link_checked': None,
                'last_entered': None,
            })
        logger.info(f"CanadianFreeStuff contests: {len(contests)}")
    except Exception as e:
        logger.error(f"Error scraping CanadianFreeStuff contests: {e}")
    return contests


def scrape_contestchef():
    """Scrape ContestChef.ca for Canadian contests."""
    contests = []
    url = 'https://www.contestchef.ca/'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        for article in soup.select('article, .contest-item, .post'):
            title_el = (
                article.find(class_=re.compile(r'entry-title|post-title|contest-title')) or
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
            if not is_ontario_eligible(title):
                continue
            text = article.get_text(separator=' ', strip=True)
            prize_match = re.search(r'\$([\d,]+)', text)
            prize_value = int(prize_match.group(1).replace(',', '')) if prize_match else 0
            end_match = re.search(r'(?:ends?|closes?|expir\w+)[\s:]+(\w+ \d+,?\s*\d{4})', text, re.IGNORECASE)
            end_date = ''
            if end_match:
                try:
                    end_date = datetime.strptime(
                        re.sub(r',?\s+', ' ', end_match.group(1)).strip(), '%B %d %Y'
                    ).date().isoformat()
                except ValueError:
                    pass
            contests.append({
                'id': make_contest_id('cc', title),
                'name': title,
                'url': href,
                'prize': text[:200],
                'prize_value': prize_value,
                'entry_method': 'online_form',
                'entry_frequency': 'single',
                'npn': True,
                'npn_note': 'From ContestChef.ca',
                'restrictions': '',
                'provinces': ['All Canada'],
                'end_date': end_date,
                'source': 'contestchef.ca',
                'status': 'active',
                'added_date': date.today().isoformat(),
                'link_valid': None,
                'link_checked': None,
                'last_entered': None,
            })
        logger.info(f"ContestChef: {len(contests)} contests")
    except Exception as e:
        logger.error(f"Error scraping ContestChef: {e}")
    return contests


def _make_entry(prefix, title, href, text, source, freq='single'):
    """Build a standard contest dict from scraped fields."""
    prize_match = re.search(r'\$([\d,]+)', text)
    prize_value = int(prize_match.group(1).replace(',', '')) if prize_match else 0
    end_match = re.search(
        r'(?:ends?|closes?|expir\w+|deadline)[\s:]+(\w+\.?\s+\d{1,2},?\s*\d{4})',
        text, re.IGNORECASE
    )
    end_date = ''
    if end_match:
        for fmt in ('%B %d %Y', '%b %d %Y', '%B. %d %Y'):
            try:
                parsed = datetime.strptime(
                    re.sub(r'[,.]', '', end_match.group(1)).strip(), fmt
                ).date()
                if parsed >= date.today():
                    end_date = parsed.isoformat()
                break
            except ValueError:
                continue
    return {
        'id': make_contest_id(prefix, title),
        'name': title,
        'url': href,
        'prize': text[:200],
        'prize_value': prize_value,
        'entry_method': 'online_form',
        'entry_frequency': freq,
        'npn': True,
        'npn_note': f'From {source}',
        'restrictions': '',
        'provinces': ['All Canada'],
        'end_date': end_date,
        'source': source,
        'status': 'active',
        'added_date': date.today().isoformat(),
        'link_valid': None,
        'link_checked': None,
        'last_entered': None,
    }


def scrape_wordpress_contests(urls, prefix, source, freq='single'):
    """
    Generic scraper for WordPress-style contest aggregator sites.
    Works for any site that lists contests as blog posts/articles.
    """
    contests = []
    seen_ids = set()
    url_list = [urls] if isinstance(urls, str) else urls
    for url in url_list:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            for article in soup.select(
                'article, .post, .type-post, .contest-item, .entry, '
                '.contest-listing, li.contest, .item'
            ):
                title_el = (
                    article.find(class_=re.compile(r'entry-title|post-title|contest-title|title')) or
                    article.find(['h2', 'h1', 'h3', 'h4'])
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
                if not is_ontario_eligible(title):
                    continue
                text = article.get_text(separator=' ', strip=True)
                entry = _make_entry(prefix, title, href, text, source, freq)
                if entry['id'] not in seen_ids:
                    seen_ids.add(entry['id'])
                    contests.append(entry)
            logger.info(f"{source} ({url.split('/')[2]}): {len(contests)} contests")
        except Exception as e:
            logger.error(f"Error scraping {source} ({url}): {e}")
    return contests


def scrape_contestcanada():
    """Scrape ContestCanada.net — updated daily since 2006."""
    return scrape_wordpress_contests(
        'https://www.contestcanada.net/', 'ccan', 'contestcanada.net'
    )


def scrape_contestscoop():
    """Scrape ContestScoop.com contest directory."""
    return scrape_wordpress_contests(
        ['https://www.contestscoop.com/', 'https://www.contestscoop.com/contests/'],
        'cscoop', 'contestscoop.com'
    )


def scrape_contestlibrary():
    """Scrape ContestLibrary.ca."""
    return scrape_wordpress_contests(
        'https://www.contestlibrary.ca/', 'clib', 'contestlibrary.ca'
    )


def scrape_secureawin():
    """Scrape SecureAWin.ca."""
    return scrape_wordpress_contests(
        'https://secureawin.ca/', 'saw', 'secureawin.ca'
    )


def scrape_curiousabout():
    """Scrape CuriousAboutCanadianContests.com."""
    return scrape_wordpress_contests(
        'https://curiousaboutcanadiancontests.com/', 'cacc', 'curiousaboutcanadiancontests.com'
    )


def scrape_wannawin():
    """Scrape WannaWin.ca."""
    return scrape_wordpress_contests(
        ['https://www.wannawin.ca/', 'https://www.wannawin.ca/contests/'],
        'ww', 'wannawin.ca'
    )


def merge_contests(db, new_contests):
    """Merge new contests into database, skipping duplicates by ID."""
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
    """Mark contests past their end date as expired."""
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

    cg = scrape_contestgirl(config)
    rfd = scrape_redflagdeals()
    cfs = scrape_canadianfreestuff_contests()
    cc = scrape_contestchef()
    ccan = scrape_contestcanada()
    cscoop = scrape_contestscoop()
    clib = scrape_contestlibrary()
    saw = scrape_secureawin()
    cacc = scrape_curiousabout()
    ww = scrape_wannawin()

    all_new = cg + rfd + cfs + cc + ccan + cscoop + clib + saw + cacc + ww
    added = merge_contests(db, all_new)
    expired = expire_old_contests(db)
    save_database(db)
    logger.info(f"=== Scraper Done: {added} new, {expired} expired ===")
    return db


if __name__ == '__main__':
    run_scraper()
