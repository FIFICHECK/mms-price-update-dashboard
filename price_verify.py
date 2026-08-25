#!/usr/bin/env python3
"""
MMS Price Verify — checks that MMS promo prices still match config (drift detection).
If someone changed originalPrice/sellingPrice during the promo period, prints a notice
(no_agent cron delivers it). Silent when everything matches.
"""
import os, sys, json, base64, time, re
from datetime import datetime
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GITHUB_REPO = 'FIFICHECK/mms-price-update-dashboard'
GITHUB_BRANCH = 'master'
MMS_EMAIL = '***REMOVED_EMAIL***'
MMS_PASSWORD = '***REMOVED_PASSWORD***!!!'
STORE_ID = 'B0961005'

_creds_path = os.path.join(BASE_DIR, 'mms_creds.json')
if os.path.exists(_creds_path):
    try:
        with open(_creds_path) as f:
            _c = json.load(f)
        GITHUB_REPO = _c.get('github_repo', GITHUB_REPO)
        GITHUB_BRANCH = _c.get('github_branch', GITHUB_BRANCH)
        MMS_EMAIL = _c.get('mms_email', MMS_EMAIL)
        MMS_PASSWORD = _c.get('mms_password', MMS_PASSWORD)
        STORE_ID = _c.get('store_id', STORE_ID)
    except Exception:
        pass

def get_token():
    return os.environ.get('PRICE_UPDATE_TOKEN', '')

def gh_hdrs():
    return {'Authorization': f'token {get_token()}', 'Accept': 'application/vnd.github.v3+json'}

def get_config():
    import requests
    r = requests.get(f'https://api.github.com/repos/{GITHUB_REPO}/contents/config.json?ref={GITHUB_BRANCH}',
                     headers=gh_hdrs(), timeout=30)
    r.raise_for_status()
    return json.loads(base64.b64decode(r.json()['content']).decode())

