#!/usr/bin/env python3
"""Run compliance check and generate report."""

import json
from legal_compliance import generate_compliance_report

with open('contests_database.json') as f:
    db = json.load(f)
with open('config.json') as f:
    config = json.load(f)

report = generate_compliance_report(db, config)

print(f"Eligible contests today: {report['eligible_today']}")
print(f"Total prize value: ${report['total_eligible_value']:,}")
for c in report['contests']:
    print(f"  - {c['name']} (${c['prize_value']:,}) ends {c['end_date']}")

with open('compliance_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print("Compliance report saved to compliance_report.json")
