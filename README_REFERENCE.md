# MMS SKU Promotional Price Update Dashboard — reference

## Repo / Site
- Repo: `FIFICHECK/mms-price-update-dashboard` (branch `master`)
- Pages: https://fificheck.github.io/mms-price-update-dashboard/
- Cron: `mms-price-scheduler` (job 89a5e704059e, `*/15 * * * *`, no_agent → `mms_price_check.sh` → `schedule_prices.py` → `price_update.py`)
- Local: `~/mms-price-update-dashboard/` (.venv with playwright+chromium)
- Wrappers: `~/.hermes/profiles/hermes1/scripts/mms_price_check.sh` (cron), `mms_price_run.sh` (one-shot)

## MMS Promo Fields (edit-product page, verified 2026-08-25)
| Field | DOM | Notes |
|-------|-----|-------|
| 原價 (港幣) | `#originalPrice` (ant-input-number input) | fill via React native setter + input/change events |
| 售價 (港幣) | `#sellingPrice` | `0` = cancel promo |
| 折扣文字 繁 | `#discountTextCh` textarea | |
| 折扣文字 英 | `#discountTextEn` textarea | |
| 折扣文字 簡 | `#discountTextSc` textarea | |
| 折扣文字格式 | `#discountTextStyle` ant-select wrapping a **checkbox group** | values: `""`(none) `RED`=Style1 `GREY`=Style2 `BLACK`=Style3 `BLUE`=Style4; multi-select; open via pointer events on `.ant-select-selector` + dropdown `input.ant-checkbox-input` clicks |
| Save | 頁面底部「完 成」掣 | scrollIntoView + click |
| Cancel | 「取 消」掣 | DRY_RUN uses this |

## Key techniques (ported from bubble-photos-dashboard)
- MMS login: React fiber `onFinish({account, password})` bypasses bot detection
- Search: fill `input[placeholder="搜尋 SKU ID"]` with sku_id (part after `_S_`), press Enter
- Edit URL: table rows `tr.ant-table-row`, `c[3].innerText === STORE_ID` (商店編號), edit link = `c[c.length-1]` first `a`
- product-list nav: `wait_until='load'` (never networkidle); edit page: `wait_until='domcontentloaded'`
- React-controlled inputs: native setter + `input`/`change` events (NOT plain `fill()` which may be ignored by ant-input-number)
- Config/Data via GitHub API with SHA retry; token env `PRICE_UPDATE_TOKEN` (falls back to `~/.config/gh/hosts.yml` oauth_token)
- Creds override: gitignored `mms_creds.json` keys `github_repo/github_branch/mms_email/mms_password/store_id`

## Config shape
```json
{"skus": {"B0961005_S_4891133140895_24": {
  "product_name": "...", "original_price": 159.9, "selling_price": 63.9,
  "discount_text_ch": "...", "discount_text_en": "...", "discount_text_sc": "...",
  "discount_style": ["RED"], "scheduled_time": "2026-08-25T12:00:00",
  "status": "pending", "last_updated": ""}}}
```
Status lifecycle: pending → completed (success) / failed (retry by editing scheduled_time back to past).

## DRY_RUN
`DRY_RUN=1 .venv/bin/python3 price_update.py` — runs full flow but clicks 取 消 instead of 完 成 (never saves). Use before any real run.

## Pitfalls
- JS events on ant-select dropdown need real pointer/mouse sequence (mousedown→mouseup→click); keyboard ArrowDown alone won't open it.
- `page.evaluate` accepts ONE extra arg — pass a dict.
- MMS session expires; always re-login via fiber.
- raw.githubusercontent CDN lags after push — verify via GitHub API contents.
- 完 成 click triggers save; after save the page may redirect to product-list — treat as success.
