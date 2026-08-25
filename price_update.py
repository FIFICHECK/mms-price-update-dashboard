#!/usr/bin/env python3
"""
MMS SKU Promotional Price Update v1 — Per-SKU scheduled promo price updates.
Fills: originalPrice, sellingPrice, discountTextCh/En/Sc, discountTextStyle (RED/GREY/BLACK/BLUE).
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

# Local creds override (gitignored mms_creds.json) — supports personal instances
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
        print(f'⚙️  Using creds override: repo={GITHUB_REPO}, store={STORE_ID}')
    except Exception as e:
        print(f'⚠️  mms_creds.json read failed: {e}')

def get_token():
    return os.environ.get('PRICE_UPDATE_TOKEN', '')

DRY_RUN = os.environ.get('DRY_RUN', '') == '1'

def gh_hdrs():
    return {'Authorization': f'token {get_token()}', 'Accept': 'application/vnd.github.v3+json'}

GH_API = f'https://api.github.com/repos/{GITHUB_REPO}'

def gh_get(path):
    r = requests_get(f'{GH_API}/{path}')
    r.raise_for_status()
    return r.json()

def gh_put(path, data, sha=None):
    payload = {
        'message': 'Auto-update via price_update.py',
        'content': base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        'branch': GITHUB_BRANCH
    }
    if sha:
        payload['sha'] = sha
    r = requests_put(f'{GH_API}/{path}', headers=gh_hdrs(), json=payload)
    r.raise_for_status()
    return r.json()

def requests_get(url, **kw):
    import requests
    kw.setdefault('headers', gh_hdrs())
    return requests.get(url, timeout=30, **kw)

def requests_put(url, **kw):
    import requests
    return requests.put(url, timeout=30, **kw)

def get_config():
    info = gh_get('contents/config.json?ref=' + GITHUB_BRANCH)
    c = json.loads(base64.b64decode(info['content']).decode())
    c['_sha'] = info['sha']
    return c

def get_dashboard_data():
    try:
        info = gh_get('contents/dashboard_data.json?ref=' + GITHUB_BRANCH)
        d = json.loads(base64.b64decode(info['content']).decode())
        d['_sha'] = info['sha']
        return d
    except Exception:
        return {'history': [], '_sha': None}

def save_json(path, data):
    sha = data.pop('_sha', None)
    gh_put(f'contents/{path}', data, sha)

STYLE_VALUES = {'1': 'RED', '2': 'GREY', '3': 'BLACK', '4': 'BLUE'}
STYLE_LABELS = {'RED': 'Discount Text Style 1', 'GREY': 'Discount Text Style 2',
                'BLACK': 'Discount Text Style 3', 'BLUE': 'Discount Text Style 4'}

class MMSPriceUpdater:
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
        print('  🔑 Login...')
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
        print(f'    Fiber: {result}')
        try:
            self.page.wait_for_url('**/product-management/**', timeout=15000)
        except Exception:
            self.page.wait_for_url('**/home**', timeout=5000)
        print(f'    URL: {self.page.url}')
        print('  ✅ Logged in')

    def _fill_react_input(self, selector, value):
        """Fill a React-controlled input via native setter + input/change events."""
        if value is None:
            return False
        ok = self.page.evaluate('(args) => {' +
            'var el=document.querySelector(args.sel);if(!el)return false;' +
            'var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;' +
            'setter.call(el, args.val);' +
            'el.dispatchEvent(new Event("input",{bubbles:true}));' +
            'el.dispatchEvent(new Event("change",{bubbles:true}));' +
            'return true;' +
        '}', {'sel': selector, 'val': str(value)})
        return ok

    def _fill_react_textarea(self, selector, value):
        """Fill a React-controlled textarea via native setter + input/change events."""
        if value is None:
            return False
        ok = self.page.evaluate('(args) => {' +
            'var el=document.querySelector(args.sel);if(!el)return false;' +
            'var proto=window.HTMLTextAreaElement?window.HTMLTextAreaElement.prototype:window.HTMLElement.prototype;' +
            'var setter=Object.getOwnPropertyDescriptor(proto,"value").set;' +
            'setter.call(el, args.val);' +
            'el.dispatchEvent(new Event("input",{bubbles:true}));' +
            'el.dispatchEvent(new Event("change",{bubbles:true}));' +
            'return true;' +
        '}', {'sel': selector, 'val': str(value)})
        return ok

    def _set_discount_style(self, styles):
        """Set discountTextStyle checkbox group. styles: list of RED/GREY/BLACK/BLUE (empty list = none)."""
        if styles is None:
            return True
        # Open the select dropdown
        opened = self.page.evaluate('() => {' +
            'var sel=document.getElementById("discountTextStyle");if(!sel)return false;' +
            'var wrap=sel.closest(".ant-select");if(!wrap)return false;' +
            'var selector=wrap.querySelector(".ant-select-selector");' +
            'var r=selector.getBoundingClientRect();' +
            'var opts={bubbles:true,cancelable:true,view:window,clientX:r.x+r.width/2,clientY:r.y+r.height/2};' +
            'var inp=wrap.querySelector("input");inp.focus();' +
            'inp.dispatchEvent(new PointerEvent("pointerdown",Object.assign({pointerId:1,isPrimary:true,button:0,buttons:1,pointerType:"mouse"},opts)));' +
            'selector.dispatchEvent(new MouseEvent("mousedown",opts));' +
            'selector.dispatchEvent(new MouseEvent("mouseup",opts));' +
            'selector.dispatchEvent(new MouseEvent("click",opts));' +
            'return true;' +
        '}')
        if not opened:
            print('    ⚠️  Style select not found')
            return False
        time.sleep(1.2)
        # Click target checkboxes inside the dropdown
        clicked = self.page.evaluate('(args) => {' +
            'var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");' +
            'if(!dd)return "no dropdown";' +
            'var checks=dd.querySelectorAll("input.ant-checkbox-input");' +
            'var targets=args.styles;' +
            'for(var c of checks){' +
            '  var want=targets.includes(c.value);' +
            '  if(c.checked!==want){' +
            '    var label=c.closest("label");' +
            '    if(label){' +
            '      var r=label.getBoundingClientRect();' +
            '      var opts={bubbles:true,cancelable:true,view:window,clientX:r.x+r.width/2,clientY:r.y+r.height/2};' +
            '      label.dispatchEvent(new MouseEvent("mousedown",opts));' +
            '      label.dispatchEvent(new MouseEvent("mouseup",opts));' +
            '      label.dispatchEvent(new MouseEvent("click",opts));' +
            '      c.checked=want;' +  # optimistic set; React will confirm
            '    }' +
            '  }' +
            '}' +
            'return "ok";' +
        '}', {'styles': styles})
        time.sleep(0.8)
        # Close dropdown by pressing Escape
        self.page.keyboard.press('Escape')
        time.sleep(0.5)
        print(f'    Style: {clicked} targets={styles}')
        return 'ok' in str(clicked)

    def update_price(self, sku, phase, label=''):
        sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku
        print(f'  💰 [{label}] {sku}...')
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
            # Find edit link (last column)
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
                raise Exception(f'No edit link found for store {STORE_ID}')
            print(f'    Edit URL found')
            self.page.goto(edit_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(4)
            # Wait for price fields
            self.page.wait_for_selector('#originalPrice', timeout=20000)
            time.sleep(1)

            # 1. Original price
            if phase.get('original_price') is not None:
                self._fill_react_input('#originalPrice', phase['original_price'])
                time.sleep(0.5)
            # 2. Selling price
            if phase.get('selling_price') is not None:
                self._fill_react_input('#sellingPrice', phase['selling_price'])
                time.sleep(0.5)
            # 3-5. Discount texts
            for sel, key in [('#discountTextCh', 'discount_text_ch'),
                             ('#discountTextEn', 'discount_text_en'),
                             ('#discountTextSc', 'discount_text_sc')]:
                if phase.get(key):
                    self._fill_react_textarea(sel, phase[key])
                    time.sleep(0.4)
            # 6. Discount style (optional)
            if phase.get('discount_style') is not None:
                self._set_discount_style(phase['discount_style'])

            # Verify values were accepted (read back DOM state)
            time.sleep(0.8)
            verify = self.page.evaluate('() => {' +
                'var out={};' +
                'var op=document.getElementById("originalPrice");' +
                'var sp=document.getElementById("sellingPrice");' +
                'if(op) out.originalPrice=op.value;' +
                'if(sp) out.sellingPrice=sp.value;' +
                'var ch=document.getElementById("discountTextCh");' +
                'if(ch) out.discountTextCh=ch.value;' +
                'return JSON.stringify(out);' +
            '}')
            print(f'    Verify: {verify}')
            try:
                v = json.loads(verify)
                if phase.get('original_price') is not None and v.get('originalPrice') is not None:
                    if abs(float(v['originalPrice']) - float(phase['original_price'])) > 0.01:
                        print(f'    ⚠️  originalPrice mismatch: {v["originalPrice"]} vs {phase["original_price"]}')
                if phase.get('selling_price') is not None and v.get('sellingPrice') is not None:
                    if abs(float(v['sellingPrice']) - float(phase['selling_price'])) > 0.01:
                        print(f'    ⚠️  sellingPrice mismatch: {v["sellingPrice"]} vs {phase["selling_price"]}')
            except Exception as e:
                print(f'    ⚠️  verify parse: {e}')

            # Save — scroll to bottom and click 完 成 (or 取 消 in dry-run)
            time.sleep(1)
            btn_label = '取 消' if DRY_RUN else '完 成'
            clicked = self.page.evaluate('(args) => {' +
                'var bs=document.querySelectorAll("button");' +
                'for(var x of bs){' +
                '  if(x.innerText.trim()===args.lbl){x.scrollIntoView({block:"center"});x.click();return true;}' +
                '}' +
                'return false;' +
            '}', {'lbl': btn_label})
            print(f'    {btn_label} btn: {clicked}')
            time.sleep(4)
            # Verify: either redirected back to product-list or success message
            url = self.page.url
            print(f'    After URL: {url}')
            return True
        except Exception as e:
            print(f'    ❌ {e}')
            return False

    def run(self, actions):
        if not actions:
            return []
        self.start()
        results = []
        try:
            self.login()
            for sku, phase, label in actions:
                ok = self.update_price(sku, phase, label)
                results.append({'sku': sku, 'label': label, 'success': ok,
                                'fields': {k: v for k, v in phase.items() if k not in ('time', 'label')}})
                time.sleep(2)
        finally:
            self.stop()
        return results

def main():
    print('💰 MMS Price Update v1 — Checking schedules...')
    now = datetime.now()
    print(f'⏰ {now.isoformat()}')

    config = get_config()
    skus = config.get('skus', {})
    if not skus:
        print('✅ No SKUs')
        return

    # Auto-fetch missing product names
    for sku, entry in skus.items():
        if not entry.get('product_name'):
            try:
                sku_id = sku.split('_S_')[-1] if '_S_' in sku else sku
                r = requests_get(f'https://www.hktvmall.com/hktv/p/{sku_id}', headers={'User-Agent': 'Mozilla/5.0'})
                if r.ok:
                    m = re.search(r'<title>([^<]+)</title>', r.text)
                    if m:
                        nm = m.group(1).split('|')[0].strip()
                        config['skus'][sku]['product_name'] = nm
                        print(f'  📝 {sku}: {nm}')
            except Exception as e:
                print(f'  ⚠️  {sku}: name fetch: {e}')

    actions = []
    for sku, entry in skus.items():
        status = entry.get('status', 'pending')
        if status == 'completed':
            print(f'  ⏭️  {sku}: completed')
            continue
        phases = entry.get('phases', [])
        if not phases:
            print(f'  ⏳ {sku}: no phases')
            continue
        current_phase = entry.get('current_phase', -1)
        next_phase = -1
        for i in range(current_phase + 1, len(phases)):
            p = phases[i]
            if not p.get('time'):
                continue
            try:
                if now >= datetime.fromisoformat(p['time']):
                    # Skip if past its end_time (promo window already over)
                    if p.get('end_time'):
                        try:
                            if now > datetime.fromisoformat(p['end_time']):
                                continue
                        except Exception:
                            pass
                    next_phase = i
                    break
            except Exception:
                pass
        if next_phase >= 0:
            p = phases[next_phase]
            print(f'  🟢 {sku}: Phase {next_phase+1} [{p.get("label","")}] ({p.get("time","")})')
            actions.append((sku, p, p.get('label', f'Phase {next_phase+1}')))
            config['skus'][sku]['_next_phase'] = next_phase
        else:
            for i in range(current_phase + 1, len(phases)):
                p = phases[i]
                if p.get('time'):
                    try:
                        pt = datetime.fromisoformat(p['time'])
                        if pt > now:
                            mins = int((pt - now).total_seconds() / 60)
                            print(f'  ⏳ {sku}: Phase {i+1} in {mins} min [{p.get("label","")}]')
                            break
                    except Exception:
                        pass

    if not actions:
        print('✅ No actions needed')
        return

    print(f'\n📦 {len(actions)} phase(s) to update')
    updater = MMSPriceUpdater()
    results = updater.run(actions)

    for r in results:
        sku = r['sku']
        ok = r['success']
        if sku in config['skus'] and not DRY_RUN:
            if ok:
                np = config['skus'][sku].pop('_next_phase', -1)
                config['skus'][sku]['current_phase'] = np
                config['skus'][sku]['last_updated'] = now.isoformat()
                if np >= len(config['skus'][sku].get('phases', [])) - 1:
                    config['skus'][sku]['status'] = 'completed'
                else:
                    config['skus'][sku]['status'] = 'active'
            else:
                config['skus'][sku]['status'] = 'failed'

    dashboard = get_dashboard_data()
    if 'history' not in dashboard:
        dashboard['history'] = []
    for r in results:
        dashboard['history'].append({
            'sku': r['sku'],
            'label': r.get('label', ''),
            'fields': r.get('fields', {}),
            'status': 'success' if r['success'] else 'failed',
            'time': now.isoformat()
        })
    dashboard['history'] = dashboard['history'][-500:]

    # Save with fresh SHA
    config.pop('_sha', None)
    try:
        info = gh_get('contents/config.json?ref=' + GITHUB_BRANCH)
        config['_sha'] = info['sha']
    except Exception:
        pass
    save_json('config.json', config)
    save_json('dashboard_data.json', dashboard)
    print('✅ All saved!')

if __name__ == '__main__':
    main()
