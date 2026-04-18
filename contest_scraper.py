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


# --- Sponsor extraction -----------------------------------------------------
# Aggregators don't identify the brand; we need to pull it from the linked URL
# domain or the description body so the dashboard shows "Kruger: Win $10,000"
# instead of a bare "Win $10,000".

AGGREGATOR_HOSTS = {
    'contestcanada.net', 'www.contestcanada.net',
    'canadianfreestuff.com', 'www.canadianfreestuff.com',
    'contestchef.ca', 'www.contestchef.ca',
    'contestscoop.com', 'www.contestscoop.com',
    'contestlibrary.ca', 'www.contestlibrary.ca',
    'secureawin.ca', 'www.secureawin.ca',
    'curiousaboutcanadiancontests.com', 'www.curiousaboutcanadiancontests.com',
    'wannawin.ca', 'www.wannawin.ca',
    'forums.redflagdeals.com', 'redflagdeals.com',
    'contestgirl.com', 'www.contestgirl.com',
    'gleam.io', 'woobox.com', 'rafflecopter.com',
    'matchpub.com', 'www.matchpub.com',
    'cmpgn.page', 'm.cmpgn.page', 'storybookcontest.cmpgn.page',
    'royaldraw.com', 'www.royaldraw.com',
    # News & generic sites that aren't really sponsors
    'globalnews.ca', 'www.globalnews.ca',
    'ctvnews.ca', 'www.ctvnews.ca', 'toronto.ctvnews.ca',
    'cbc.ca', 'www.cbc.ca',
    'googleusercontent.com',
}

# Host -> display brand name for cases where the slug alone isn't ideal
HOST_BRAND_OVERRIDES = {
    'ici.radio-canada.ca': 'Radio-Canada',
    'radio-canada.ca': 'Radio-Canada',
    'arm5.scotiabank.com': 'Scotiabank',
    'arm5f.scotiabank.com': 'Scotiabank',
    'thepersonal.com': 'The Personal (CFMWS)',
    'nbacontest.com': 'NBA',
    'picks.nba.com': 'NBA',
    'ca.bauer.com': 'Bauer',
    'sobeys.com': 'Sobeys / Coca-Cola',
    'montanas.ca': "Montana's / Bud Light",
    'mandarin.promo-manager.com': 'Mandarin Restaurant',
    'wd40.ca': 'WD-40',
    'repairdontreplace.wd40.ca': 'WD-40',
    'gustotv.com': 'Gusto TV',
    'mlb.com': 'MLB',
    'winwithgoldfish.ca': 'Goldfish',
    'expediacruises.ca': 'Expedia Cruises',
    'oldspicesupercontest.com': 'Old Spice',
    'lovefoodhatewaste.ca': 'Love Food Hate Waste',
    'avionrewards.com': 'Avion Rewards',
    'ikea.com': 'IKEA',
    'www.ikea.com': 'IKEA',
    'whatsyourtech.ca': "What's Your Tech",
    'spkmusiccontest.ca': 'Mondelez',
    'krugerproductsbrands.ca': 'Kruger Products',
    'cloud.email.krugerproductsbrands.ca': 'Kruger Products',
    'mykrugerproducts.ca': 'Kruger Products',
    'st-hubert.com': 'St. Hubert',
    'www.st-hubert.com': 'St. Hubert',
    'wheeloffortune.com': 'Wheel of Fortune',
    'www.wheeloffortune.com': 'Wheel of Fortune',
    'games.circlek.com': 'Circle K',
    'winwithdole.ca': 'Dole',
    'www.winwithdole.ca': 'Dole',
    'matchpub.com': '',
}

SPONSOR_DESCRIPTION_PATTERNS = [
    r'([A-Z][A-Za-z0-9&\.\-\']+(?:\s+[A-Z][A-Za-z0-9&\.\-\']+){0,3})\s+(?:has\s+a\s+giveaway|is\s+giving\s+away|has\s+an?\s+Earth\s+Month|has\s+collaborated|has\s+a\s+contest|presents)',
    r'(?:Enter\s+this\s+contest\s+from|contest\s+from)\s+([A-Z][A-Za-z0-9&\.\-\']+(?:\s+[A-Z][A-Za-z0-9&\.\-\']+){0,3})[.\s,]',
    r'participating\s+([A-Z][A-Za-z0-9&\.\-\']+(?:\s+[A-Z][A-Za-z0-9&\.\-\']+)?)\s+products?',
    r'@([a-z][a-z0-9]+?)canada\s+(?:has|is)',
]


