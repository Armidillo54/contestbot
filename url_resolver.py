#!/usr/bin/env python3
"""
URL Resolver — follows aggregator links and finds the actual contest/freebie entry URL.

Contest aggregator sites (ContestGirl, CanadianFreeStuff, SmartCanucks, etc.) link to
their own blog post or detail page, not the actual entry form. This module fetches each
aggregator page and extracts the real direct link.

Only runs on entries where url_resolved is not True and the stored URL is on a known
aggregator domain. Already-resolved entries are skipped on subsequent runs.
"""

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Domains that are aggregator pages — their URLs need to be followed
AGGREGATOR_DOMAINS = {
    'contestgirl.com',
    'canadianfreestuff.com',
    'smartcanucks.ca',
    'contestchef.ca',
    'redflagdeals.com',
    'forums.redflagdeals.com',
}

# These are never useful as contest/freebie destinations
SKIP_DOMAINS = {
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'youtube.com',
    'pinterest.com', 'tiktok.com', 'linkedin.com', 'reddit.com',
    'google.com', 'google.ca', 'apple.com', 'microsoft.com',
    'amazon.com', 'amazon.ca', 'doubleclick.net', 'googleads.g.doubleclick.net',
    'shareasale.com', 'viglink.com', 'skimlinks.com', 'pepperjam.com',
}

# Words in link text that strongly suggest "this is the entry link"
ENTER_KEYWORDS = [
    'enter now', 'enter here', 'enter contest', 'enter the contest',
    'enter to win', 'enter sweepstakes', 'enter the draw', 'enter the giveaway',
    'click here to enter', 'click to enter',
    'get your free', 'claim your free', 'claim freebie', 'get freebie',
    'request free', 'order free sample', 'get free sample', 'claim sample',
    'apply now', 'apply here', 'sign up here', 'register now',
    'visit site', 'go to contest', 'participate now',
    'click here for', 'click here to get',
]

# Words in the href that suggest the link is a contest/freebie entry page
ENTRY_HREF_KEYWORDS = [
    'enter', 'contest', 'sweepstakes', 'sweeps', 'giveaway', 'win',
    'free-sample', 'freesample', 'sample', 'freebie', 'offer',
]

# Path segments that are definitely not contest entry pages
SKIP_PATHS = {
    '/privacy', '/privacy-policy', '/terms', '/about', '/contact',
    '/advertise', '/sitemap', '/login', '/register', '/subscribe',
    '/newsletter', '/rss', '/feed', '/tag/', '/category/',
    '/author/', '/page/', '#', 'javascript:',
}


def _domain(url):
    try:
        return urlparse(url).netloc.lower().lstrip('www.')
    except Exception:
        return ''


def _is_skip_url(url):
    if not url or not url.startswith('http'):
        return True
    dom = _domain(url)
    if any(skip in dom for skip in SKIP_DOMAINS):
        return True
    path = urlparse(url).path.lower()
    if any(path.startswith(p) or p in path for p in SKIP_PATHS):
        return True
    return False


def _is_aggregator_url(url):
    dom = _domain(url)
    return any(agg in dom for agg in AGGREGATOR_DOMAINS)


def resolve_url(aggregator_url):
    """
    Fetch aggregator_url, find the real contest/freebie entry link.
    Returns (resolved_url: str, success: bool).
    On failure returns the original URL and False.
    """
    try:
        resp = requests.get(aggregator_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return aggregator_url, False
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Focus on the main content area to avoid sidebar/nav noise
        content = (
            soup.find('article') or
            soup.find(attrs={'class': re.compile(r'entry-content|post-content|article-content|post-body|td-post-content')}) or
            soup.find('main') or
            soup
        )

        aggregator_domain = _domain(aggregator_url)

        # --- Pass 1: link text matches an "enter" keyword ---
        for link in content.find_all('a', href=True):
            href = link.get('href', '').strip()
            text = link.get_text(separator=' ', strip=True).lower()
            if _is_skip_url(href) or _domain(href) == aggregator_domain:
                continue
            if any(kw in text for kw in ENTER_KEYWORDS):
                return href, True

        # --- Pass 2: href contains entry-related keyword ---
        for link in content.find_all('a', href=True):
            href = link.get('href', '').strip()
            if _is_skip_url(href) or _domain(href) == aggregator_domain:
                continue
            if any(kw in href.lower() for kw in ENTRY_HREF_KEYWORDS):
                return href, True

        # --- Pass 3: first clean external link in content area ---
        for link in content.find_all('a', href=True):
            href = link.get('href', '').strip()
            text = link.get_text(strip=True)
            if not href.startswith('http') or len(text) < 3:
                continue
            if _is_skip_url(href) or _domain(href) == aggregator_domain:
                continue
            return href, True

        return aggregator_url, False

    except Exception as e:
        logger.debug(f"Resolve failed for {aggregator_url}: {e}")
        return aggregator_url, False


def resolve_contests():
    """Resolve URLs for contest entries that still point to aggregator pages."""
    path = Path('contests_database.json')
    if not path.exists():
        return

    with open(path) as f:
        db = json.load(f)

    changed = 0
    for contest in db.get('contests', []):
        if contest.get('status') not in ('active', 'unverified'):
            continue
        if contest.get('url_resolved'):
            continue  # Already resolved on a previous run
        url = contest.get('url', '')
        if not url or not _is_aggregator_url(url):
            # Already a direct link — just mark it resolved
            contest['url_resolved'] = True
            continue

        logger.info(f"Resolving: {contest['name']} — {url}")
        resolved, success = resolve_url(url)
        contest['source_url'] = url          # keep original for reference
        contest['url'] = resolved
        contest['url_resolved'] = success
        if not success:
            logger.warning(f"  Could not resolve, keeping aggregator URL")
        else:
            logger.info(f"  → {resolved}")
        changed += 1
        time.sleep(0.5)  # Polite delay between requests

    if changed:
        with open(path, 'w') as f:
            json.dump(db, f, indent=2)
    logger.info(f"Contests: resolved {changed} URLs")


def resolve_freebies():
    """Resolve URLs for freebie entries that still point to aggregator pages."""
    path = Path('freebies_database.json')
    if not path.exists():
        return

    with open(path) as f:
        db = json.load(f)

    changed = 0
    for freebie in db.get('freebies', []):
        if freebie.get('status') != 'active':
            continue
        if freebie.get('url_resolved'):
            continue
        url = freebie.get('url', '')
        if not url or not _is_aggregator_url(url):
            freebie['url_resolved'] = True
            continue

        logger.info(f"Resolving freebie: {freebie['name']} — {url}")
        resolved, success = resolve_url(url)
        freebie['source_url'] = url
        freebie['url'] = resolved
        freebie['url_resolved'] = success
        if not success:
            logger.warning(f"  Could not resolve freebie URL, keeping aggregator URL")
        else:
            logger.info(f"  → {resolved}")
        changed += 1
        time.sleep(0.5)

    if changed:
        with open(path, 'w') as f:
            json.dump(db, f, indent=2)
    logger.info(f"Freebies: resolved {changed} URLs")


def run_url_resolver():
    """Main entry point — resolve both contests and freebies."""
    logger.info("=== URL Resolver Starting ===")
    resolve_contests()
    resolve_freebies()
    logger.info("=== URL Resolver Done ===")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    run_url_resolver()
