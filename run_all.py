#!/usr/bin/env python3
"""ContestBot — Daily pipeline: scrape → resolve URLs → validate links → clean → deploy."""
import logging
import sys
import json
import os
import shutil
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('ContestBot')


def generate_dashboard():
    """Copy dashboard and data files into docs/ for GitHub Pages."""
    os.makedirs('docs', exist_ok=True)
    shutil.copy('dashboard.html', 'docs/index.html')
    shutil.copy('contests_database.json', 'docs/contests_database.json')
    shutil.copy('freebies_database.json', 'docs/freebies_database.json')
    shutil.copy('sales_database.json', 'docs/sales_database.json')
    if os.path.exists('events_database.json'):
        shutil.copy('events_database.json', 'docs/events_database.json')
    logger.info("Dashboard generated in docs/")


def clean_junk_contests():
    """Remove obviously invalid entries from contests_database.json."""
    try:
        with open('contests_database.json', 'r') as f:
            db = json.load(f)
        original = len(db.get('contests', []))
        db['contests'] = [
            c for c in db.get('contests', [])
            if c.get('id')
            and c.get('name')
            and c['name'].lower() not in ['contestgirl', 'single entry sweeps']
            and len(c.get('name', '')) > 3
            and c.get('url', '').startswith('http')
        ]
        cleaned = original - len(db['contests'])
        if cleaned > 0:
            active = [c for c in db['contests'] if c.get('status') == 'active']
            db['total_prize_value'] = sum(c.get('prize_value', 0) for c in active)
            db['total_active'] = len(active)
            with open('contests_database.json', 'w') as f:
                json.dump(db, f, indent=2)
            logger.info(f"Cleaned {cleaned} junk contest entries")
    except Exception as e:
        logger.error(f"Contest cleaning failed: {e}")


def clean_junk_freebies():
    """Remove obviously invalid entries from freebies_database.json."""
    try:
        with open('freebies_database.json', 'r') as f:
            db = json.load(f)
        original = len(db.get('freebies', []))
        db['freebies'] = [
            f for f in db.get('freebies', [])
            if f.get('id')
            and f.get('name')
            and len(f.get('name', '')) > 3
            and f.get('url', '').startswith('http')
        ]
        cleaned = original - len(db['freebies'])
        if cleaned > 0:
            db['total_freebies'] = len([f for f in db['freebies'] if f.get('status') == 'active'])
            with open('freebies_database.json', 'w') as f:
                json.dump(db, f, indent=2)
            logger.info(f"Cleaned {cleaned} junk freebie entries")
    except Exception as e:
        logger.error(f"Freebie cleaning failed: {e}")


def main():
    start = datetime.now()
    logger.info("=" * 50)
    logger.info("CONTESTBOT DAILY SCAN")
    logger.info(f"Date: {start.strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)

    # Step 1: Scrape contests
    logger.info("[1/6] Scraping contests...")
    try:
        from contest_scraper import run_scraper
        run_scraper()
    except Exception as e:
        logger.error(f"Contest scraper failed: {e}")

    # Step 2: Scrape freebies
    logger.info("[2/7] Scraping freebies...")
    try:
        from freebie_scraper import run_freebie_scraper
        run_freebie_scraper()
    except Exception as e:
        logger.error(f"Freebie scraper failed: {e}")

    # Step 3: Scrape store sales
    logger.info("[3/8] Scraping store sales...")
    try:
        from sale_scraper import run_sale_scraper
        run_sale_scraper()
    except Exception as e:
        logger.error(f"Sale scraper failed: {e}")

    # Step 4: Scrape local Orillia events
    logger.info("[4/8] Scraping local events...")
    try:
        from event_scraper import run_event_scraper
        run_event_scraper()
    except Exception as e:
        logger.error(f"Event scraper failed: {e}")

    # Step 5: Resolve aggregator links → direct entry URLs
    logger.info("[5/8] Resolving entry URLs...")
    try:
        from url_resolver import run_url_resolver
        run_url_resolver()
    except Exception as e:
        logger.error(f"URL resolver failed: {e}")

    # Step 6: Validate links (mark 404s as dead_link)
    logger.info("[6/8] Validating links...")
    try:
        from link_checker import run_link_checker
        run_link_checker()
    except Exception as e:
        logger.error(f"Link checker failed: {e}")

    # Step 7: Clean junk entries
    logger.info("[7/8] Cleaning databases...")
    clean_junk_contests()
    clean_junk_freebies()

    # Step 8: Generate dashboard
    logger.info("[8/8] Generating dashboard...")
    generate_dashboard()

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Done in {elapsed:.1f}s")


if __name__ == '__main__':
    main()
