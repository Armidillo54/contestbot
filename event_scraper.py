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
    # Already ISO
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    # Month name formats: "April 19, 2026" or "Apr 19 2026"
    months = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    }
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


def is_upcoming(event_date_str, days_ahead=90):
    """Return True if event is today or within the next N days."""
    if not event_date_str:
        return True  # no date info → keep it
    try:
        ed = date.fromisoformat(event_date_str)
        today = date.today()
        return today <= ed <= today + timedelta(days=days_ahead)
    except ValueError:
        return True


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

def scrape_eventbrite():
    """Scrape Eventbrite Orillia events. Uses JSON-LD + HTML fallback."""
    events = []
    today = date.today().isoformat()
    urls = [
        'https://www.eventbrite.ca/d/canada--orillia/events/',
        'https://www.eventbrite.ca/d/canada--orillia/events--this-weekend/',
    ]
    seen_ids = set()
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue
        # Try JSON-LD first
        ld_events = extract_json_ld_events(html, 'Orillia, ON', 'eventbrite')
        for ev in ld_events:
            if ev['id'] not in seen_ids:
                seen_ids.add(ev['id'])
                events.append(ev)

        # HTML fallback: Eventbrite event cards
        if not ld_events:
            soup = BeautifulSoup(html, 'html.parser')
            for card in soup.select('[data-event-id], .eds-event-card, .search-event-card, article'):
                title_el = (card.find(class_=re.compile(r'title|heading|event-name', re.I))
                            or card.find(['h2', 'h3']))
                if not title_el:
                    continue
                name = title_el.get_text(strip=True)
                if not name or len(name) < 4:
                    continue
                link_el = card.find('a', href=True)
                ev_url = link_el['href'] if link_el else url
                if ev_url.startswith('/'):
                    ev_url = 'https://www.eventbrite.ca' + ev_url
                date_el = card.find(class_=re.compile(r'date|time', re.I)) or card.find('time')
                event_date = parse_iso_date(
                    date_el.get('datetime', date_el.get_text()) if date_el else ''
                )
                ev_id = make_event_id('eventbrite', name, event_date)
                if ev_id not in seen_ids:
                    seen_ids.add(ev_id)
                    events.append({
                        'id': ev_id,
                        'name': name,
                        'date': event_date,
                        'end_date': '',
                        'time': '',
                        'venue': 'Orillia, ON',
                        'category': categorize_event(name),
                        'price': 'See event',
                        'url': ev_url,
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
    urls = [
        'https://www.downtownorillia.ca/events/',
        'https://www.downtownorillia.ca/event_types/live-music/',
        'https://www.downtownorillia.ca/event_types/festivals/',
    ]
    seen_ids = set()
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue

        ld_events = extract_json_ld_events(html, 'Downtown Orillia, ON', 'downtownorillia')
        for ev in ld_events:
            if ev['id'] not in seen_ids:
                seen_ids.add(ev['id'])
                events.append(ev)
            continue

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
                date_el = (article.find(class_=re.compile(r'tribe-event-date|start-date|datetime', re.I))
                           or article.find('abbr', class_=re.compile(r'dtstart'))
                           or article.find('time'))
                date_text = (date_el.get('title') or date_el.get('datetime') or
                             date_el.get_text()) if date_el else ''
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
    # Remove past events (more than 1 day old with a known date)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    kept = []
    for ev in db.get('events', []):
        d = ev.get('date', '')
        if d and d < yesterday:
            continue  # drop past events
        kept.append(ev)
    db['events'] = kept
    db['total_events'] = len([e for e in db['events'] if e.get('status') == 'active'])
    with open(EVENTS_DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Events DB saved: {db['total_events']} active events")


def merge_events(db, new_events):
    existing_ids = {e['id'] for e in db['events']}
    added = 0
    for ev in new_events:
        if not ev.get('name') or not ev.get('url'):
            continue
        if ev['id'] not in existing_ids:
            db['events'].append(ev)
            existing_ids.add(ev['id'])
            added += 1
    return added


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_event_scraper():
    logger.info("=== Event Scraper Starting ===")
    db = load_events_db()

    all_new = []
    all_new.extend(scrape_eventbrite())
    all_new.extend(scrape_casino_rama())
    all_new.extend(scrape_downtown_orillia())
    all_new.extend(scrape_orillia_matters())
    all_new.extend(scrape_city_orillia())

    # Filter to upcoming events only before merging
    upcoming = [e for e in all_new if is_upcoming(e.get('date', ''), days_ahead=120)]
    added = merge_events(db, upcoming)
    save_events_db(db)
    logger.info(f"=== Event Scraper Done: {added} new events added ===")
    return db


if __name__ == '__main__':
    run_event_scraper()
