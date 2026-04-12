#!/usr/bin/env python3
"""ContestBot Legal Compliance - Province eligibility and contest rule checker."""

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

PROVINCE_CODES = {
    'Ontario': 'ON', 'Quebec': 'QC', 'British Columbia': 'BC',
    'Alberta': 'AB', 'Manitoba': 'MB', 'Saskatchewan': 'SK',
    'Nova Scotia': 'NS', 'New Brunswick': 'NB',
    'Newfoundland and Labrador': 'NL', 'Prince Edward Island': 'PE',
    'Northwest Territories': 'NT', 'Yukon': 'YT', 'Nunavut': 'NU'
}

AGE_OF_MAJORITY = {
    'ON': 18, 'QC': 18, 'BC': 19, 'AB': 18, 'MB': 18, 'SK': 18,
    'NS': 19, 'NB': 19, 'NL': 19, 'PE': 18, 'NT': 19, 'YT': 19, 'NU': 19
}


def check_province_eligible(contest, user_province='Ontario'):
    """Check if user's province is eligible for this contest."""
    provinces = contest.get('provinces', [])
    if not provinces:
        return True
    if 'All Canada' in provinces:
        return True
    user_code = PROVINCE_CODES.get(user_province, user_province)
    return user_code in provinces or user_province in provinces


def check_age_eligible(contest, user_dob=None, user_province='Ontario'):
    """Check if user meets age requirement."""
    restrictions = contest.get('restrictions', '').lower()
    user_code = PROVINCE_CODES.get(user_province, user_province)
    min_age = AGE_OF_MAJORITY.get(user_code, 18)

    if '21+' in restrictions or '21 or older' in restrictions:
        min_age = 21
    elif '19+' in restrictions or '19 or older' in restrictions:
        min_age = 19
    elif '25+' in restrictions:
        min_age = 25

    if user_dob:
        today = date.today()
        try:
            dob = date.fromisoformat(user_dob)
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age >= min_age
        except ValueError:
            pass
    return True


def check_not_expired(contest):
    """Check if contest is still active."""
    end_date = contest.get('end_date', '')
    if not end_date:
        return True
    try:
        return date.fromisoformat(end_date) >= date.today()
    except ValueError:
        return True


def check_entry_allowed(contest):
    """Check if another entry is allowed based on frequency and last entry."""
    last = contest.get('last_entered')
    if not last:
        return True
    freq = contest.get('entry_frequency', 'single')
    if freq == 'single':
        return False
    try:
        last_date = date.fromisoformat(last)
        days_since = (date.today() - last_date).days
        if freq == 'daily':
            return days_since >= 1
        elif freq == 'weekly':
            return days_since >= 7
        elif freq == 'monthly':
            return days_since >= 30
    except ValueError:
        pass
    return True


def filter_eligible_contests(db, config):
    """Return list of contests the user is eligible to enter today."""
    user = config.get('user', {})
    province = user.get('province', 'Ontario')
    dob = user.get('date_of_birth')
    eligible = []

    for contest in db.get('contests', []):
        if contest.get('status') != 'active':
            continue
        if not contest.get('npn', False):
            continue
        if not check_not_expired(contest):
            contest['status'] = 'expired'
            logger.info(f"Expired: {contest['name']}")
            continue
        if not check_province_eligible(contest, province):
            logger.debug(f"Province ineligible: {contest['name']}")
            continue
        if not check_age_eligible(contest, dob, province):
            logger.debug(f"Age ineligible: {contest['name']}")
            continue
        if not check_entry_allowed(contest):
            logger.debug(f"Already entered: {contest['name']}")
            continue
        eligible.append(contest)

    eligible.sort(key=lambda c: c.get('prize_value', 0), reverse=True)
    logger.info(f"Found {len(eligible)} eligible contests out of {len(db.get('contests', []))} total")
    return eligible


def generate_compliance_report(db, config):
    """Generate a compliance summary report."""
    eligible = filter_eligible_contests(db, config)
    total = len(db.get('contests', []))
    active = len([c for c in db['contests'] if c['status'] == 'active'])
    expired = len([c for c in db['contests'] if c['status'] == 'expired'])

    report = {
        'date': date.today().isoformat(),
        'total_contests': total,
        'active': active,
        'expired': expired,
        'eligible_today': len(eligible),
        'total_eligible_value': sum(c.get('prize_value', 0) for c in eligible),
        'contests': [{'name': c['name'], 'prize_value': c['prize_value'], 'end_date': c['end_date']} for c in eligible]
    }
    return report