def _brand_from_host(host):
    """Turn a host like 'games.circlek.com' into a tidy brand name."""
    if not host:
        return ''
    if host in HOST_BRAND_OVERRIDES:
        return HOST_BRAND_OVERRIDES[host]
    # Try parent-domain overrides
    parts = host.split('.')
    for i in range(len(parts) - 1):
        sub = '.'.join(parts[i:])
        if sub in HOST_BRAND_OVERRIDES:
            return HOST_BRAND_OVERRIDES[sub]
    # Strip TLD + "www" + promotional prefixes from host's core label
    core = host
    for suffix in ('.ca', '.com', '.net', '.org', '.co', '.io'):
        if core.endswith(suffix):
            core = core[:-len(suffix)]
            break
    label = core.split('.')[-1] or core
    label = re.sub(
        r'(?:winwith|win[-]?with[-]?|sweepstakes?|giveaway|promo|contest)',
        '', label, flags=re.I
    ).strip('-')
    if not label or len(label) < 3:
        return ''
    # Skip ugly slug-derived brand names (long mashed-together words)
    if '-' not in label and len(label) > 12:
        return ''
    # Skip news/generic single-word labels
    if label.lower() in ('news', 'media', 'shop', 'store', 'enter', 'win',
                          'free', 'prize', 'click', 'press', 'home', 'about',
                          'blog', 'page', 'site', 'event', 'play', 'app'):
        return ''
    # Skip slogan/verb-prefix URLs (drinkX, snackX, eatX, noXgame, etc.)
    if '-' not in label:
        for verb in ('drink', 'snack', 'eat', 'try', 'shop', 'visit',
                     'love', 'no', 'wit', 'taa', 'thefishin', 'thebear'):
            if label.lower().startswith(verb) and len(label) > len(verb) + 1:
                return ''
        # Skip labels ending in obvious filler suffixes
        for suf in ('contest', 'contests', 'rocks', 'radio', 'gear',
                     'represent', 'appliance'):
            if label.lower().endswith(suf) and label.lower() != suf:
                return ''
    return label.replace('-', ' ').title()


def extract_sponsor(description, url=''):
    """Return a sponsor/brand name for the contest, or ''."""
    # 1) URL domain (only if it isn't an aggregator / link-shortener)
    if url:
        m = re.match(r'https?://([^/]+)', url.lower())
        host = m.group(1) if m else ''
        if host and host not in AGGREGATOR_HOSTS:
            brand = _brand_from_host(host)
            if brand and len(brand) > 1:
                return brand
    # 2) Description patterns
    if description:
        for pat in SPONSOR_DESCRIPTION_PATTERNS:
            m = re.search(pat, description)
            if m:
                cand = m.group(1).strip(' ,.-')
                cand = re.sub(r'^(BIG|Great|Here|This|Ontarians|Nova\s+Scotians|Members)\b.*', '', cand).strip()
                if 1 < len(cand) < 40 and not cand.isdigit():
                    return cand
    return ''


