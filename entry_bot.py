#!/usr/bin/env python3
"""ContestBot Entry Bot - Automated contest form submission using Selenium."""

import json
import logging
import time
import random
from datetime import date, datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

from legal_compliance import filter_eligible_contests
from contest_scraper import load_config, load_database, save_database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ENTRY_LOG = Path('entry_log.json')


def get_driver(headless=True):
    """Initialize Chrome WebDriver."""
    options = Options()
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def human_delay(min_s=1.0, max_s=3.0):
    """Random delay to mimic human behavior."""
    time.sleep(random.uniform(min_s, max_s))


def fill_field(driver, field, value):
    """Try to fill a form field by common selectors."""
    selectors = [
        f"input[name*='{field}']",
        f"input[id*='{field}']",
        f"input[placeholder*='{field}']",
        f"input[aria-label*='{field}']",
    ]
    for sel in selectors:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            elem.clear()
            for char in value:
                elem.send_keys(char)
                time.sleep(random.uniform(0.02, 0.08))
            return True
        except NoSuchElementException:
            continue
    return False


def try_fill_form(driver, user_info):
    """Attempt to fill a standard contest form."""
    field_map = {
        'first': user_info.get('first_name', ''),
        'last': user_info.get('last_name', ''),
        'email': user_info.get('email', ''),
        'phone': user_info.get('phone', ''),
        'postal': user_info.get('postal_code', ''),
        'zip': user_info.get('postal_code', ''),
        'city': user_info.get('city', ''),
    }
    filled = 0
    for field_hint, value in field_map.items():
        if value and fill_field(driver, field_hint, value):
            filled += 1
            human_delay(0.5, 1.5)
    return filled


def try_check_consent(driver):
    """Try to check consent/rules checkboxes."""
    checked = 0
    consent_selectors = [
        "input[type='checkbox'][name*='rule']",
        "input[type='checkbox'][name*='agree']",
        "input[type='checkbox'][name*='terms']",
        "input[type='checkbox'][name*='consent']",
        "input[type='checkbox'][id*='rule']",
        "input[type='checkbox'][id*='agree']",
    ]
    for sel in consent_selectors:
        try:
            boxes = driver.find_elements(By.CSS_SELECTOR, sel)
            for box in boxes:
                if not box.is_selected():
                    box.click()
                    checked += 1
                    human_delay(0.3, 0.8)
        except Exception:
            continue
    return checked


def try_select_province(driver, province='Ontario'):
    """Try to select province from dropdown."""
    selectors = [
        "select[name*='province']",
        "select[name*='state']",
        "select[name*='region']",
        "select[id*='province']",
    ]
    for sel in selectors:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            select = Select(elem)
            for option in select.options:
                if province.lower() in option.text.lower():
                    select.select_by_visible_text(option.text)
                    return True
        except Exception:
            continue
    return False


def try_submit(driver):
    """Try to find and click submit button."""
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:contains('Submit')",
        "button:contains('Enter')",
        ".submit-btn",
        "#submit",
    ]
    for sel in submit_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            if btn.is_displayed() and btn.is_enabled():
                btn.click()
                return True
        except Exception:
            continue

    # Fallback: find by text content
    for text in ['Submit', 'Enter Now', 'Enter Contest', 'ENTER', 'SUBMIT']:
        try:
            btn = driver.find_element(By.XPATH, f"//button[contains(text(), '{text}')]")
            if btn.is_displayed():
                btn.click()
                return True
        except Exception:
            continue
    return False


def enter_contest(driver, contest, user_info):
    """Attempt to enter a single contest."""
    result = {
        'contest_id': contest['id'],
        'contest_name': contest['name'],
        'url': contest['url'],
        'timestamp': datetime.now().isoformat(),
        'status': 'failed',
        'fields_filled': 0,
        'error': None
    }

    try:
        logger.info(f"Entering: {contest['name']} ({contest['url']})")
        driver.get(contest['url'])
        human_delay(2, 4)

        # Wait for page load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )

        # Fill form fields
        filled = try_fill_form(driver, user_info)
        result['fields_filled'] = filled
        logger.info(f"  Filled {filled} fields")

        # Select province
        try_select_province(driver, user_info.get('province', 'Ontario'))

        # Check consent boxes
        checked = try_check_consent(driver)
        logger.info(f"  Checked {checked} consent boxes")

        human_delay(1, 2)

        # Submit
        if filled >= 2:
            submitted = try_submit(driver)
            if submitted:
                human_delay(2, 4)
                result['status'] = 'submitted'
                logger.info(f"  SUBMITTED successfully")
            else:
                result['status'] = 'no_submit_button'
                result['error'] = 'Could not find submit button'
                logger.warning(f"  Could not find submit button")
        else:
            result['status'] = 'insufficient_fields'
            result['error'] = f'Only filled {filled} fields'
            logger.warning(f"  Only filled {filled} fields, skipping submit")

    except TimeoutException:
        result['error'] = 'Page load timeout'
        logger.error(f"  Timeout loading {contest['url']}")
    except Exception as e:
        result['error'] = str(e)[:200]
        logger.error(f"  Error: {e}")

    return result


def log_entry(result):
    """Append entry result to log file."""
    log = []
    if ENTRY_LOG.exists():
        with open(ENTRY_LOG) as f:
            log = json.load(f)
    log.append(result)
    with open(ENTRY_LOG, 'w') as f:
        json.dump(log, f, indent=2)


def run_entry_bot():
    """Main entry bot runner."""
    logger.info("=== ContestBot Entry Bot Starting ===")
    config = load_config()
    db = load_database()
    user_info = config.get('user', {})
    settings = config.get('settings', {})

    if user_info.get('first_name') == 'CHANGE_ME':
        logger.error("Config not set up! Edit config.json with your info.")
        return

    eligible = filter_eligible_contests(db, config)
    max_entries = settings.get('max_entries_per_day', 50)
    headless = settings.get('headless_browser', True)

    logger.info(f"Found {len(eligible)} eligible contests (max {max_entries}/day)")

    driver = get_driver(headless=headless)
    entered = 0
    results = []

    try:
        for contest in eligible[:max_entries]:
            result = enter_contest(driver, contest, user_info)
            results.append(result)
            log_entry(result)

            if result['status'] == 'submitted':
                # Update last_entered in database
                for c in db['contests']:
                    if c['id'] == contest['id']:
                        c['last_entered'] = date.today().isoformat()
                        break
                entered += 1

            human_delay(3, 7)  # Delay between contests

    finally:
        driver.quit()
        save_database(db)

    logger.info(f"=== Entry Bot Done: {entered}/{len(eligible)} submitted ===")
    return results


if __name__ == '__main__':
    run_entry_bot()
