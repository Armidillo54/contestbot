#!/usr/bin/env python3
"""
Sale scraper — checks the sale/promotions pages of specific Canadian retailers
and extracts active deals (e.g. "30% off footwear", "Up to 50% off kids").

Each store entry in the database is keyed by store+category so stale deals are
replaced on every run rather than accumulating.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SALES_DB_PATH = Path('sales_database.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-CA,en;q=0.9',
}

# Patterns to find discount text anywhere on the page
PCT_PATTERNS = [
    r'up\s+to\s+(\d+)\s*%\s*off',
    r'save\s+up\s+to\s+(\d+)\s*%',
    r'(\d+)\s*%\s*off\s+([\w\s&\']+)',
    r'save\s+(\d+)\s*%',
    r'(\d+)\s*-\s*(\d+)\s*%\s*off',
    r'up\s+to\s+(\d+)\s*%',
    r'(\d+)\s*%\s*off',
    r'\$(\d+)\s*off',
    r'buy\s+(\d+)\s*get\s+(\d+)\s*free',
]

STORES = [
    {
        'store': "Tip Top Tailor",
        'short': 'tiptop',
        'urls': [
            'https://www.tiptop.ca/collections/sale',
            'https://www.tiptop.ca/collections/mid-season-sale',
        ],
        'category': 'Menswear',
    },
    {
        'store': "Mark's",
        'short': 'marks',
        'urls': [
            'https://www.marks.com/en/sale-clearance.html',
            'https://www.marks.com/en/sale-clearance/storewide.html',
        ],
        'category': 'Clothing & Workwear',
    },
    {
        'store': "Sport Chek",
        'short': 'sportchek',
        'urls': [
            'https://www.sportchek.ca/en/sale-clearance.html',
            'https://www.sportchek.ca/en/sale-clearance/sale.html',
        ],
        'category': 'Sports & Outdoors',
    },
    {
        'store': "Joe Fresh",
        'short': 'joefresh',
        'urls': [
            'https://www.joefresh.com/ca/collections/c/clearance',
            'https://www.joefresh.com/ca/Categories/Women/Women-s-Sale/c/56018?query=promotions%3Dclearance',
        ],
        'category': 'Clothing',
    },
    {
        'store': "H&M Kids",
        'short': 'hmkids',
        'urls': [
            'https://www2.hm.com/en_ca/kids/sale/2-8/view-all.html',
            'https://www2.hm.com/en_ca/kids/sale/girls/view-all.html',
        ],
        'category': "Kids' Clothing",
    },
    {
        'store': "Reitmans",
        'short': 'reitmans',
        'urls': [
            'https://www.reitmans.com/en/sale',
            'https://www.reitmans.com/collections/sale-clothing',
        ],
        'category': "Women's Clothing",
    },
    {
        'store': "RW&CO",
        'short': 'rwandco',
        'urls': [
            'https://www.rw-co.com/en/promotions-sales/man-and-women-clothing-accessories',
            'https://www.rw-co.com/en/men/sale/clearance-1',
        ],
        'category': 'Clothing',
    },
    {
        'store': "Carter's",
        'short': 'carters',
        'urls': [
            'https://www.carters.com/c/clearance',
            'https://www.carters.com/c/deals',
        ],
        'category': "Kids' Clothing",
    },
    {
        'store': "Three Ships Beauty",
        'short': 'threeships',
        'urls': [
            'https://www.threeshipsbeauty.com/collections/shop-the-sale',
            'https://www.threeshipsbeauty.com/collections/discounts-allowed',
        ],
        'category': 'Beauty',
    },
    {
        'store': "Thrive Causemetics",
        'short': 'thrive',
        'urls': [
            'https://thrivecausemetics.ca/collections/save-on-select-products',
            'https://thrivecausemetics.ca/collections/sets-price-drop',
        ],
        'category': 'Beauty',
    },
]


def fetch_page(url):
    """Fetch a URL, return (html, final_url) or (None, None) on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text, resp.url   # use final URL after any redirects
        logger.debug(f"HTTP {resp.status_code} for {url}")
    except Exception as e:
        logger.debug(f"Fetch failed {url}: {e}")
    return None, None


