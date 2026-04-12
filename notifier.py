#!/usr/bin/env python3
"""ContestBot Notifier - Email notifications for new contests and entry results."""

import json
import logging
import os
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', '')


def send_email(subject, html_body):
    """Send an HTML email notification."""
    if not all([SMTP_USER, SMTP_PASS, NOTIFY_EMAIL]):
        logger.warning("Email not configured. Set SMTP_USER, SMTP_PASS, NOTIFY_EMAIL env vars.")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


def build_daily_report(db, report):
    """Build HTML daily report email."""
    active = [c for c in db.get('contests', []) if c['status'] == 'active']
    total_value = sum(c.get('prize_value', 0) for c in active)
    today = date.today().isoformat()

    contest_rows = ''
    for c in sorted(active, key=lambda x: x.get('prize_value', 0), reverse=True)[:15]:
        status_color = '#00ff88' if c.get('last_entered') == today else '#888'
        contest_rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333">{c['name']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#00ff88">${c.get('prize_value',0):,}</td>
            <td style="padding:8px;border-bottom:1px solid #333">{c.get('end_date','--')}</td>
            <td style="padding:8px;border-bottom:1px solid #333">{c.get('entry_frequency','--')}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{status_color}">
                {'Entered' if c.get('last_entered') == today else 'Pending'}
            </td>
        </tr>"""

    html = f"""
    <div style="font-family:sans-serif;background:#0a0a0f;color:#e0e0e0;padding:30px;max-width:700px;margin:0 auto">
        <h1 style="color:#00d4ff;text-align:center">ContestBot Daily Report</h1>
        <p style="text-align:center;color:#888">{today}</p>

        <div style="display:flex;gap:15px;margin:20px 0;justify-content:center">
            <div style="background:#12121f;padding:15px 25px;border-radius:10px;text-align:center">
                <div style="font-size:2em;color:#00d4ff;font-weight:700">{len(active)}</div>
                <div style="color:#888;font-size:0.85em">Active</div>
            </div>
            <div style="background:#12121f;padding:15px 25px;border-radius:10px;text-align:center">
                <div style="font-size:2em;color:#00ff88;font-weight:700">${total_value:,}</div>
                <div style="color:#888;font-size:0.85em">Prize Pool</div>
            </div>
            <div style="background:#12121f;padding:15px 25px;border-radius:10px;text-align:center">
                <div style="font-size:2em;color:#7b2ff7;font-weight:700">{report.get('eligible_today',0)}</div>
                <div style="color:#888;font-size:0.85em">Eligible</div>
            </div>
        </div>

        <table style="width:100%;border-collapse:collapse;background:#12121f;border-radius:10px;overflow:hidden;margin-top:20px">
            <tr style="background:#1a1a2e">
                <th style="padding:10px;text-align:left;color:#00d4ff">Contest</th>
                <th style="padding:10px;text-align:left;color:#00d4ff">Value</th>
                <th style="padding:10px;text-align:left;color:#00d4ff">Ends</th>
                <th style="padding:10px;text-align:left;color:#00d4ff">Freq</th>
                <th style="padding:10px;text-align:left;color:#00d4ff">Status</th>
            </tr>
            {contest_rows}
        </table>

        <p style="text-align:center;color:#555;margin-top:20px;font-size:0.8em">
            ContestBot | Orillia, ON | NPN Only
        </p>
    </div>"""
    return html


def notify_new_contests(new_contests):
    """Send notification about newly discovered contests."""
    if not new_contests:
        return

    items = ''.join(f"<li><b>{c['name']}</b> - ${c.get('prize_value',0):,} (ends {c.get('end_date','TBD')})</li>" for c in new_contests)
    html = f"""
    <div style="font-family:sans-serif;background:#0a0a0f;color:#e0e0e0;padding:30px">
        <h2 style="color:#00d4ff">New Contests Found!</h2>
        <p>ContestBot discovered {len(new_contests)} new contest(s):</p>
        <ul style="line-height:2">{items}</ul>
    </div>"""
    send_email(f"ContestBot: {len(new_contests)} New Contests Found", html)


def send_daily_report():
    """Load data and send daily report."""
    try:
        with open('contests_database.json') as f:
            db = json.load(f)
        report = {}
        if Path('compliance_report.json').exists():
            with open('compliance_report.json') as f:
                report = json.load(f)
        html = build_daily_report(db, report)
        send_email(f"ContestBot Daily Report - {date.today().isoformat()}", html)
    except Exception as e:
        logger.error(f"Failed to send daily report: {e}")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    send_daily_report()
