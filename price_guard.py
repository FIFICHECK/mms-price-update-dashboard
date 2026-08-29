#!/usr/bin/env python3
"""
MMS Promo Price Guard — monitor HKTVmall real displayed price for promo SKUs.

For each SKU with an ACTIVE promo phase (promo_done, not yet reverted, end_time in future):
  - fetch https://www.hktvmall.com/hktv/p/{store_sku}
  - parse the DISCOUNT price (or selling_price fallback)
  - if real price != expected selling_price → the promo contract dropped → re-run promo via price_update.py

Exit codes (for cron):
  0 = all good / nothing to do (silent)
  1 = drift detected, re-promo triggered (or attempted)
  2 = error (fetch/parse) — reported so it isn't silently missed
"""
import os, re, sys, json, time, subprocess, contextlib, io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def get_config():
    # Suppress import-time prints (e.g. "Using creds override") so normal runs stay silent
    with contextlib.redirect_stdout(io.StringIO()):
        from price_update import get_config as _g
        cfg = _g()
    return cfg

def fetch_price(sku_id, store_sku):
    """Return current HKTVmall display price for the SKU, or None on failure."""
    url = f'https://www.hktvmall.com/hktv/p/{store_sku}'
    import requests
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}, timeout=30)
    if not r.ok:
        print(f'⚠️  fetch {url}: HTTP {r.status_code}', flush=True)
        return None
    text = r.text
    # Preferred: structured DISCOUNT price
    m = re.search(r'"value"\s*:\s*([\d.]+)\s*,\s*"priceType"\s*:\s*"DISCOUNT"', text)
    if m:
        return float(m.group(1))
    # Fallback: data-price attribute on PDP root
    m = re.search(r'data-price="\$?\s*([\d.]+)"', text)
    if m:
        return float(m.group(1))
    # Fallback: title/price JSON
    m = re.search(r'"price"\s*:\s*"?([\d.]+)', text)
    if m:
        return float(m.group(1))
    return None

def main():
    now = time.time()
    config = get_config()
    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs')
        return 0

    problems = []
    errors = []
    for store_sku, entry in skus.items():
        # Only guard SKUs with an active promo (promo_done, not reverted, end_time future)
        # NOTE: verify_skip SKUs are STILL guarded here — verify_skip only silences the
        # MMS-edit-page drift monitor (contract-locked SKUs show locked price there);
        # the HKTVmall real-price guard is exactly for those SKUs.
        phases = entry.get('phases', [])
        for i, ph in enumerate(phases):
            if not ph.get('promo_done') or ph.get('revert_done'):
                continue
            end_time = ph.get('end_time')
            if end_time:
                try:
                    from datetime import datetime
                    end_ts = datetime.fromisoformat(end_time.replace('Z', '+00:00')).timestamp()
                except Exception:
                    end_ts = 0
                if now > end_ts:
                    continue  # past end → normal revert flow handles it
            selling = ph.get('selling_price')
            if selling is None:
                continue
            sku_id = store_sku.split('_S_')[-1] if '_S_' in store_sku else store_sku
            real = fetch_price(sku_id, store_sku)
            if real is None:
                errors.append(store_sku)
                continue
            if abs(real - float(selling)) <= 0.01:
                # silent on match (no_agent cron: empty stdout = no delivery)
                pass
            else:
                print(f'🔴 {store_sku}: HKTVmall real = ${real} ≠ expected ${selling} — promo dropped!', flush=True)
                problems.append((store_sku, real, selling))

    if errors:
        print(f'⚠️  fetch/parse failed for: {", ".join(errors)}', flush=True)
        return 2

    if not problems:
        # all good → silent (no_agent cron delivers nothing on empty stdout)
        return 0

    print('', flush=True)
    print('⚠️  **PROMO PRICE DROPPED — re-applying promo**', flush=True)
    for sku, real, sell in problems:
        print(f'  {sku}: ${real} → ${sell}', flush=True)
    # Re-run the main updater (it will re-apply the promo for due phases)
    env = dict(os.environ)
    r = subprocess.run([sys.executable, os.path.join(BASE_DIR, 'price_update.py')],
                       capture_output=True, text=True, timeout=240, env=env)
    print(r.stdout[-2000:], flush=True)
    if r.returncode != 0:
        print(f'❌ price_update.py exited {r.returncode}: {r.stderr[-800:]}', flush=True)
        return 1
    print('✅ Promo re-applied', flush=True)
    return 1  # non-zero so cron log captures the action

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'❌ price guard error: {e}', flush=True)
        sys.exit(2)
