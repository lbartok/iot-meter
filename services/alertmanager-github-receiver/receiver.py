"""
Alertmanager → GitHub Issues webhook receiver.

Receives Alertmanager webhook POSTs and creates/closes GitHub Issues.
Each unique alert gets one issue; resolved alerts close the issue.

Environment variables:
  GITHUB_TOKEN       — Personal access token with 'issues' scope
  GITHUB_OWNER       — Repository owner  (default: lbartok)
  GITHUB_REPO        — Repository name   (default: iot-meter)
  RECEIVER_PORT      — Listen port        (default: 8082)
  DRY_RUN            — Set to '1' to log without creating issues
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timezone

from flask import Flask, request, jsonify
import requests as http_requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_OWNER = os.environ.get('GITHUB_OWNER', 'lbartok')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'iot-meter')
RECEIVER_PORT = int(os.environ.get('RECEIVER_PORT', '8082'))
DRY_RUN = os.environ.get('DRY_RUN', '0') == '1'

GITHUB_API = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}'

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('github-receiver')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _github_headers():
    return {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }


def _alert_fingerprint(alert: dict) -> str:
    """Stable fingerprint for dedup — matches Alertmanager's grouping."""
    labels = alert.get('labels', {})
    key = json.dumps(labels, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _severity_label(alert: dict) -> str:
    return f"severity/{alert.get('labels', {}).get('severity', 'unknown')}"


def _service_label(alert: dict) -> str:
    svc = alert.get('labels', {}).get('service', alert.get('labels', {}).get('job', 'unknown'))
    return f"service/{svc}"


def _build_issue_title(alert: dict) -> str:
    name = alert.get('labels', {}).get('alertname', 'Unknown')
    svc = alert.get('labels', {}).get('service', '')
    fp = _alert_fingerprint(alert)
    return f"[Alert] {name} — {svc} [{fp}]"


def _build_issue_body(alert: dict) -> str:
    labels = alert.get('labels', {})
    annotations = alert.get('annotations', {})
    starts = alert.get('startsAt', 'unknown')
    status = alert.get('status', 'firing')

    body = f"## {annotations.get('summary', labels.get('alertname', 'Alert'))}\n\n"
    body += f"**Status:** `{status}`\n"
    body += f"**Severity:** `{labels.get('severity', 'unknown')}`\n"
    body += f"**Service:** `{labels.get('service', labels.get('job', 'unknown'))}`\n"
    body += f"**Started:** `{starts}`\n\n"
    body += f"### Description\n\n{annotations.get('description', 'No description provided.')}\n\n"
    body += f"### Labels\n\n```json\n{json.dumps(labels, indent=2)}\n```\n\n"
    body += f"### Annotations\n\n```json\n{json.dumps(annotations, indent=2)}\n```\n\n"
    body += "---\n*Auto-created by alertmanager-github-receiver*\n"
    return body


def _find_open_issue(fingerprint: str) -> dict | None:
    """Search for an existing open issue with the same fingerprint."""
    search_url = f'https://api.github.com/search/issues'
    q = f'repo:{GITHUB_OWNER}/{GITHUB_REPO} is:issue is:open [{fingerprint}] in:title'
    resp = http_requests.get(search_url, headers=_github_headers(), params={'q': q})
    if resp.status_code == 200 and resp.json().get('total_count', 0) > 0:
        return resp.json()['items'][0]
    return None


def _create_issue(alert: dict) -> dict | None:
    """Create a new GitHub issue for a firing alert."""
    title = _build_issue_title(alert)
    body = _build_issue_body(alert)
    labels = ['alert', _severity_label(alert), _service_label(alert)]

    if DRY_RUN:
        log.info(f'DRY_RUN: Would create issue: {title}')
        return {'number': 0, 'html_url': 'dry-run'}

    resp = http_requests.post(
        f'{GITHUB_API}/issues',
        headers=_github_headers(),
        json={'title': title, 'body': body, 'labels': labels},
    )
    if resp.status_code == 201:
        issue = resp.json()
        log.info(f'Created issue #{issue["number"]}: {title}')
        return issue
    else:
        log.error(f'Failed to create issue: {resp.status_code} {resp.text}')
        return None


def _close_issue(issue: dict, alert: dict):
    """Close an existing issue when alert resolves."""
    number = issue['number']
    ends = alert.get('endsAt', 'unknown')

    comment = f"## Resolved\n\nAlert resolved at `{ends}`.\n\n---\n*Auto-closed by alertmanager-github-receiver*"

    if DRY_RUN:
        log.info(f'DRY_RUN: Would close issue #{number}')
        return

    # Add resolved comment
    http_requests.post(
        f'{GITHUB_API}/issues/{number}/comments',
        headers=_github_headers(),
        json={'body': comment},
    )

    # Close issue
    resp = http_requests.patch(
        f'{GITHUB_API}/issues/{number}',
        headers=_github_headers(),
        json={'state': 'closed'},
    )
    if resp.status_code == 200:
        log.info(f'Closed issue #{number}')
    else:
        log.error(f'Failed to close issue #{number}: {resp.status_code}')


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive Alertmanager webhook and create/close GitHub issues."""
    payload = request.get_json(force=True)
    alerts = payload.get('alerts', [])
    log.info(f'Received {len(alerts)} alert(s)')

    results = []
    for alert in alerts:
        status = alert.get('status', 'firing')
        fp = _alert_fingerprint(alert)
        name = alert.get('labels', {}).get('alertname', 'Unknown')

        if status == 'firing':
            existing = _find_open_issue(fp)
            if existing:
                log.info(f'Issue already open for {name} [{fp}]: #{existing["number"]}')
                results.append({'alert': name, 'action': 'already_open', 'issue': existing['number']})
            else:
                issue = _create_issue(alert)
                if issue:
                    results.append({'alert': name, 'action': 'created', 'issue': issue.get('number', 0)})
                else:
                    results.append({'alert': name, 'action': 'error'})

        elif status == 'resolved':
            existing = _find_open_issue(fp)
            if existing:
                _close_issue(existing, alert)
                results.append({'alert': name, 'action': 'closed', 'issue': existing['number']})
            else:
                log.info(f'No open issue found for resolved alert {name} [{fp}]')
                results.append({'alert': name, 'action': 'no_issue_to_close'})

    return jsonify({'status': 'ok', 'processed': len(results), 'results': results}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'alertmanager-github-receiver',
        'dry_run': DRY_RUN,
        'github_configured': bool(GITHUB_TOKEN),
        'target': f'{GITHUB_OWNER}/{GITHUB_REPO}',
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    if not GITHUB_TOKEN and not DRY_RUN:
        log.warning('GITHUB_TOKEN not set — running in DRY_RUN mode')
        DRY_RUN = True
    log.info(f'Starting alertmanager-github-receiver on port {RECEIVER_PORT}')
    log.info(f'Target: {GITHUB_OWNER}/{GITHUB_REPO}, DRY_RUN={DRY_RUN}')
    app.run(host='0.0.0.0', port=RECEIVER_PORT)
