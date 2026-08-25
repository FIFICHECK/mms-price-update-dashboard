#!/usr/bin/env python3
"""
MMS Price Update Scheduler — checks config.json for due SKUs and triggers price_update.py.
Silent when nothing is due (no_agent watchdog pattern).
"""
import os, sys, json, subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = '/tmp/mms_price_update.lock'


def main():
    now = datetime.now()
    print(f'⏰ {now.isoformat()} — checking...', flush=True)

    if os.path.exists(LOCK_FILE):
        print('🔒 Lock exists — skipping')
        return

    # Read config from GitHub (source of truth) via a lightweight fetch
    token = os.environ.get('PRICE_UPDATE_TOKEN', '')
    repo = 'FIFICHECK/mms-price-update-dashboard'
    branch = 'master'
    creds_path = os.path.join(BASE_DIR, 'mms_creds.json')
    if os.path.exists(creds_path):
        try:
            import json as _j
            with open(creds_path) as f:
                _c = _j.load(f)
            repo = _c.get('github_repo', repo)
            branch = _c.get('github_branch', branch)
        except Exception:
            pass

    import requests
    hdrs = {'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'} if token else {}
    try:
        r = requests.get(f'https://api.github.com/repos/{repo}/contents/config.json?ref={branch}',
                         headers=hdrs, timeout=30)
        r.raise_for_status()
        import base64
        config = json.loads(base64.b64decode(r.json()['content']).decode())
    except Exception as e:
        print(f'❌ Config fetch failed: {e}')
        return

    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs configured')
        return

    due = []
    for sku, entry in skus.items():
        if entry.get('status') == 'completed':
            continue
        st = entry.get('scheduled_time')
        if not st:
            continue
        try:
            if now >= datetime.fromisoformat(st):
                due.append(sku)
        except Exception:
            pass

    if not due:
        print('✅ Nothing due')
        return

    print(f'🟢 {len(due)} SKU(s) due: {due}')
    # Run price_update.py with the same env
    env = dict(os.environ)
    env['PRICE_UPDATE_TOKEN'] = token
    py = os.path.join(BASE_DIR, '.venv', 'bin', 'python3')
    if not os.path.exists(py):
        py = 'python3'
    subprocess.run([py, os.path.join(BASE_DIR, 'price_update.py')], env=env, check=False)


if __name__ == '__main__':
    main()
