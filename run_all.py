#!/usr/bin/env python3
"""ContestBot - Daily contest scanner and dashboard generator."""
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
    """Copy dashboard and data into docs/ for GitHub Pages."""
    os.makedirs('docs', exist_ok=True)
    shutil.copy('dashboard.html', 'docs/index.html')
    shutil.copy('contests_database.json', 'docs/contests_database.json')
    shutil.copy('freebies_database.json', 'docs/freebies_database.json')
    logger.info("Dashboard generated in docs/")


def clean_junk_contests():
    """Remove junk entries from contests_database.json."""
    try:
        with open('contests_database.json', 'r') as f:
            db = json.load(f)
        original = len(db.get('contests', []))
        db['contests'] = [
            c for c in db.get('contests', [])
            if c.get('id') and c.get('name')
            and c['name'].lower() not in ['contestgirl', 'single entry sweeps']
            and len(c.get('name', '')) > 3
            and c.get('url', '').startswith('http')
        ]
        cleaned = original - len(db['contests'])
        if cleaned > 0:
            active = [c for c in db['contests'] if c.get('status') == 'active']
            db['total_prize_value'] = sum(c.get('prize_value', 0) for c in active)
            db['active_count'] = len(active)
            with open('contests_database.json', 'w') as f:
                json.dump(db, f, indent=2)
            logger.info(f"Cleaned {cleaned} junk entries")
    except Exception as e:
        logger.error(f"Cleaning failed: {e}")


def main():
    start = datetime.now()
    logger.info("=" * 50)
    logger.info("CONTESTBOT DAILY SCAN")
    logger.info(f"Date: {start.strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)

    # Step 1: Scrape free contest sources
    logger.info("[1/3] Scraping contests...")
    try:
        from contest_scraper import run_scraper
        run_scraper()
    except Exception as e:
        logger.error(f"Scraper failed: {e}")

    # Step 2: Clean junk
    logger.info("[2/3] Cleaning database...")
    clean_junk_contests()

    # Step 3: Generate dashboard
    logger.info("[3/3] Generating dashboard...")
    generate_dashboard()

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"Done in {elapsed:.1f}s")


if __name__ == '__main__':
    main()
