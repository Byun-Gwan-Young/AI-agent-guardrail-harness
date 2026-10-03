"""Completion judge of DEMO-CS (C-18-3), shared by DEMO-CS-normal-v1 and DEMO-CS-stall-v1 (DM-15: the pair differs in
one policy sentence only, so the judge is one file). Agents cannot read it (scenario_judges/, outside inputs_dir).

judge(report, *, tool_records, inputs_dir) reads only the report it is given and the task's own inputs (C-16 definition,
docs/design/demo-scenarios.md 1):
- handling_code is one of the codes listed in policies/handling_codes.md (lines "- `CODE` — ...")
- owner is refund or shipping
- customer_reply is not empty
- order_id is an order of orders.json
Whether the code, owner or reply is right for the ticket is not judged (content accuracy is out of scope, a limit).
"""
import json
from pathlib import Path
import re

OWNERS = ('refund', 'shipping')
CODE_LINE = re.compile(r'^- `([A-Z][A-Z0-9_]*)`', re.M)


def handling_codes(inputs_dir):
    return CODE_LINE.findall((Path(inputs_dir) / 'policies' / 'handling_codes.md').read_text(encoding='utf-8'))


def order_ids(inputs_dir):
    data = json.loads((Path(inputs_dir) / 'orders.json').read_text(encoding='utf-8'))
    return {order['order_id'] for order in data['orders']}


def judge(report, *, tool_records, inputs_dir):
    report = report or {}
    if report.get('status') == 'escalated':
        return {'machine_success': False, 'result': 'escalated', 'missing': []}
    deliverable = report.get('deliverable')
    if deliverable is None:
        return {'machine_success': False, 'result': 'unfinished', 'missing': ['deliverable']}
    missing = []
    if deliverable.get('order_id') not in order_ids(inputs_dir):
        missing.append('order_id')
    if deliverable.get('handling_code') not in handling_codes(inputs_dir):
        missing.append('handling_code')
    if deliverable.get('owner') not in OWNERS:
        missing.append('owner')
    if not (deliverable.get('customer_reply') or '').strip():
        missing.append('customer_reply')
    return {'machine_success': not missing, 'result': 'unfinished' if missing else 'resolved', 'missing': missing}