class MMSPriceVerifier:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.page = None

    def start(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page()
        self.page.set_viewport_size({'width': 1920, 'height': 1080})

    def stop(self):
        try: self.browser.close()
        except Exception: pass
        try: self.pw.stop()
        except Exception: pass

    def login(self):
        self.page.goto('https://merchant.shoalter.com/login', wait_until='networkidle')
        time.sleep(3)
        self.page.fill('input[placeholder="請輸入ID"]', MMS_EMAIL)
        self.page.fill('input[placeholder="請輸入密碼"]', MMS_PASSWORD)
        time.sleep(1)
        result = self.page.evaluate('(args) => {' +
            'var f=document.querySelector("form");if(!f)return"no form";' +
            'var k=Object.keys(f).find(k=>k.startsWith("__reactFiber")||k.startsWith("__reactInternalInstance"));' +
            'if(!k)return"no react fiber";var x=f[k];while(x){' +
            'var m=x.memoizedProps;' +
            'if(m&&m.onFinish){m.onFinish({account:args.e,password:args.p});return"ok";}x=x.return;}return"no onFinish";' +
        '}', {'e': MMS_EMAIL, 'p': MMS_PASSWORD})
        print(f'    Fiber: {result}', flush=True)
        try:
            self.page.wait_for_url('**/product-management/**', timeout=15000)
        except Exception:
            self.page.wait_for_url('**/home**', timeout=5000)
        return result == 'ok'

    def read_prices(self, sku):
        """Navigate to edit page and read current originalPrice/sellingPrice."""
        sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku
        try:
            self.page.goto('https://merchant.shoalter.com/product-management/product-list', wait_until='load', timeout=45000)
            time.sleep(3)
            inp = self.page.query_selector('input[placeholder="搜尋 SKU ID"]')
            if not inp:
                inp = self.page.query_selector('input.ant-input')
            if not inp:
                raise Exception('Search input not found')
            inp.fill('')
            inp.fill(sku_id)
            time.sleep(1)
            inp.press('Enter')
            time.sleep(4)
            edit_url = self.page.evaluate('(s) => {' +
                'var rows=document.querySelectorAll("table:nth-child(2) tr.ant-table-row, table tr.ant-table-row");' +
                'for(var r of rows){' +
                '  var c=r.querySelectorAll("td");' +
                '  if(c.length>=8){' +
                '    if(c[3]&&c[3].innerText.trim()===s){' +
                '      var links=c[c.length-1]?c[c.length-1].querySelectorAll("a"):null;' +
                '      if(links&&links.length>0) return links[0].href;' +
                '    }' +
                '  }' +
                '}' +
                'return null;' +
            '}', STORE_ID)
            if not edit_url:
                return None, f'no edit link (store {STORE_ID})'
            self.page.goto(edit_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(4)
            self.page.wait_for_selector('#originalPrice', timeout=20000)
            time.sleep(1)
            vals = self.page.evaluate('() => {' +
                'var out={};' +
                'var op=document.getElementById("originalPrice");if(op)out.originalPrice=op.value;' +
                'var sp=document.getElementById("sellingPrice");if(sp)out.sellingPrice=sp.value;' +
                'return JSON.stringify(out);' +
            '}')
            v = json.loads(vals)
            return v, None
        except Exception as e:
            return None, str(e)

def num(v):
    if v is None or v == '':
        return None
    try:
        return round(float(v), 2)
    except Exception:
        return None

def main():
    now = datetime.now()
    print(f'⏰ {now.isoformat()} — price verify check...', flush=True)

    try:
        config = get_config()
    except Exception as e:
        print(f'❌ Config fetch failed: {e}', flush=True)
        return

    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs configured', flush=True)
        return

    # Select SKUs to verify: completed (already updated) AND (no verify_until OR verify_until >= today)
    today = now.date().isoformat()
    targets = {}
    for sku, entry in skus.items():
        if entry.get('status') != 'completed':
            continue
        vu = entry.get('verify_until')
        if vu and vu < today:
            continue
        targets[sku] = entry

    if not targets:
        print('✅ No completed SKUs to verify', flush=True)
        return

    print(f'🔍 Verifying {len(targets)} SKU(s)...', flush=True)
    verifier = MMSPriceVerifier()
    drifts = []
    errors = []
    try:
        verifier.start()
        if not verifier.login():
            print('❌ MMS login failed', flush=True)
            return
        for sku, entry in targets.items():
            print(f'  👀 {sku}...', flush=True)
            vals, err = verifier.read_prices(sku)
            if err:
                errors.append((sku, err))
                print(f'    ⚠️  {err}', flush=True)
                continue
            op_now = num(vals.get('originalPrice'))
            sp_now = num(vals.get('sellingPrice'))
            op_cfg = num(entry.get('original_price'))
            sp_cfg = num(entry.get('selling_price'))
            changed = []
            if op_cfg is not None and op_now is not None and abs(op_now - op_cfg) > 0.01:
                changed.append(('原價', op_cfg, op_now))
            if sp_cfg is not None and sp_now is not None and abs(sp_now - sp_cfg) > 0.01:
                changed.append(('售價', sp_cfg, sp_now))
            if changed:
                drifts.append((sku, entry, changed))
                print(f'    ⚠️  DRIFT: {changed}', flush=True)
            else:
                print(f'    ✅ OK (orig={op_now}, sell={sp_now})', flush=True)
            time.sleep(2)
    finally:
        verifier.stop()

    # Output — only print when drift found (no_agent cron delivers stdout)
    if not drifts:
        print('✅ All prices match', flush=True)
        return

    print('', flush=True)
    print('⚠️  **MMS 價格變更偵測**', flush=True)
    print(f'📅 檢查時間: {now.strftime("%Y-%m-%d %H:%M")}', flush=True)
    print('', flush=True)
    for sku, entry, changed in drifts:
        name = entry.get('product_name', '')
        print(f'**{sku}**', flush=True)
        if name:
            print(f'  📦 {name}', flush=True)
        print(f'  ⏰ 原排程時間: {entry.get("scheduled_time", "—")}', flush=True)
        for label, cfg_val, now_val in changed:
            print(f'  ⚠️  {label}: ${cfg_val} → ${now_val}（被人改過！）', flush=True)
        print('', flush=True)
    print('💡 如需修正，請喺 dashboard 更新該 SKU 嘅價格或改 scheduled_time 重新執行。', flush=True)

    # Also print errors if any (so failures are visible)
    if errors:
        print('⚠️ 以下 SKU 檢查失敗:', flush=True)
        for sku, err in errors:
            print(f'  - {sku}: {err}', flush=True)

if __name__ == '__main__':
    main()
