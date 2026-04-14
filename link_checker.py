#!/usr/bin/env python3
"""Server-side link validator. Checks all active contest and freebie URLs for dead links."""

import json
import logging
import time
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
TIMEOUT = 12
# How many days before re-checking an already-validated link
RECHECK_DAYS = 3


def check_url(url):
    """
    Return True if the URL is reachable, False if definitively dead (404/410).
    Returns True on ambiguous errors (timeout, SSL, connection) to avoid false negatives.
    """
    try:
        resp = requests.head(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code in (404, 410):
            return False
        if resp.status_code == 405:
            # Server doesn't allow HEAD — fall back to a streaming GET
            resp = requests.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, stream=True
            )
            resp.close()
            return resp.status_code not in (404, 410)
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        # Timeout, SSL error, etc. — assume OK rather than falsely flag it
        return True


def should_recheck(entry):
    """Return True if this entry needs its link re-checked today."""
    last = entry.get('link_checked')
    if not last:
        return True
    try:
        days_since = (date.today() - date.fromisoformat(last)).days
        return days_since >= RECHECK_DAYS
    except ValueError:
        return True


def validate_contests():
    """Check all active contest URLs. Mark 404s as dead_link."""
    path = Path('contests_database.json')
    if not path.exists():
        return
    with open(path) as f:
        db = json.load(f)

    today = date.today().isoformat()
    checked = marked_dead = 0

    for contest in db.get('contests', []):
        if contest.get('status') not in ('active', 'unverified'):
            continue
        if not should_recheck(contest):
            continue
        url = contest.get('url', '')
        if not url:
            continue
        is_valid = check_url(url)
        contest['link_valid'] = is_valid
        contest['link_checked'] = today
        if not is_valid:
            contest['status'] = 'dead_link'
            marked_dead += 1
            logger.info(f"DEAD LINK (contest): {contest['name']} -> {url}")
        checked += 1
        time.sleep(0.3)  # Be polite — 300 ms between requests

    with open(path, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Contests: checked {checked} links, marked {marked_dead} dead")


def validate_freebies():
    """Check all active freebie URLs. Mark 404s as dead_link."""
    path = Path('freebies_database.json')
    if not path.exists():
        return
    with open(path) as f:
        db = json.load(f)

    today = date.today().isoformat()
    checked = marked_dead = 0

    for freebie in db.get('freebies', []):
        if freebie.get('status') not in ('active',):
            continue
        if not should_recheck(freebie):
            continue
        url = freebie.get('url', '')
        if not url:
            continue
        is_valid = check_url(url)
        freebie['link_valid'] = is_valid
        freebie['link_checked'] = today
        if not is_valid:
            freebie['status'] = 'dead_link'
            marked_dead += 1
            logger.info(f"DEAD LINK (freebie): {freebie['name']} -> {url}")
        checked += 1
        time.sleep(0.3)

    # Auto-expire freebies with no expiry date that are older than 30 days
    auto_expired = 0
    for freebie in db.get('freebies', []):
        if freebie.get('status') != 'active':
            continue
        if freebie.get('expiry'):
            continue  # Has explicit expiry date — handled by expire_old_freebies()
        added = freebie.get('added_date', '')
        if not added:
            continue
        try:
            age_days = (date.today() - date.fromisoformat(added)).days
            if age_days >= 30:
                freebie['status'] = 'expired'
                auto_expired += 1
                logger.info(f"AUTO-EXPIRED freebie (30 days old): {freebie['name']}")
        except ValueError:
            pass

    with open(path, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"Freebies: checked {checked} links, {marked_dead} dead, {auto_expired} auto-expired")


def run_link_checker():
    """Run link validation on both contests and freebies."""
    logger.info("=== Link Checker Starting ===")
    validate_contests()
    validate_freebies()
    logger.info("=== Link Checker Done ===")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    run_link_checker()