def _apply_sponsor_prefix(title, sponsor):
    """Prepend sponsor to title if its key word isn't already there."""
    if not sponsor or not title:
        return title
    title_low = title.lower()
    if sponsor.lower() in title_low:
        return title
    # Compare with all separators stripped, so 'Kaltire' matches 'Kal Tire'.
    norm = lambda s: re.sub(r'[^a-z0-9]+', '', s.lower())
    if norm(sponsor) and norm(sponsor) in norm(title):
        return title
    # If any meaningful word from the sponsor already appears in the title,
    # don't prefix (avoids 'Kruger Products: Kruger Contest: ...').
    for word in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", sponsor):
        if word.lower() in ('the', 'and', 'inc', 'ltd', 'products', 'canada',
                             'corp', 'company', 'restaurant'):
            continue
        if word.lower() in title_low:
            return title
    return f"{sponsor}: {title.strip()}"


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
    sponsor = extract_sponsor(text, href)
    display_name = _apply_sponsor_prefix(title, sponsor)
    return {
        'id': make_contest_id(prefix, display_name),
        'name': display_name,
        'sponsor': sponsor,
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
                # Drop hashtag-only / emoji titles that aggregators pull from
                # Instagram (e.g. '#WIN #MileEndKicks #CINEPLEX'). They give
                # no useful prize info.
                stripped = re.sub(r'[\s#]+', ' ', title).strip()
                letters = re.sub(r'[^A-Za-z]', '', stripped)
                if len(letters) < 8 or title.lstrip().startswith('#'):
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


# --- Local Simcoe/Muskoka radio-station contest scrapers --------------------

LOCAL_AREA = 'Simcoe/Muskoka'


def scrape_local_radio(urls, prefix, source, freq='single'):
    """
    Scraper for Ontario radio station contest pages (WordPress-style sites).
    Tags results as Ontario-only + local_area Simcoe/Muskoka so the dashboard
    can surface them as 'local'.
    """
    contests = []
    seen_ids = set()
    url_list = [urls] if isinstance(urls, str) else urls
    for url in url_list:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            candidates = soup.select(
                'article, .post, .type-post, .contest, .contest-item, '
                '.entry, .card, li.contest, .item, .tribe-events-list-event-wrap'
            )
            for el in candidates:
                title_el = (
                    el.find(class_=re.compile(r'entry-title|post-title|contest-title|card-title|title')) or
                    el.find(['h2', 'h1', 'h3', 'h4'])
                )
                if not title_el:
                    continue
                link_el = title_el.find('a', href=True) or el.find('a', href=True)
                if not link_el:
                    continue
                title = title_el.get_text(strip=True)
                href = link_el.get('href', '')
                if href.startswith('/'):
                    base = re.match(r'https?://[^/]+', url).group(0)
                    href = base + href
                if not href.startswith('http') or len(title) < 5:
                    continue
                if not is_ontario_eligible(title):
                    continue
                low = title.lower()
                # Filter out navigation / generic page titles
                if any(w in low for w in ['privacy', 'contact', 'about us', 'terms', 'advertise', 'careers']):
                    continue
                text = el.get_text(separator=' ', strip=True)
                # Radio-station pages often mix contests with news articles; require
                # at least one contest-signal word in title or body.
                contest_signals = ('win', 'contest', 'giveaway', 'sweepstake',
                                   'prize', 'tickets', 'enter to')
                if not any(w in low for w in contest_signals) and \
                   not any(w in text.lower() for w in contest_signals):
                    continue
                entry = _make_entry(prefix, title, href, text, source, freq)
                entry['provinces'] = ['Ontario']
                entry['local_area'] = LOCAL_AREA
                entry['npn_note'] = f'Local contest from {source}'
                if entry['id'] not in seen_ids:
                    seen_ids.add(entry['id'])
                    contests.append(entry)
            logger.info(f"{source}: {len(contests)} local contests")
        except Exception as e:
            logger.error(f"Error scraping {source} ({url}): {e}")
    return contests


def scrape_kicx106():
    """KICX 106 FM — Simcoe County country station."""
    return scrape_local_radio(
        ['https://kicx.ca/contests/', 'https://kicx.ca/'],
        'kicx', 'KICX 106 (Orillia)'
    )


def scrape_rock95():
    """Rock 95 Barrie."""
    return scrape_local_radio(
        ['https://rock95.com/contests/', 'https://rock95.com/'],
        'rock95', 'Rock 95 (Barrie)'
    )


def scrape_koolfm():
    """Kool FM 107.5 — Barrie."""
    return scrape_local_radio(
        ['https://koolfm.com/contests/', 'https://koolfm.com/'],
        'kool', 'Kool FM (Barrie)'
    )


def scrape_country104():
    """Country 104 — Barrie/Simcoe."""
    return scrape_local_radio(
        ['https://country104.ca/contests/', 'https://country104.ca/'],
        'c104', 'Country 104 (Barrie)'
    )


def scrape_lakecountry887():
    """Lake Country 88.7 — Orillia/Lake Simcoe."""
    return scrape_local_radio(
        ['https://lakecountry887.com/contests/', 'https://lakecountry887.com/'],
        'lc887', 'Lake Country 88.7 (Orillia)'
    )


def scrape_bayshore():
    """Bayshore Broadcasting — Muskoka/Parry Sound stations.

    Only hit the /contests/ path; the homepage is a news aggregator whose
    articles were being picked up as 'contests' (e.g. crash reports).
    """
    return scrape_local_radio(
        ['https://www.bayshorebroadcasting.ca/contests/'],
        'bay', 'Bayshore Broadcasting (Muskoka)'
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

    # Local Simcoe / Muskoka sources
    kicx = scrape_kicx106()
    rock = scrape_rock95()
    kool = scrape_koolfm()
    c104 = scrape_country104()
    lc = scrape_lakecountry887()
    bay = scrape_bayshore()

    all_new = (cg + rfd + cfs + cc + ccan + cscoop + clib + saw + cacc + ww
               + kicx + rock + kool + c104 + lc + bay)
    added = merge_contests(db, all_new)
    expired = expire_old_contests(db)
    save_database(db)
    logger.info(f"=== Scraper Done: {added} new, {expired} expired ===")
    return db


if __name__ == '__main__':
    run_scraper()