def extract_sale_text(html, store_name):
    """
    Pull sale/discount descriptions out of a page's HTML.
    Returns a list of human-readable strings like "Up to 40% off" or "30% off footwear".
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Grab text from the most informative elements first
    candidates = []
    for tag in soup.find_all(['title', 'meta']):
        if tag.name == 'meta' and tag.get('name') in ('description', 'og:description'):
            candidates.append(tag.get('content', ''))
        elif tag.name == 'title':
            candidates.append(tag.get_text())

    for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'strong', 'b', 'p']):
        text = tag.get_text(separator=' ', strip=True)
        if len(text) < 200:
            candidates.append(text)

    # Look for promo/banner sections
    for cls in ['promo', 'banner', 'sale', 'hero', 'offer', 'deal', 'discount', 'savings']:
        for el in soup.find_all(class_=re.compile(cls, re.I)):
            candidates.append(el.get_text(separator=' ', strip=True)[:300])

    found = []
    seen = set()
    for text in candidates:
        for pattern in PCT_PATTERNS:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                snippet = text[max(0, m.start()-20):m.end()+40].strip()
                snippet = re.sub(r'\s+', ' ', snippet)
                if snippet.lower() not in seen and len(snippet) > 4:
                    seen.add(snippet.lower())
                    found.append(snippet)

    return found


def build_sale_entries(store_cfg, descriptions, url):
    """Turn raw description strings into structured sale DB entries."""
    today = date.today().isoformat()
    entries = []
    if not descriptions:
        # Even if we couldn't parse a specific %, record that the sale page exists
        entries.append({
            'id': f"{store_cfg['short']}-sale-general",
            'store': store_cfg['store'],
            'description': f"Sale on now at {store_cfg['store']}",
            'detail': '',
            'category': store_cfg['category'],
            'url': url,
            'scraped_date': today,
            'status': 'active',
        })
    else:
        for i, desc in enumerate(descriptions[:6]):  # cap at 6 per store
            entry_id = f"{store_cfg['short']}-sale-{i}"
            entries.append({
                'id': entry_id,
                'store': store_cfg['store'],
                'description': desc,
                'detail': '',
                'category': store_cfg['category'],
                'url': url,
                'scraped_date': today,
                'status': 'active',
            })
    return entries


def scrape_store(store_cfg):
    """Try each URL for a store until one returns a live 200 page."""
    for url in store_cfg['urls']:
        html, final_url = fetch_page(url)
        if not html:
            continue
        descriptions = extract_sale_text(html, store_cfg['store'])
        # Use the final URL (after redirects) so the dashboard link actually works
        entries = build_sale_entries(store_cfg, descriptions, final_url)
        logger.info(f"{store_cfg['store']}: {len(entries)} entries → {final_url}")
        return entries
    # All URLs failed — omit this store entirely rather than show a dead link
    logger.warning(f"{store_cfg['store']}: all URLs returned non-200, skipping")
    return []


def run_sale_scraper():
    """Scrape all stores, replace entire DB with fresh results each run."""
    logger.info("=== Sale Scraper Starting ===")
    all_entries = []
    for store in STORES:
        entries = scrape_store(store)
        all_entries.extend(entries)

    db = {
        'sales': all_entries,
        'last_updated': date.today().isoformat(),
        'total_sales': len(all_entries),
        'stores': [s['store'] for s in STORES],
    }
    with open(SALES_DB_PATH, 'w') as f:
        json.dump(db, f, indent=2)
    logger.info(f"=== Sale Scraper Done: {len(all_entries)} entries across {len(STORES)} stores ===")
    return db


if __name__ == '__main__':
    run_sale_scraper()
