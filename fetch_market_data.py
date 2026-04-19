#!/usr/bin/env python3
"""
Auto-fetch market data for the Marks Cycle Deck dashboard.
Runs as a GitHub Actions step; patches index.html in-place.

Data sources:
  - Index level + YTD : Yahoo Finance v8 spark API (free, no key)
  - TTM PE            : worldperatio.com (HTML parse, no key)
  - CAPE              : multpl.com/shiller-pe (HTML parse, no key)
  - Fear & Greed      : api.alternative.me/fng/ (free JSON API)
"""

import re, sys, json, time, datetime
import urllib.request, urllib.error, urllib.parse
from urllib.parse import quote as urlquote

UA = "Mozilla/5.0 (compatible; MarksDataBot/1.0)"

def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def safe_float(v, default=None):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except Exception:
        return default

# ─────────────────────────────────────────────
# 1. Yahoo Finance — index levels + YTD change
# ─────────────────────────────────────────────
TICKERS = {
    "us": "^GSPC",
    "sg": "^STI",
    "hk": "^HSI",
    "jp": "^N225",
    "my": "^KLSE",
    "cn": "000905.SS",
}

def fetch_yahoo(ticker):
    """Return (current_price, ytd_pct) via Yahoo Finance v8 spark."""
    url = (
        "https://query2.finance.yahoo.com/v8/finance/spark"
        f"?symbols={urlquote(ticker)}&range=ytd&interval=1d"
    )
    try:
        raw = get(url)
        data = json.loads(raw)
        spark = data["spark"]["result"][0]["response"][0]
        closes = spark["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if not closes:
            return None, None
        current = round(closes[-1], 2)
        ytd_pct = round((closes[-1] / closes[0] - 1) * 100, 1)
        return current, ytd_pct
    except Exception as e:
        print(f"  ⚠ Yahoo {ticker}: {e}")
        return None, None

# ─────────────────────────────────────────────
# 2. worldperatio.com — TTM PE per market
# ─────────────────────────────────────────────
WORLDPE_URLS = {
    "us": "https://worldperatio.com/index/sp-500/",
    "sg": "https://worldperatio.com/area/singapore/",
    "hk": "https://worldperatio.com/area/hong-kong/",
    "jp": "https://worldperatio.com/area/japan/",
    "my": "https://worldperatio.com/area/malaysia/",
    "cn": "https://worldperatio.com/area/china/",
}

def fetch_worldpe(market_id):
    """Scrape current PE + 5Y/10Y averages from worldperatio.com."""
    url = WORLDPE_URLS[market_id]
    try:
        html = get(url)
        # Primary: <b class="w3-text-black -f14">16.13</b>
        # The page repeats the current PE multiple times; grab first occurrence
        # which follows "P/E Ratio:" label
        current_pe = None
        pe5y = None
        pe10y = None

        # Current PE: appears after "P/E Ratio:" in the timeline row
        m = re.search(
            r'P/E Ratio:\s*<b[^>]*>([\d.]+)</b>',
            html, re.IGNORECASE
        )
        if m:
            current_pe = safe_float(m.group(1))

        # Fallback: "is <b>XX.XX</b>, calculated"
        if not current_pe:
            m = re.search(
                r'is\s*<b>([\d.]+)</b>,\s*calculated',
                html, re.IGNORECASE
            )
            if m:
                current_pe = safe_float(m.group(1))

        # 5Y average: appears after "5Y Average:"
        m5 = re.search(
            r'5Y Average:\s*<b[^>]*>([\d.]+)</b>',
            html, re.IGNORECASE
        )
        if m5:
            pe5y = safe_float(m5.group(1))

        # 10Y average: appears after "10Y Average:"
        m10 = re.search(
            r'10Y Average:\s*<b[^>]*>([\d.]+)</b>',
            html, re.IGNORECASE
        )
        if m10:
            pe10y = safe_float(m10.group(1))

        return current_pe, pe5y, pe10y
    except Exception as e:
        print(f"  ⚠ worldperatio {market_id}: {e}")
    return None, None, None

# ─────────────────────────────────────────────
# 3. multpl.com — S&P 500 Shiller CAPE
# ─────────────────────────────────────────────
def fetch_cape():
    try:
        html = get("https://www.multpl.com/shiller-pe")
        # <div id="current-value">40.44</div>  OR  Current Shiller PE Ratio is XX.XX
        patterns = [
            r'id="current-value"[^>]*>\s*([\d.]+)',
            r'Current Shiller PE Ratio is\s*([\d.]+)',
            r'shiller.pe.*?is\s*([\d.]+)',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                val = safe_float(m.group(1))
                if val and 5 < val < 100:
                    return val
    except Exception as e:
        print(f"  ⚠ CAPE (multpl): {e}")
    return None

# ─────────────────────────────────────────────
# 4. alternative.me — Crypto Fear & Greed
#    (Best public proxy for general sentiment;
#     CNN F&G has no public API)
# ─────────────────────────────────────────────
def fetch_fng():
    try:
        raw = get("https://api.alternative.me/fng/?limit=1")
        data = json.loads(raw)
        val = int(data["data"][0]["value"])
        return val
    except Exception as e:
        print(f"  ⚠ Fear & Greed: {e}")
    return None

# ─────────────────────────────────────────────
# 5. Patch index.html
# ─────────────────────────────────────────────
import urllib.parse

def patch_field(html, market_id, field, new_val, is_string=False):
    """Replace a JS object field value for a specific market."""
    if new_val is None:
        return html, False

    if is_string:
        new_str = f"'{new_val}'"
    else:
        new_str = str(new_val)

    # Match:  field: <value>,   inside the market object block
    # Strategy: locate the id: 'market_id' block, then replace field within next 2000 chars
    id_pat = re.compile(rf"id:\s*'{re.escape(market_id)}'")
    m = id_pat.search(html)
    if not m:
        print(f"  ⚠ Market block '{market_id}' not found")
        return html, False

    block_start = m.start()
    # Find the closing } of this market object
    block_end = html.find("\n    }", block_start) + 6
    block = html[block_start:block_end]

    field_pat = re.compile(rf"({re.escape(field)}:\s*)([^,\n]+)(,?)")
    new_block, count = field_pat.subn(rf"\g<1>{new_str}\g<3>", block, count=1)

    if count == 0:
        print(f"  ⚠ Field '{field}' not found in '{market_id}' block")
        return html, False

    return html[:block_start] + new_block + html[block_end:], True


def patch_updateDate(html, date_str):
    html = re.sub(r"(updateDate:\s*')[^']+'", rf"\g<1>{date_str}'", html)
    return html


def main():
    print(f"\n{'='*55}")
    print(f"  Marks Cycle Deck — Data Fetch  {datetime.date.today()}")
    print(f"{'='*55}\n")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    today = str(datetime.date.today())
    changes = 0

    # ── Index levels + YTD ──────────────────────
    print("📊 Fetching index levels (Yahoo Finance)…")
    for mid, ticker in TICKERS.items():
        level, ytd = fetch_yahoo(ticker)
        time.sleep(0.4)
        if level:
            html, ok = patch_field(html, mid, "level", level)
            if ok: print(f"  ✓ {mid} level = {level:,.0f}")
            changes += ok
        if ytd is not None:
            html, ok = patch_field(html, mid, "ytd", ytd)
            if ok: print(f"  ✓ {mid} ytd   = {ytd:+.1f}%")
            changes += ok

    # ── TTM PE + 5Y/10Y averages ─────────────────
    print("\n📈 Fetching TTM PE + 5Y/10Y avg (worldperatio.com)…")
    for mid in TICKERS:
        pe, pe5y, pe10y = fetch_worldpe(mid)
        time.sleep(1.5)
        if pe:
            html, ok = patch_field(html, mid, "ttmPE", round(pe, 2))
            if ok: print(f"  ✓ {mid} ttmPE = {pe:.2f}×")
            changes += ok
        else:
            print(f"  – {mid} ttmPE: no data, keeping existing")
        if pe5y:
            html, ok = patch_field(html, mid, "pe5y", round(pe5y, 2))
            if ok: print(f"  ✓ {mid} pe5y  = {pe5y:.2f}×")
            changes += ok
        if pe10y:
            html, ok = patch_field(html, mid, "pe10y", round(pe10y, 2))
            if ok: print(f"  ✓ {mid} pe10y = {pe10y:.2f}×")
            changes += ok

    # ── CAPE (US only) ───────────────────────────
    print("\n🔢 Fetching CAPE (multpl.com)…")
    cape = fetch_cape()
    if cape:
        html, ok = patch_field(html, "us", "cape", cape)
        if ok: print(f"  ✓ us CAPE = {cape:.1f}")
        changes += ok
    else:
        print("  – CAPE: no data, keeping existing")

    # ── Fear & Greed ─────────────────────────────
    print("\n😱 Fetching Fear & Greed (alternative.me)…")
    fgi = fetch_fng()
    if fgi is not None:
        html, ok = patch_field(html, "us", "fgi", fgi)
        if ok: print(f"  ✓ us FGI  = {fgi}")
        changes += ok
    else:
        print("  – FGI: no data, keeping existing")

    # ── Update date ──────────────────────────────
    html = patch_updateDate(html, today)
    print(f"\n📅 updateDate → {today}")

    # ── Write back ───────────────────────────────
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Done — {changes} fields updated in index.html")

    # Output summary for Actions step
    summary = {
        "date": today,
        "fields_updated": changes,
    }
    with open("fetch_summary.json", "w") as f:
        json.dump(summary, f)

if __name__ == "__main__":
    main()
