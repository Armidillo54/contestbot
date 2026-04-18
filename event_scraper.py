#!/usr/bin/env python3
"""
Scrapes local events in the Orillia, Ontario area.
Sources: Eventbrite, OrilliaMatters, Casino Rama, Downtown Orillia BIA,
         City of Orillia calendar.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

EVENTS_DB_PATH = Path('events_database.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# --- Local-area filter --------------------------------------------------------
# User wants ONLY events in Orillia, Oro-Medonte, Severn, Ramara.
# Barrie / Toronto / Lindsay / Georgina / Muskoka are too far.
LOCAL_PLACE_PATTERNS = [
    r'\borillia\b', r'\boro[\s\-]?medonte\b', r'\bsevern\s+(?:township|bridge|falls)?\b',
    r'\bsevern\b', r'\bramara\b', r'\brama\b',
    r'\bwashago\b', r'\bbrechin\b', r'\batherley\b',
    r'\blongford\b', r'\bcouchiching\b', r'\bcoldwater\b',
    r'\buptergrove\b', r'\bhawkestone\b', r'\bshanty\s+bay\b',
    r'\bmnjikaning\b', r'\bsimcoe\s+county\b',
]
BLOCKED_PLACE_PATTERNS = [
    r'\bbarrie\b', r'\btoronto\b', r'\boshawa\b', r'\blindsay\b',
    r'\bgeorgina\b', r'\binnisfil\b', r'\bminesing\b',
    r'\bmuskoka\b', r'\bgravenhurst\b', r'\bbracebridge\b',
    r'\bhuntsville\b', r'\bmidland\b', r'\bpenetang(?:uishene)?\b',
    r'\balliston\b', r'\bnewmarket\b', r'\baurora\b',
    r'\bmarkham\b', r'\bvaughan\b', r'\bmississauga\b', r'\bbrampton\b',
    r'\bottawa\b', r'\bmontreal\b', r'\bcollingwood\b',
    r'\bwasaga\b', r'\bbeaverton\b', r'\bsutton\b',
    r'\bkeswick\b', r'\bbradford\b', r'\bangus\b',
    r'\bborden\b', r'\bstayner\b', r'\bcreemore\b',
]
GARBAGE_TITLE_PATTERNS = [
    r'^\d+\.\s*',          # "1.March break" — Eventbrite category nav
    r'^test\s+event',
    r'^\s*online\s*$',
]
# Eventbrite directory paths that aren't actual events
EVENTBRITE_DIRECTORY_PATTERNS = [r'/d/[^/]+/', r'/c/[^/]+/']


def is_local_event(name, venue='', description='', url=''):
    """Return True only for events in Orillia/Oro-Medonte/Severn/Ramara."""
    text = f"{name} {venue} {description}".lower()
    for pat in GARBAGE_TITLE_PATTERNS:
        if re.search(pat, name, re.I):
            return False
    for pat in BLOCKED_PLACE_PATTERNS:
        if re.search(pat, text):
            return False
    for pat in LOCAL_PLACE_PATTERNS:
        if re.search(pat, text):
            return True
    # Also accept based on URL slug (some Eventbrite events name the venue in the slug)
    url_l = (url or '').lower()
    for pat in LOCAL_PLACE_PATTERNS:
        if re.search(pat, url_l):
            for bad in BLOCKED_PLACE_PATTERNS:
                if re.search(bad, url_l):
                    return False
            return True
    return False


CATEGORY_KEYWORDS = {
    'music':     ['concert', 'music', 'band', 'live music', 'jazz', 'rock', 'country',
                  'blues', 'folk', 'symphony', 'orchestra', 'choir', 'karaoke', 'open mic',
                  'dj', 'singer', 'mariposa', 'tribute', 'acoustic', 'performance'],
    'kids':      ['kids', 'children', 'family', 'youth', 'junior', 'toddler', 'teen',
                  'march break', 'storytime', 'playground', 'camp'],
    'festival':  ['festival', 'fair', 'carnival', 'expo', 'celebration', 'gala',
                  'pirate', 'scottish', 'highland', 'mardi gras', 'block party'],
    'sports':    ['sport', 'hockey', 'baseball', 'soccer', 'basketball', 'golf', 'run',
                  'race', 'tournament', 'game', 'match', 'skating', 'swim', 'rowing',
                  'canoe', 'triathlon', 'cycling', 'fitness', 'yoga'],
    'theatre':   ['theatre', 'theater', 'play', 'musical', 'opera', 'comedy', 'improv',
                  'dance', 'ballet', 'opera house', 'stage', 'clue', 'cabaret'],
    'food':      ['food', 'dining', 'restaurant', 'taste', 'wine', 'beer', 'brew',
                  'market', 'bbq', 'brunch', 'supper', 'delicious', 'culinary'],
    'parade':    ['parade', 'procession', 'santa claus', 'christmas parade'],
    'arts':      ['art', 'gallery', 'exhibit', 'museum', 'craft', 'studio', 'painting',
                  'photography', 'makers', 'vintage', 'artisan', 'crystal', 'healing'],
    'community': ['community', 'volunteer', 'charity', 'fundrais', 'networking',
                  'workshop', 'seminar', 'conference', 'rotary', 'legion', 'farmers'],
    'outdoor':   ['outdoor', 'nature', 'hike', 'trail', 'park', 'garden', 'boat',
                  'canoe', 'kayak', 'fishing', 'waterfront', 'beach'],
}


def categorize_event(name, description=''):
    text = (name + ' ' + description).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return 'other'


def make_event_id(prefix, title, event_date=''):
    slug = re.sub(r'[^a-z0-9]', '-', title.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')[:40]
    date_slug = event_date.replace('-', '')[:8] if event_date else ''
    return f"{prefix}-{date_slug}-{slug}" if date_slug else f"{prefix}-{slug}"


def fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        logger.debug(f"HTTP {resp.status_code} for {url}")
    except Exception as e:
        logger.debug(f"Fetch failed {url}: {e}")
    return None


def parse_iso_date(text):
    """Try to extract YYYY-MM-DD from a string. Returns '' on failure."""
    if not text:
        return ''
    # Already ISO (YYYY-MM-DD)
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    # Compact ISO: 20260712 or 20260712T100000 (Tribe Events Calendar title attr)
    m = re.match(r'(\d{4})(\d{2})(\d{2})(?:T\d+)?$', text.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    }
    # "April 19, 2026" or "Apr 19 2026"
    m = re.search(r'([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})', text)
    if m:
        mon = months.get(m.group(1).lower()[:3])
        if mon:
            return f"{m.group(3)}-{mon}-{m.group(2).zfill(2)}"
    # "19 April 2026"
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})', text)
    if m:
        mon = months.get(m.group(2).lower()[:3])
        if mon:
            return f"{m.group(3)}-{mon}-{m.group(1).zfill(2)}"
    return ''


def is_upcoming(event_date_str, days_ahead=90, allow_undated=False):
    """Return True if event is today or within the next N days.

    If allow_undated is False (default), missing dates are rejected — we'd rather
    drop a date-less listing than show a stale event with no date.
    """
    if not event_date_str:
        return allow_undated
    try:
        ed = date.fromisoformat(event_date_str)
        today = date.today()
        return today <= ed <= today + timedelta(days=days_ahead)
    except ValueError:
        return allow_undated


def extract_json_ld_events(html, default_venue='Orillia, ON', default_source=''):
    """Pull Event objects out of JSON-LD <script> blocks on the page."""
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    today = date.today().isoformat()

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            raw = script.string or ''
            data = json.loads(raw)
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            # Handle @graph wrapper
            if '@graph' in item:
                items += item['@graph']
                continue
            event_type = item.get('@type', '')
            if not isinstance(event_type, str):
                event_type = ' '.join(event_type)
            if 'event' not in event_type.lower():
                continue

            name = item.get('name', '').strip()
            if not name:
                continue
            url = item.get('url', '') or item.get('sameAs', '')
            start = item.get('startDate', '')
            end = item.get('endDate', '')
            event_date = parse_iso_date(str(start))
            end_date = parse_iso_date(str(end))

            # Location
            loc = item.get('location', {})
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            if isinstance(loc, dict):
                venue_name = loc.get('name', '')
                addr = loc.get('address', {})
                city = addr.get('addressLocality', '') if isinstance(addr, dict) else ''
                venue = f"{venue_name}, {city}".strip(', ') or default_venue
            else:
                venue = default_venue

            # Price
            offers = item.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price_raw = str(offers.get('price', '')) if isinstance(offers, dict) else ''
            if price_raw == '0':
                price = 'Free'
            elif price_raw:
                currency = offers.get('priceCurrency', '$') if isinstance(offers, dict) else '$'
                price = f"{currency}{price_raw}+"
            else:
                price = 'See event'

            desc = item.get('description', name)
            if isinstance(desc, str):
                desc = desc[:200]

            events.append({
                'id': make_event_id(default_source or 'evt', name, event_date),
                'name': name,
                'date': event_date,
                'end_date': end_date,
                'time': '',
                'venue': venue,
                'category': categorize_event(name, desc),
                'price': price,
                'url': url,
                'description': desc,
                'source': default_source,
                'scraped_date': today,
                'status': 'active',
            })
    return events


# ---------------------------------------------------------------------------
# Per-source scrapers
# ---------------------------------------------------------------------------

EVENTBRITE_EVENT_HREF = re.compile(
    r'^https?://(?:www\.)?eventbrite\.[a-z.]+/e/[^/?#]+-tickets-\d+', re.I
)


def scrape_eventbrite():
    """Scrape Eventbrite Orillia events.

    Strategy: collect every individual event URL (/e/{slug}-tickets-{id}) on the
    listing page along with the nearest title/date, then defer date filling to
    the per-page JSON-LD enrichment pass.
    """
    events = []
    today = date.today().isoformat()
    urls = [
        'https://www.eventbrite.ca/d/canada--orillia/events/',
        'https://www.eventbrite.ca/d/canada--orillia/events--this-weekend/',
    ]
    seen_urls = set()
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue

        # Listing-page JSON-LD usually only describes the search itself, but
        # individual event objects may still be present — keep them if so.
        for ev in extract_json_ld_events(html, 'Orillia, ON', 'eventbrite'):
            if ev.get('url') and EVENTBRITE_EVENT_HREF.match(ev['url']):
                if ev['url'] not in seen_urls:
                    seen_urls.add(ev['url'])
                    events.append(ev)

        soup = BeautifulSoup(html, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href'].strip().split('?')[0]
            if href.startswith('/'):
                href = 'https://www.eventbrite.ca' + href
            if not EVENTBRITE_EVENT_HREF.match(href):
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Title: link text, or aria-label, or the nearest heading
            name = (link.get('aria-label') or link.get_text(strip=True) or '').strip()
            if not name or len(name) < 4:
                card = link.find_parent(['article', 'section', 'div'])
                if card:
                    h = card.find(['h1', 'h2', 'h3'])
                    if h:
                        name = h.get_text(strip=True)
            if not name or len(name) < 4:
                continue

            # Try to grab a date hint from the surrounding card
            event_date = ''
            card = link.find_parent(['article', 'section', 'div'])
            if card:
                t = card.find('time')
                if t:
                    event_date = parse_iso_date(t.get('datetime') or t.get_text())
                if not event_date:
                    date_el = card.find(class_=re.compile(r'date|when', re.I))
                    if date_el:
                        event_date = parse_iso_date(date_el.get_text())

            events.append({
                'id': make_event_id('eventbrite', name, event_date),
                'name': name,
                'date': event_date,
                'end_date': '',
                'time': '',
                'venue': 'Orillia, ON',
                'category': categorize_event(name),
                'price': 'See event',
                'url': href,
                'description': name,
                'source': 'eventbrite.ca',
                'scraped_date': today,
                'status': 'active',
            })
    logger.info(f"Eventbrite: {len(events)} events")
    return events


def scrape_casino_rama():
    """Scrape upcoming shows from Casino Rama entertainment page."""
    events = []
    today = date.today().isoformat()
    html = fetch_page('https://www.casinorama.com/entertainment/')
    if not html:
        return events

    # Try JSON-LD first
    ld_events = extract_json_ld_events(html, 'Casino Rama Resort, Rama ON', 'casinorama')
    if ld_events:
        events.extend(ld_events)
        logger.info(f"Casino Rama (JSON-LD): {len(events)} events")
        return events

    # HTML fallback
    soup = BeautifulSoup(html, 'html.parser')
    for article in soup.select('article, .event-card, .wp-block-post, .show-listing'):
        title_el = (article.find(class_=re.compile(r'title|heading', re.I))
                    or article.find(['h2', 'h3', 'h4']))
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        link_el = title_el.find('a', href=True) or article.find('a', href=True)
        ev_url = link_el['href'] if link_el else 'https://www.casinorama.com/entertainment/'
        if ev_url.startswith('/'):
            ev_url = 'https://www.casinorama.com' + ev_url
        date_el = article.find(class_=re.compile(r'date|time', re.I)) or article.find('time')
        date_text = date_el.get_text(strip=True) if date_el else ''
        # Casino Rama embeds dates in the URL sometimes: /bnl-2026/ — try page text too
        event_date = parse_iso_date(date_text)
        events.append({
            'id': make_event_id('rama', name, event_date),
            'name': name,
            'date': event_date,
            'end_date': '',
            'time': '8:00 PM',
            'venue': 'Casino Rama Resort, Rama ON',
            'category': categorize_event(name),
            'price': 'Ticketed',
            'url': ev_url,
            'description': name,
            'source': 'casinorama.com',
            'scraped_date': today,
            'status': 'active',
        })
    logger.info(f"Casino Rama (HTML): {len(events)} events")
    return events


def scrape_downtown_orillia():
    """Scrape events from Downtown Orillia BIA."""
    events = []
    today = date.today().isoformat()
    seen_ids = set()

    # Try Tribe Events REST API first (gives clean structured data with proper dates)
    try:
        api_url = ('https://www.downtownorillia.ca/wp-json/tribe/events/v1/events'
                   '?per_page=50&status=publish')
        resp = requests.get(api_url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            for ev in data.get('events', []):
                name = ev.get('title', '').strip()
                if not name:
                    continue
                ev_url = ev.get('url', '')
                event_date = parse_iso_date(ev.get('start_date', ''))
                end_date = parse_iso_date(ev.get('end_date', ''))
                venue_info = ev.get('venue', {})
                venue = (venue_info.get('venue', 'Downtown Orillia, ON')
                         if venue_info else 'Downtown Orillia, ON')
                desc = ev.get('description', name)
                if isinstance(desc, str):
                    desc = re.sub(r'<[^>]+>', ' ', desc).strip()[:200]
                ev_id = make_event_id('bia', name, event_date)
                if ev_id not in seen_ids:
                    seen_ids.add(ev_id)
                    events.append({
                        'id': ev_id,
                        'name': name,
                        'date': event_date,
                        'end_date': end_date,
                        'time': '',
                        'venue': venue,
                        'category': categorize_event(name, desc),
                        'price': 'Free',
                        'url': ev_url,
                        'description': desc,
                        'source': 'downtownorillia.ca',
                        'scraped_date': today,
                        'status': 'active',
                    })
            if events:
                logger.info(f"Downtown Orillia (REST API): {len(events)} events")
                return events
    except Exception as e:
        logger.debug(f"Downtown Orillia REST API failed: {e}")

    # HTML fallback
    urls = [
        'https://www.downtownorillia.ca/events/',
        'https://www.downtownorillia.ca/event_types/live-music/',
        'https://www.downtownorillia.ca/event_types/festivals/',
    ]
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue

        ld_events = extract_json_ld_events(html, 'Downtown Orillia, ON', 'downtownorillia')
        for ev in ld_events:
            if ev['id'] not in seen_ids:
                seen_ids.add(ev['id'])
                events.append(ev)

        if not ld_events:
            soup = BeautifulSoup(html, 'html.parser')
            for article in soup.select('article, .tribe-event, .event-item, .type-tribe_events'):
                title_el = (article.find(class_=re.compile(r'title|heading|event-title', re.I))
                            or article.find(['h2', 'h3']))
                if not title_el:
                    continue
                name = title_el.get_text(strip=True)
                if not name or len(name) < 3:
                    continue
                link_el = title_el.find('a', href=True) or article.find('a', href=True)
                ev_url = link_el['href'] if link_el else url
                # Tribe Events Calendar uses abbr.tribe-events-start-datetime with
                # title="YYYY-MM-DD HH:MM:SS" or compact "20260712T100000"
                date_el = (
                    article.find(class_=re.compile(
                        r'tribe-events-start-datetime|tribe-event-date|start-date', re.I))
                    or article.find('abbr', class_=re.compile(r'tribe-events-abbr|dtstart', re.I))
                    or article.find(attrs={'data-start': True})
                    or article.find('time')
                )
                if date_el:
                    date_text = (date_el.get('title') or date_el.get('datetime')
                                 or date_el.get('data-start') or date_el.get_text())
                else:
                    date_text = ''
                event_date = parse_iso_date(date_text)
                ev_id = make_event_id('bia', name, event_date)
                if ev_id not in seen_ids:
                    seen_ids.add(ev_id)
                    events.append({
                        'id': ev_id,
                        'name': name,
                        'date': event_date,
                        'end_date': '',
                        'time': '',
                        'venue': 'Downtown Orillia, ON',
                        'category': categorize_event(name),
                        'price': 'Free',
                        'url': ev_url,
                        'description': name,
                        'source': 'downtownorillia.ca',
                        'scraped_date': today,
                        'status': 'active',
                    })
    logger.info(f"Downtown Orillia: {len(events)} events")
    return events


def scrape_orillia_matters():
    """Scrape events from OrilliaMatters events calendar."""
    events = []
    today = date.today().isoformat()
    html = fetch_page('https://www.orilliamatters.com/events')
    if not html:
        return events

    ld_events = extract_json_ld_events(html, 'Orillia, ON', 'orilliamatters')
    if ld_events:
        events.extend(ld_events)
        logger.info(f"OrilliaMatters (JSON-LD): {len(events)} events")
        return events

    soup = BeautifulSoup(html, 'html.parser')
    for article in soup.select('article, .event, .listing-item'):
        title_el = (article.find(class_=re.compile(r'title|heading', re.I))
                    or article.find(['h2', 'h3']))
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        link_el = title_el.find('a', href=True) or article.find('a', href=True)
        ev_url = link_el['href'] if link_el else 'https://www.orilliamatters.com/events'
        if ev_url.startswith('/'):
            ev_url = 'https://www.orilliamatters.com' + ev_url
        date_el = article.find(class_=re.compile(r'date|time|when', re.I)) or article.find('time')
        date_text = date_el.get_text(strip=True) if date_el else ''
        event_date = parse_iso_date(date_text)
        events.append({
            'id': make_event_id('om', name, event_date),
            'name': name,
            'date': event_date,
            'end_date': '',
            'time': '',
            'venue': 'Orillia, ON',
            'category': categorize_event(name),
            'price': 'See event',
            'url': ev_url,
            'description': name,
            'source': 'orilliamatters.com',
            'scraped_date': today,
            'status': 'active',
        })
    logger.info(f"OrilliaMatters (HTML): {len(events)} events")
    return events


def scrape_city_orillia():
    """Scrape City of Orillia events calendar."""
    events = []
    today = date.today().isoformat()
    html = fetch_page('https://calendar.orillia.ca/default/index?calendar=events&_mid_=4722')
    if not html:
        # fallback to main events page
        html = fetch_page('https://www.orillia.ca/en/events.aspx')
    if not html:
        return events

    ld_events = extract_json_ld_events(html, 'City of Orillia, ON', 'cityorillia')
    if ld_events:
        events.extend(ld_events)
        logger.info(f"City of Orillia (JSON-LD): {len(events)} events")
        return events

    soup = BeautifulSoup(html, 'html.parser')
    for item in soup.select('.event, .calendar-event, article, .row-event, li.event-item'):
        title_el = (item.find(class_=re.compile(r'title|name|heading', re.I))
                    or item.find(['h2', 'h3', 'h4', 'a']))
        if not title_el:
            continue
        name = title_el.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        link_el = item.find('a', href=True)
        ev_url = link_el['href'] if link_el else 'https://www.orillia.ca/en/events.aspx'
        if ev_url.startswith('/'):
            ev_url = 'https://www.orillia.ca' + ev_url
        date_el = item.find(class_=re.compile(r'date|time', re.I)) or item.find('time')
        date_text = date_el.get_text(strip=True) if date_el else ''
        event_date = parse_iso_date(date_text)
        events.append({
            'id': make_event_id('city', name, event_date),
            'name': name,
            'date': event_date,
            'end_date': '',
            'time': '',
            'venue': 'Orillia, ON',
            'category': categorize_event(name),
            'price': 'See event',
            'url': ev_url,
            'description': name,
            'source': 'orillia.ca',
            'scraped_date': today,
            'status': 'active',
        })
    logger.info(f"City of Orillia (HTML): {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_events_db():
    if EVENTS_DB_PATH.exists():
        with open(EVENTS_DB_PATH) as f:
            return json.load(f)
    return {'events': [], 'last_updated': None, 'total_events': 0}


def save_events_db(db):
    db['last_updated'] = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    kept = []
    for ev in db.get('events', []):
        d = ev.get('date', '')
        if d and d < yesterday:
            continue  # drop past events
        # Drop dateless entries scraped more than a week ago
        if not d and ev.get('scraped_date', '') < week_ago:
            continue
        kept.append(ev)
    db['events'] = kept
    db['total_events'] = len([e for e in db['events'] if e.get('status') == 'active'])
    with open(EVENTS_DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Events DB saved: {db['total_events']} active events")


def _extract_dates_from_html(html):
    """Pull (start_date, end_date) ISO strings from a single event page."""
    if not html:
        return '', ''

    # 1) JSON-LD Event objects (Eventbrite, Casino Rama, etc.)
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and '@graph' in item:
                items += item['@graph']
                continue
            if not isinstance(item, dict):
                continue
            t = item.get('@type', '')
            if isinstance(t, list):
                t = ' '.join(t)
            if 'event' not in str(t).lower():
                continue
            start = parse_iso_date(str(item.get('startDate', '')))
            end = parse_iso_date(str(item.get('endDate', '')))
            if start:
                return start, end

    # 2) Eventbrite serializes start time in window state JSON
    m = re.search(r'"start"\s*:\s*\{[^}]*?"local"\s*:\s*"([^"]+)"', html)
    if m:
        d = parse_iso_date(m.group(1))
        if d:
            return d, ''
    m = re.search(r'"startDate"\s*:\s*"([^"]+)"', html)
    if m:
        d = parse_iso_date(m.group(1))
        if d:
            return d, ''

    # 3) OpenGraph meta
    for prop in ('event:start_time', 'og:start_time'):
        m = re.search(rf'<meta[^>]+property=["\']?{re.escape(prop)}["\']?[^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            d = parse_iso_date(m.group(1))
            if d:
                return d, ''

    # 4) Tribe Events Calendar (Downtown Orillia)
    m = re.search(r'tribe-events-(?:start-date|abbr)[^"]*"[^>]*title="([^"]+)"', html)
    if m:
        d = parse_iso_date(m.group(1))
        if d:
            return d, ''

    # 5) Generic <time datetime="YYYY-MM-DD"> or visible date strings
    m = re.search(r'datetime="(\d{4}-\d{2}-\d{2}[^"]*)"', html)
    if m:
        d = parse_iso_date(m.group(1))
        if d:
            return d, ''
    m = re.search(r'\b([A-Z][a-z]{2,8}\s+\d{1,2},?\s+20\d{2})\b', html)
    if m:
        d = parse_iso_date(m.group(1))
        if d:
            return d, ''
    return '', ''


def enrich_event_dates(events, max_fetches=200):
    """For each event missing a date, fetch its URL and pull a real start date.

    Bounded by max_fetches to keep daily runtime reasonable. Skips obvious
    listing-page URLs (those without a per-event slug).
    """
    fetched = 0
    enriched = 0
    for ev in events:
        if ev.get('date'):
            continue
        url = ev.get('url', '')
        if not url:
            continue
        # Skip Eventbrite directory listings — they're not events
        if any(re.search(p, url) for p in EVENTBRITE_DIRECTORY_PATTERNS):
            continue
        if fetched >= max_fetches:
            break
        html = fetch_page(url)
        fetched += 1
        start, end = _extract_dates_from_html(html)
        if start:
            ev['date'] = start
            if end:
                ev['end_date'] = end
            # Recompute id now that we have a real date
            prefix = ev['id'].split('-', 1)[0]
            ev['id'] = make_event_id(prefix, ev['name'], start)
            enriched += 1
    logger.info(f"Date enrichment: fetched {fetched} pages, filled {enriched} dates")


def merge_events(db, new_events):
    existing_map = {e['id']: e for e in db['events']}
    added = 0
    for ev in new_events:
        if not ev.get('name') or not ev.get('url'):
            continue
        if ev['id'] not in existing_map:
            db['events'].append(ev)
            existing_map[ev['id']] = ev
            added += 1
        else:
            # Backfill date/end_date on existing entries that were scraped without dates
            existing = existing_map[ev['id']]
            if ev.get('date') and not existing.get('date'):
                existing['date'] = ev['date']
            if ev.get('end_date') and not existing.get('end_date'):
                existing['end_date'] = ev['end_date']
    return added


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def prune_existing_events(db):
    """One-time cleanup: drop entries that don't pass the local-area filter,
    Eventbrite directory URLs, garbage titles, and dateless entries older than
    a week.
    """
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    kept = []
    dropped = 0
    for ev in db.get('events', []):
        url = ev.get('url', '')
        # Drop Eventbrite directory / category URLs (not real events)
        if any(re.search(p, url) for p in EVENTBRITE_DIRECTORY_PATTERNS):
            dropped += 1
            continue
        # Drop non-local
        if not is_local_event(ev.get('name', ''), ev.get('venue', ''),
                              ev.get('description', ''), url):
            dropped += 1
            continue
        # Drop dateless entries scraped more than a week ago — enrichment failed
        if not ev.get('date') and ev.get('scraped_date', today) < week_ago:
            dropped += 1
            continue
        kept.append(ev)
    db['events'] = kept
    if dropped:
        logger.info(f"Pruned {dropped} non-local / garbage / stale events")
    return dropped


def run_event_scraper():
    logger.info("=== Event Scraper Starting ===")
    db = load_events_db()

    # Clean out non-local + garbage entries from prior runs
    prune_existing_events(db)

    all_new = []
    all_new.extend(scrape_eventbrite())
    all_new.extend(scrape_casino_rama())
    all_new.extend(scrape_downtown_orillia())
    all_new.extend(scrape_orillia_matters())
    all_new.extend(scrape_city_orillia())

    # Apply local-area filter before any further work
    before = len(all_new)
    all_new = [e for e in all_new
               if is_local_event(e.get('name', ''), e.get('venue', ''),
                                 e.get('description', ''), e.get('url', ''))]
    logger.info(f"Local filter: {before} -> {len(all_new)} events kept")

    # Fill in missing dates by fetching individual event pages
    enrich_event_dates(all_new)

    # Also backfill dates on entries already in the DB that still have none
    stale = [e for e in db.get('events', []) if not e.get('date') and e.get('url')]
    if stale:
        enrich_event_dates(stale)

    # Filter to upcoming events only — drop dateless entries (we tried to enrich)
    upcoming = [e for e in all_new
                if is_upcoming(e.get('date', ''), days_ahead=120, allow_undated=False)]
    logger.info(f"Date filter: {len(all_new)} -> {len(upcoming)} upcoming events")
    added = merge_events(db, upcoming)
    save_events_db(db)
    logger.info(f"=== Event Scraper Done: {added} new events added ===")
    return db


if __name__ == '__main__':
    run_event_scraper()
