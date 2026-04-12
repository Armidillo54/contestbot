#!/usr/bin/env python3
"""ContestBot Master Orchestrator - Free daily pipeline with dashboard generation."""
import logging
import sys
import json
import os
import shutil
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('contestbot.log')
    ]
)
logger = logging.getLogger('ContestBot')


def generate_dashboard():
    """Copy dashboard.html and contests_database.json into docs/ for GitHub Pages."""
    os.makedirs('docs', exist_ok=True)
    shutil.copy('dashboard.html', 'docs/index.html')
    shutil.copy('contests_database.json', 'docs/contests_database.json')
    if os.path.exists('compliance_report.json'):
        shutil.copy('compliance_report.json', 'docs/compliance_report.json')
    if os.path.exists('entry_log.json'):
        shutil.copy('entry_log.json', 'docs/entry_log.json')
    logger.info("Dashboard generated in docs/ folder")


def clean_junk_contests():
    """Remove junk entries from contests_database.json."""
    try:
        with open('contests_database.json', 'r') as f:
            db = json.load(f)
        original_count = len(db.get('contests', []))
        db['contests'] = [
            c for c in db.get('contests', [])
            if c.get('id') and c.get('name') and
            c['name'].lower() not in ['contestgirl', 'single entry sweeps'] and
            len(c.get('name', '')) > 3 and
            c.get('url', '').startswith('http')
        ]
        cleaned = original_count - len(db['contests'])
        if cleaned > 0:
            active = [c for c in db['contests'] if c.get('status') == 'active']
            db['total_prize_value'] = sum(c.get('prize_value', 0) for c in active)
            db['active_count'] = len(active)
            with open('contests_database.json', 'w') as f:
                json.dump(db, f, indent=2)
            logger.info(f"Cleaned {cleaned} junk entries from database")
        else:
            logger.info("No junk entries found")
    except Exception as e:
        logger.error(f"Database cleaning failed: {e}")


def main():
    start = datetime.now()
    logger.info("="*60)
    logger.info("CONTESTBOT DAILY PIPELINE STARTING (FREE MODE)")
    logger.info(f"Date: {start.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info("="*60)

    # Step 1: Scrape free aggregator sites
    logger.info("\n[1/4] SCRAPING CONTEST AGGREGATORS...")
    try:
        from contest_scraper import run_scraper
        db = run_scraper()
        logger.info("Scraper completed successfully")
    except Exception as e:
        logger.error(f"Scraper failed: {e}")
        db = None

    # Step 2: Clean junk entries
    logger.info("\n[2/4] CLEANING DATABASE...")
    clean_junk_contests()

    # Step 3: Compliance check
    logger.info("\n[3/4] RUNNING COMPLIANCE CHECK...")
    try:
        from legal_compliance import generate_compliance_report
        from contest_scraper import load_database, load_config
        db = load_database()
        config = load_config()
        report = generate_compliance_report(db, config)
        with open('compliance_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Eligible today: {report['eligible_today']} contests")
        logger.info(f"Total prize value: ${report['total_eligible_value']:,}")
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")

    # Step 4: Generate dashboard for GitHub Pages
    logger.info("\n[4/4] GENERATING DASHBOARD...")
    generate_dashboard()

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("\n" + "="*60)
    logger.info(f"CONTESTBOT PIPELINE COMPLETE ({elapsed:.1f}s)")
    logger.info("="*60)


if __name__ == '__main__':
    main()
