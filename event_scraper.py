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
    """Scrape Eventbrite events across Orillia + nearby (Barrie, Simcoe County)."""
    events = []
    today = date.today().isoformat()
    # Cover Orillia plus nearby hubs — Barrie and Simcoe County pull in concerts
    # that are reachable from Orillia for a family night out.
    urls = [
        'https://www.eventbrite.ca/d/canada--orillia/events/',
        'https://www.eventbrite.ca/d/canada--orillia/events--this-weekend/',
        'https://www.eventbrite.ca/d/canada--orillia/music--events/',
        'https://www.eventbrite.ca/d/canada--orillia/family-and-education--events/',
        'https://www.eventbrite.ca/d/canada--barrie/music--events/',
        'https://www.eventbrite.ca/d/canada--barrie/events--this-weekend/',
        'https://www.eventbrite.ca/d/canada--simcoe-county/events/',
    ]
    seen_ids = set()
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue
        # Default venue reflects the search scope
        if 'barrie' in url:
            default_venue = 'Barrie, ON'
        elif 'simcoe' in url:
            default_venue = 'Simcoe County, ON'
        else:
            default_venue = 'Orillia, ON'

        ld_events = extract_json_ld_events(html, default_venue, 'eventbrite')
        for ev in ld_events:
            ev['source'] = 'eventbrite.ca'
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
                        'venue': default_venue,
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


def _casino_rama_show_links(html, base_url):
    """Extract unique individual show/event page URLs from a Casino Rama listing page."""
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/'):
            href = 'https://www.casinorama.com' + href
        if 'casinorama.com' not in href:
            continue
        # Show/event detail pages typically live under /event/ or /entertainment/<slug>/
        if not re.search(r'/(event|entertainment|shows?)/[a-z0-9\-]+/?$', href, re.I):
            continue
        # Skip the top-level index pages themselves
        if href.rstrip('/').endswith(('/entertainment', '/events', '/shows')):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
    return links


