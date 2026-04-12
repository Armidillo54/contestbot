#!/usr/bin/env python3
"""ContestBot Master Orchestrator - Runs the full daily pipeline."""

import logging
import sys
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


def main():
    start = datetime.now()
    logger.info("="*60)
    logger.info("CONTESTBOT DAILY PIPELINE STARTING")
    logger.info(f"Date: {start.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info("="*60)

    # Step 1: Scrape aggregator sites
    logger.info("\n[1/5] SCRAPING CONTEST AGGREGATORS...")
    try:
        from contest_scraper import run_scraper
        db = run_scraper()
        logger.info("Scraper completed successfully")
    except Exception as e:
        logger.error(f"Scraper failed: {e}")
        db = None

    # Step 2: Perplexity AI Scout
    logger.info("\n[2/5] RUNNING PERPLEXITY AI SCOUT...")
    try:
        from perplexity_scout import run_scout
        run_scout()
        logger.info("AI Scout completed")
    except Exception as e:
        logger.error(f"AI Scout failed: {e}")

    # Step 3: Compliance check
    logger.info("\n[3/5] RUNNING COMPLIANCE CHECK...")
    try:
        import json
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
        report = {}

    # Step 4: Entry bot (only if running locally with Chrome)
    logger.info("\n[4/5] ENTRY BOT...")
    try:
        import os
        if os.environ.get('RUN_ENTRY_BOT', 'false').lower() == 'true':
            from entry_bot import run_entry_bot
            results = run_entry_bot()
            logger.info(f"Entry bot completed: {len(results or [])} attempts")
        else:
            logger.info("Entry bot skipped (set RUN_ENTRY_BOT=true to enable)")
    except Exception as e:
        logger.error(f"Entry bot failed: {e}")

    # Step 5: Send notifications
    logger.info("\n[5/5] SENDING NOTIFICATIONS...")
    try:
        from notifier import send_daily_report
        send_daily_report()
        logger.info("Notifications sent")
    except Exception as e:
        logger.error(f"Notifications failed: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("\n" + "="*60)
    logger.info(f"CONTESTBOT PIPELINE COMPLETE ({elapsed:.1f}s)")
    logger.info("="*60)


if __name__ == '__main__':
    main()
