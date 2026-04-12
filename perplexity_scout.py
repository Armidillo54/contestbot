#!/usr/bin/env python3
"""ContestBot Perplexity Scout - Uses Perplexity API to discover new Canadian NPN contests."""

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

import requests

from contest_scraper import load_database, save_database, merge_contests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_KEY = os.environ.get('PERPLEXITY_API_KEY', '')
API_URL = 'https://api.perplexity.ai/chat/completions'

SCOUT_QUERIES = [
    "Find all active Canadian no purchase necessary (NPN) contests ending after {today}. List the contest name, URL, prize, end date, and provinces eligible. Focus on online entry contests open to Ontario residents.",
    "What new Canadian sweepstakes and contests launched this week that are no purchase necessary? Include brand name, prize value, entry URL, and end date.",
    "List Canadian daily entry contests currently active on contestgirl.com, redflagdeals.com, or canadianfreestuff.com with prizes over $100.",
]


def query_perplexity(prompt):
    """Send a query to Perplexity API and return the response."""
    if not API_KEY:
        logger.error("PERPLEXITY_API_KEY not set. Skipping AI scout.")
        return None

    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'sonar',
        'messages': [
            {
                'role': 'system',
                'content': 'You are a Canadian contest research assistant. Return results as a JSON array of objects with keys: name, url, prize, prize_value (integer in CAD), end_date (YYYY-MM-DD), entry_frequency (daily/weekly/monthly/single), provinces (array of province codes or ["All Canada"]), npn_note. Only include No Purchase Necessary contests. If unsure about a field, use null.'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'temperature': 0.1,
        'max_tokens': 4000
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        logger.info(f"Perplexity response length: {len(content)} chars")
        return content
    except Exception as e:
        logger.error(f"Perplexity API error: {e}")
        return None


def parse_contests_from_response(response_text):
    """Extract contest data from Perplexity API response."""
    contests = []
    if not response_text:
        return contests

    # Try to find JSON array in response
    json_match = re.search(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL)
    if json_match:
        try:
            raw_contests = json.loads(json_match.group())
            for rc in raw_contests:
                if not rc.get('name') or not rc.get('url'):
                    continue
                contest_id = re.sub(r'[^a-z0-9]', '-', rc['name'].lower().strip())[:50]
                contests.append({
                    'id': f"pplx-{contest_id}",
                    'name': rc['name'],
                    'url': rc['url'],
                    'prize': rc.get('prize', 'Unknown'),
                    'prize_value': rc.get('prize_value', 0) or 0,
                    'entry_method': 'online_form',
                    'entry_frequency': rc.get('entry_frequency', 'single'),
                    'npn': True,
                    'npn_note': rc.get('npn_note', 'Discovered by Perplexity AI'),
                    'restrictions': '',
                    'provinces': rc.get('provinces', ['All Canada']),
                    'end_date': rc.get('end_date', ''),
                    'source': 'perplexity_ai',
                    'status': 'unverified',
                    'last_entered': None
                })
            logger.info(f"Parsed {len(contests)} contests from AI response")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
    else:
        logger.warning("No JSON array found in Perplexity response")

    return contests


def run_scout():
    """Main scout entry point."""
    logger.info("=== Perplexity Scout Starting ===")

    if not API_KEY:
        logger.warning("No PERPLEXITY_API_KEY set. Set it as a GitHub secret or env var.")
        logger.info("Skipping AI-powered contest discovery.")
        return

    db = load_database()
    all_new = []

    for i, query_template in enumerate(SCOUT_QUERIES):
        query = query_template.format(today=date.today().isoformat())
        logger.info(f"Scout query {i+1}/{len(SCOUT_QUERIES)}...")

        response = query_perplexity(query)
        if response:
            contests = parse_contests_from_response(response)
            all_new.extend(contests)

    if all_new:
        added = merge_contests(db, all_new)
        save_database(db)
        logger.info(f"Scout found {len(all_new)} contests, {added} were new")
    else:
        logger.info("Scout found no new contests")

    logger.info("=== Perplexity Scout Done ===")


if __name__ == '__main__':
    run_scout()