def scrape_casino_rama():
    """Scrape upcoming shows from Casino Rama.

    Strategy: hit the entertainment index pages, harvest both JSON-LD (if
    present) and every individual show page URL, then fetch each show page to
    pick up JSON-LD dates/prices that the listing page usually hides.
    """
    events = []
    today = date.today().isoformat()
    seen_ids = set()

    listing_urls = [
        'https://www.casinorama.com/entertainment/',
        'https://www.casinorama.com/entertainment/concerts/',
        'https://www.casinorama.com/entertainment/shows/',
        'https://www.casinorama.com/events/',
    ]

    show_links = set()
    for url in listing_urls:
        html = fetch_page(url)
        if not html:
            continue

        # JSON-LD on the listing page
        for ev in extract_json_ld_events(html, 'Casino Rama Resort, Rama ON', 'casinorama'):
            ev['source'] = 'casinorama.com'
            if ev.get('price') in ('See event', ''):
                ev['price'] = 'Ticketed'
            if ev['id'] not in seen_ids:
                seen_ids.add(ev['id'])
                events.append(ev)

        # Collect detail-page links to follow
        show_links.update(_casino_rama_show_links(html, url))

        # HTML fallback on the listing page — pulls names/links when JSON-LD
        # is missing, and dates often live inline next to each show card
        soup = BeautifulSoup(html, 'html.parser')
        for article in soup.select(
            'article, .event-card, .wp-block-post, .show-listing, .entertainment-item'
        ):
            title_el = (article.find(class_=re.compile(r'title|heading', re.I))
                        or article.find(['h2', 'h3', 'h4']))
            if not title_el:
                continue
            name = title_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            link_el = title_el.find('a', href=True) or article.find('a', href=True)
            ev_url = link_el['href'] if link_el else url
            if ev_url.startswith('/'):
                ev_url = 'https://www.casinorama.com' + ev_url
            date_el = article.find(class_=re.compile(r'date|time', re.I)) or article.find('time')
            date_text = ''
            if date_el:
                date_text = (date_el.get('datetime') or date_el.get('title')
                             or date_el.get_text() or '')
            # Dates sometimes appear as free-floating text inside the card
            if not parse_iso_date(date_text):
                date_text = article.get_text(' ', strip=True)
            event_date = parse_iso_date(date_text)
            ev_id = make_event_id('rama', name, event_date)
            if ev_id in seen_ids:
                continue
            seen_ids.add(ev_id)
            events.append({
                'id': ev_id,
                'name': name,
                'date': event_date,
                'end_date': '',
                'time': '8:00 PM',
                'venue': 'Casino Rama Resort, Rama ON',
                'category': 'music',  # Casino Rama is overwhelmingly concerts
                'price': 'Ticketed',
                'url': ev_url,
                'description': name,
                'source': 'casinorama.com',
                'scraped_date': today,
                'status': 'active',
            })

    # Follow individual show pages to get proper dates via JSON-LD
    # Cap at 40 to be polite
    for detail_url in list(show_links)[:40]:
        html = fetch_page(detail_url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Casino Rama Resort, Rama ON', 'casinorama')
        for ev in ld:
            ev['source'] = 'casinorama.com'
            ev['url'] = detail_url  # canonical detail page
            if ev.get('price') in ('See event', ''):
                ev['price'] = 'Ticketed'
            if not ev.get('category') or ev['category'] == 'other':
                ev['category'] = 'music'
            # Rebuild id now that we may have a date
            ev['id'] = make_event_id('rama', ev['name'], ev.get('date', ''))
            if ev['id'] not in seen_ids:
                seen_ids.add(ev['id'])
                events.append(ev)
            else:
                # Backfill date onto existing record from the listing
                for existing in events:
                    if existing.get('url') == detail_url and not existing.get('date'):
                        existing['date'] = ev.get('date', '')
                        existing['end_date'] = ev.get('end_date', '')
                        break

    logger.info(f"Casino Rama: {len(events)} events ({len(show_links)} detail pages followed)")
    return events


def scrape_songkick_orillia():
    """Pull concert listings from Songkick's Orillia metro page."""
    events = []
    today = date.today().isoformat()
    seen = set()
    urls = [
        'https://www.songkick.com/metro-areas/30614-canada-barrie',  # Barrie metro includes Orillia
        'https://www.songkick.com/search?query=orillia',
    ]
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Orillia area, ON', 'songkick')
        for ev in ld:
            ev['source'] = 'songkick.com'
            ev['category'] = 'music'
            if ev.get('price') in ('See event', ''):
                ev['price'] = 'Ticketed'
            if ev['id'] not in seen:
                seen.add(ev['id'])
                events.append(ev)
    logger.info(f"Songkick: {len(events)} events")
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


def scrape_tribe_api(api_url, prefix, default_venue, source_name, default_price='See event'):
    """Generic scraper for WordPress sites running The Events Calendar (Tribe) REST API."""
    events = []
    today = date.today().isoformat()
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            logger.debug(f"{source_name} Tribe API HTTP {resp.status_code}")
            return events
        data = resp.json()
        for ev in data.get('events', []):
            name = ev.get('title', '').strip()
            if not name:
                continue
            ev_url = ev.get('url', '')
            event_date = parse_iso_date(ev.get('start_date', ''))
            end_date = parse_iso_date(ev.get('end_date', ''))
            venue_info = ev.get('venue', {}) or {}
            venue = venue_info.get('venue', default_venue) if venue_info else default_venue
            desc = ev.get('description', name) or name
            if isinstance(desc, str):
                desc = re.sub(r'<[^>]+>', ' ', desc).strip()[:200]
            # Price from cost field if available
            cost = (ev.get('cost') or '').strip()
            if cost.lower() in ('', 'free', '$0'):
                price = 'Free' if cost.lower() == 'free' else default_price
            else:
                price = cost
            events.append({
                'id': make_event_id(prefix, name, event_date),
                'name': name,
                'date': event_date,
                'end_date': end_date,
                'time': '',
                'venue': venue,
                'category': categorize_event(name, desc),
                'price': price,
                'url': ev_url,
                'description': desc,
                'source': source_name,
                'scraped_date': today,
                'status': 'active',
            })
    except Exception as e:
        logger.debug(f"{source_name} Tribe API failed: {e}")
    return events


def scrape_orillia_opera_house():
    """Scrape upcoming shows at the Orillia Opera House."""
    events = []
    # Tribe Events API (common for WordPress event sites)
    events = scrape_tribe_api(
        'https://orilliaoperahouse.ca/wp-json/tribe/events/v1/events?per_page=50&status=publish',
        'opera', 'Orillia Opera House, Orillia ON', 'orilliaoperahouse.ca', 'Ticketed',
    )
    if events:
        logger.info(f"Orillia Opera House (Tribe API): {len(events)} events")
        return events

    # HTML fallback — try JSON-LD on the events page
    today = date.today().isoformat()
    for url in ['https://orilliaoperahouse.ca/events/',
                'https://orilliaoperahouse.ca/whats-on/',
                'https://orilliaoperahouse.ca/']:
        html = fetch_page(url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Orillia Opera House, Orillia ON', 'orilliaoperahouse')
        for ev in ld:
            ev['source'] = 'orilliaoperahouse.ca'
            if ev.get('price') in ('See event', ''):
                ev['price'] = 'Ticketed'
            events.append(ev)
        if events:
            break
    logger.info(f"Orillia Opera House: {len(events)} events")
    return events


def scrape_orillia_library():
    """Scrape events (especially kids/family) from Orillia Public Library."""
    events = []
    today = date.today().isoformat()
    seen = set()

    # Try Tribe Events API first
    tribe_events = scrape_tribe_api(
        'https://www.orilliapubliclibrary.ca/wp-json/tribe/events/v1/events?per_page=60&status=publish',
        'opl', 'Orillia Public Library, Orillia ON', 'orilliapubliclibrary.ca', 'Free',
    )
    for ev in tribe_events:
        if ev['id'] not in seen:
            seen.add(ev['id'])
            events.append(ev)

    # HTML fallback: library events page
    if not events:
        for url in ['https://www.orilliapubliclibrary.ca/events/',
                    'https://www.orilliapubliclibrary.ca/programs/',
                    'https://orilliapubliclibrary.libnet.info/events']:
            html = fetch_page(url)
            if not html:
                continue
            ld = extract_json_ld_events(html, 'Orillia Public Library, Orillia ON', 'opl')
            for ev in ld:
                ev['source'] = 'orilliapubliclibrary.ca'
                ev['price'] = 'Free'
                if ev['id'] not in seen:
                    seen.add(ev['id'])
                    events.append(ev)

            # LibraryCalendar-style HTML fallback
            soup = BeautifulSoup(html, 'html.parser')
            for item in soup.select('article, .event, .event-item, li.evt, .calendar-event'):
                title_el = (item.find(class_=re.compile(r'title|heading|event-title', re.I))
                            or item.find(['h2', 'h3', 'h4']))
                if not title_el:
                    continue
                name = title_el.get_text(strip=True)
                if not name or len(name) < 3:
                    continue
                link_el = title_el.find('a', href=True) or item.find('a', href=True)
                ev_url = link_el['href'] if link_el else url
                if ev_url.startswith('/'):
                    ev_url = 'https://www.orilliapubliclibrary.ca' + ev_url
                date_el = (item.find(class_=re.compile(r'date|time|when|start', re.I))
                           or item.find('time'))
                date_text = ''
                if date_el:
                    date_text = (date_el.get('datetime') or date_el.get('title')
                                 or date_el.get_text() or '')
                event_date = parse_iso_date(date_text)
                ev_id = make_event_id('opl', name, event_date)
                if ev_id in seen:
                    continue
                seen.add(ev_id)
                events.append({
                    'id': ev_id,
                    'name': name,
                    'date': event_date,
                    'end_date': '',
                    'time': '',
                    'venue': 'Orillia Public Library, Orillia ON',
                    'category': categorize_event(name),
                    'price': 'Free',
                    'url': ev_url,
                    'description': name,
                    'source': 'orilliapubliclibrary.ca',
                    'scraped_date': today,
                    'status': 'active',
                })
    logger.info(f"Orillia Public Library: {len(events)} events")
    return events


def scrape_orillia_farmers_market():
    """Scrape Orillia Farmers' Market dates."""
    events = []
    today = date.today().isoformat()
    seen = set()

    # The Orillia Farmers' Market runs Saturdays in season — try their site first
    for url in ['https://orilliafarmersmarket.ca/',
                'https://orilliafarmersmarket.ca/market-days/',
                'https://www.downtownorillia.ca/event/farmers-market/']:
        html = fetch_page(url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Orillia Farmers\' Market, Orillia ON', 'ofm')
        for ev in ld:
            ev['source'] = 'orilliafarmersmarket.ca'
            ev['price'] = 'Free'
            ev['category'] = 'food'
            if ev['id'] not in seen:
                seen.add(ev['id'])
                events.append(ev)

    # Fallback: synthesize upcoming Saturday market dates for the season (May–Oct)
    if not events:
        today_d = date.today()
        # Find next Saturday
        days_until_sat = (5 - today_d.weekday()) % 7
        for i in range(20):  # up to 20 weeks out
            market_d = today_d + timedelta(days=days_until_sat + 7 * i)
            # Only during typical outdoor season (mid-May to late Oct)
            if market_d.month < 5 or market_d.month > 10:
                continue
            if market_d.month == 5 and market_d.day < 10:
                continue
            if market_d.month == 10 and market_d.day > 31:
                continue
            iso = market_d.isoformat()
            name = 'Orillia Farmers\' Market'
            events.append({
                'id': make_event_id('ofm', name, iso),
                'name': name,
                'date': iso,
                'end_date': '',
                'time': '8:30 AM – 1:00 PM',
                'venue': 'Centennial Park, Orillia ON',
                'category': 'food',
                'price': 'Free',
                'url': 'https://orilliafarmersmarket.ca/',
                'description': 'Local farmers, food producers, and artisans at Centennial Park.',
                'source': 'orilliafarmersmarket.ca',
                'scraped_date': today,
                'status': 'active',
            })
    logger.info(f"Orillia Farmers' Market: {len(events)} events")
    return events


def scrape_simcoe_events():
    """Scrape Simcoe.com events aggregator (charity runs, sports, community)."""
    events = []
    today = date.today().isoformat()
    seen = set()
    urls = [
        'https://www.simcoe.com/events/?loc=orillia',
        'https://www.simcoe.com/events/',
    ]
    for url in urls:
        html = fetch_page(url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Orillia area, ON', 'simcoe')
        for ev in ld:
            ev['source'] = 'simcoe.com'
            if ev['id'] not in seen:
                seen.add(ev['id'])
                events.append(ev)
    logger.info(f"Simcoe.com: {len(events)} events")
    return events


def scrape_race_roster():
    """Scrape local charity runs, bike rides, and races from Race Roster."""
    events = []
    today = date.today().isoformat()
    seen = set()
    # Race Roster search for Orillia-area events
    for url in ['https://raceroster.com/search?q=orillia',
                'https://raceroster.com/search?q=simcoe+county']:
        html = fetch_page(url)
        if not html:
            continue
        ld = extract_json_ld_events(html, 'Orillia area, ON', 'race')
        for ev in ld:
            ev['source'] = 'raceroster.com'
            ev['category'] = 'sports'
            if ev['id'] not in seen:
                seen.add(ev['id'])
                events.append(ev)
    logger.info(f"Race Roster: {len(events)} events")
    return events


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_events_db():
    if EVENTS_DB_PATH.exists():
        with open(EVENTS_DB_PATH) as f:
            return json.load(f)
    return {'events': [], 'last_updated': None, 'total_events': 0}


STALE_UNDATED_DAYS = 21


def save_events_db(db):
    today = date.today()
    db['last_updated'] = today.isoformat()
    today_iso = today.isoformat()
    stale_cutoff = (today - timedelta(days=STALE_UNDATED_DAYS)).isoformat()
    kept = []
    dropped_past = 0
    dropped_stale = 0
    for ev in db.get('events', []):
        d = ev.get('date', '')
        # Drop past events: any event whose date is strictly before today
        if d and d < today_iso:
            dropped_past += 1
            continue
        # Drop undated events that have been in the DB for a while (likely past)
        if not d:
            first_seen = ev.get('first_seen') or ev.get('scraped_date', '')
            if first_seen and first_seen < stale_cutoff:
                dropped_stale += 1
                continue
        kept.append(ev)
    db['events'] = kept
    db['total_events'] = len([e for e in db['events'] if e.get('status') == 'active'])
    with open(EVENTS_DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(
        f"Events DB saved: {db['total_events']} active "
        f"(dropped {dropped_past} past, {dropped_stale} stale undated)"
    )


def merge_events(db, new_events):
    existing_map = {e['id']: e for e in db['events']}
    today_iso = date.today().isoformat()
    added = 0
    for ev in new_events:
        if not ev.get('name') or not ev.get('url'):
            continue
        if ev['id'] not in existing_map:
            ev.setdefault('first_seen', today_iso)
            db['events'].append(ev)
            existing_map[ev['id']] = ev
            added += 1
        else:
            # Backfill date/end_date on existing entries that were scraped without dates
            existing = existing_map[ev['id']]
            existing.setdefault('first_seen', existing.get('scraped_date', today_iso))
            if ev.get('date') and not existing.get('date'):
                existing['date'] = ev['date']
            if ev.get('end_date') and not existing.get('end_date'):
                existing['end_date'] = ev['end_date']
            # Refresh last-seen timestamp
            existing['scraped_date'] = today_iso
    return added


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_event_scraper():
    logger.info("=== Event Scraper Starting ===")
    db = load_events_db()

    all_new = []
    scrapers = [
        ('Eventbrite', scrape_eventbrite),
        ('Casino Rama', scrape_casino_rama),
        ('Downtown Orillia', scrape_downtown_orillia),
        ('OrilliaMatters', scrape_orillia_matters),
        ('City of Orillia', scrape_city_orillia),
        ('Opera House', scrape_orillia_opera_house),
        ('Public Library', scrape_orillia_library),
        ('Farmers Market', scrape_orillia_farmers_market),
        ('Simcoe.com', scrape_simcoe_events),
        ('Race Roster', scrape_race_roster),
        ('Songkick', scrape_songkick_orillia),
    ]
    for label, fn in scrapers:
        try:
            all_new.extend(fn())
        except Exception as e:
            logger.error(f"{label} scraper failed: {e}")

    # Filter to upcoming events only before merging
    upcoming = [e for e in all_new if is_upcoming(e.get('date', ''), days_ahead=180)]
    added = merge_events(db, upcoming)
    save_events_db(db)
    logger.info(f"=== Event Scraper Done: {added} new events added ===")
    return db


if __name__ == '__main__':
    run_event_scraper()
