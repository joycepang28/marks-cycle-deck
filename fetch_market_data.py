#!/usr/bin/env python3
"""
Auto-fetch market data for the Marks Cycle Deck dashboard.
Patches DEFAULT_DATA values in index.html in-place.

Data sources:
  - Index level (US/HK/JP/SG) : CNBC quote API
  - Index level (MY)           : i3investor.com (klse)
  - Index level (CN)           : Eastmoney push2 API
  - YTD %                      : Eastmoney kline API (year-start close)
  - TTM PE + 5Y/10Y avg        : worldperatio.com (HTML parse)
  - CAPE                       : multpl.com/shiller-pe (HTML parse)
  - Fear & Greed               : api.alternative.me/fng/ (free JSON API)
"""

import re, json, time, datetime
import urllib.request, urllib.parse, urllib.error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"

def get(url, timeout=20, accept="text/html,*/*"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def safe_float(v, default=None):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default

# ─────────────────────────────────────────────
# 1. CNBC — index level for US/SG/HK/JP
# ─────────────────────────────────────────────
CNBC_SYMBOLS = {
    "us": ".SPX",    # S&P 500
    "sg": ".STI",    # Straits Times Index
    "hk": ".HSI",    # Hang Seng Index
    "jp": ".N225",   # Nikkei 225
}

def fetch_cnbc(symbol):
    """Return current index level from CNBC quote page."""
    url = f"https://www.cnbc.com/quotes/{symbol}"
    try:
        raw = get(url)
        m = re.search(r'"last":\s*"?([\d,\.]+)"?', raw)
        if m:
            return safe_float(m.group(1))
    except Exception as e:
        print(f"  ⚠ CNBC {symbol}: {e}")
    return None

# ─────────────────────────────────────────────
# 2. Eastmoney — index level for CN
#    and year-start close for all markets (YTD)
# ─────────────────────────────────────────────
# secid format: {market}.{code}
# 1=SH, 0=SZ; 100=US indices, 116=HK, foreign markets
EASTMONEY_SECIDS = {
    "cn":  "1.000905",   # CSI 500
    "us":  "100.SPX",    # S&P 500 (YTD only)
    "sg":  "100.STI",    # STI (YTD only)
    "hk":  "100.HSI",    # HSI (YTD only)
    "jp":  "100.N225",   # Nikkei 225 (YTD only)
}

def fetch_eastmoney_level(secid):
    """Return current index level from Eastmoney."""
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f57,f58,f60,f169,f170"
    try:
        raw = get(url, accept="application/json,*/*")
        data = json.loads(raw)
        d = data.get("data")
        if not d:
            return None
        f43 = d.get("f43")
        if f43 is not None:
            # eastmoney returns price * 100
            return round(float(f43) / 100, 2)
    except Exception as e:
        print(f"  ⚠ Eastmoney level {secid}: {e}")
    return None

def fetch_eastmoney_yearstart(secid):
    """Return first available close of the current year from Eastmoney kline API."""
    year = datetime.date.today().year
    beg = f"{year}0101"
    end = f"{year}0115"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56"
        f"&klt=101&fqt=0&beg={beg}&end={end}"
    )
    try:
        raw = get(url, accept="application/json,*/*")
        data = json.loads(raw)
        klines = (data.get("data") or {}).get("klines", [])
        if klines:
            # kline format: date,open,close,high,low,vol,...
            parts = klines[0].split(",")
            return safe_float(parts[2])  # close price
    except Exception as e:
        print(f"  ⚠ Eastmoney yearstart {secid}: {e}")
    return None

# ─────────────────────────────────────────────
# 3. i3investor.com — MY KLCI current level
# ─────────────────────────────────────────────
def fetch_my_klci():
    """Return current FBM KLCI level from i3investor."""
    url = "https://klse.i3investor.com/web/index/market-index"
    try:
        raw = get(url)
        # Pattern: <strong>1,695.21</strong> near FBM KLCI
        idx = raw.find("FBM KLCI")
        if idx < 0:
            idx = raw.find("KLCI")
        if idx >= 0:
            segment = raw[max(0, idx-500):idx+500]
            m = re.search(r'<strong>([\d,\.]+)</strong>', segment)
            if m:
                return safe_float(m.group(1))
    except Exception as e:
        print(f"  ⚠ MY KLCI (i3investor): {e}")
    return None

def fetch_my_yearstart():
    """Estimate MY KLCI year-start from Eastmoney (best available)."""
    # Try eastmoney with KLSE — may not be available
    # Fallback: use known approximate value
    for secid in ["104.KLSE", "105.KLSE", "106.KLSE"]:
        val = fetch_eastmoney_yearstart(secid)
        if val:
            return val
    return None

# ─────────────────────────────────────────────
# 4. worldperatio.com — TTM PE + 5Y/10Y avg
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
    """Return (ttm_pe, pe5y, pe10y) from worldperatio.com."""
    url = WORLDPE_URLS[market_id]
    try:
        html = get(url)
        current_pe = None
        m = re.search(r'P/E Ratio:\s*<b[^>]*>([\d.]+)</b>', html, re.IGNORECASE)
        if m:
            current_pe = safe_float(m.group(1))
        if not current_pe:
            m = re.search(r'is\s*<b>([\d.]+)</b>,\s*calculated', html, re.IGNORECASE)
            if m:
                current_pe = safe_float(m.group(1))
        pe5y = None
        m5 = re.search(r'5Y Average:\s*<b[^>]*>([\d.]+)</b>', html, re.IGNORECASE)
        if m5:
            pe5y = safe_float(m5.group(1))
        pe10y = None
        m10 = re.search(r'10Y Average:\s*<b[^>]*>([\d.]+)</b>', html, re.IGNORECASE)
        if m10:
            pe10y = safe_float(m10.group(1))
        return current_pe, pe5y, pe10y
    except Exception as e:
        print(f"  ⚠ worldperatio {market_id}: {e}")
    return None, None, None

# ─────────────────────────────────────────────
# 5. multpl.com — Shiller CAPE (US only)
# ─────────────────────────────────────────────
def fetch_cape():
    try:
        html = get("https://www.multpl.com/shiller-pe")
        for pat in [
            r'id="current-value"[^>]*>\s*([\d.]+)',
            r'Current Shiller PE Ratio is\s*([\d.]+)',
        ]:
            m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                val = safe_float(m.group(1))
                if val and 5 < val < 100:
                    return val
    except Exception as e:
        print(f"  ⚠ CAPE (multpl): {e}")
    return None

# ─────────────────────────────────────────────
# 6. alternative.me — Fear & Greed Index
# ─────────────────────────────────────────────
def fetch_fng():
    try:
        raw = get("https://api.alternative.me/fng/?limit=1", accept="application/json,*/*")
        data = json.loads(raw)
        return int(data["data"][0]["value"])
    except Exception as e:
        print(f"  ⚠ Fear & Greed: {e}")
    return None

# ─────────────────────────────────────────────
# 7. Patch index.html DEFAULT_DATA in-place
# ─────────────────────────────────────────────
def patch_field(html, market_id, field, new_val):
    """Replace a numeric JS field inside the market object block."""
    if new_val is None:
        return html, False
    id_pat = re.compile(rf"id:\s*'{re.escape(market_id)}'")
    m = id_pat.search(html)
    if not m:
        return html, False
    block_start = m.start()
    block_end = html.find("\n    }", block_start) + 6
    block = html[block_start:block_end]
    field_pat = re.compile(rf"({re.escape(field)}:\s*)([^,\n]+)(,?)")
    new_block, count = field_pat.subn(rf"\g<1>{new_val}\g<3>", block, count=1)
    if count == 0:
        return html, False
    return html[:block_start] + new_block + html[block_end:], True

def patch_update_date(html, date_str):
    return re.sub(r"(updateDate:\s*')[^']+'", rf"\g<1>{date_str}'", html)

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    today = str(datetime.date.today())
    print(f"\n{'='*55}")
    print(f"  Marks Cycle Deck — Data Fetch  {today}")
    print(f"{'='*55}\n")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    changes = 0

    # ── Step 1: Fetch current index levels ───────────────
    print("📊 Index levels…")

    levels = {}

    # US, SG, HK, JP via CNBC
    for mid, sym in CNBC_SYMBOLS.items():
        lv = fetch_cnbc(sym)
        time.sleep(0.5)
        if lv:
            levels[mid] = lv
            print(f"  ✓ {mid:2s} ({sym}): {lv:,.2f}")
        else:
            print(f"  ⚠ {mid:2s} ({sym}): no data from CNBC")

    # CN via Eastmoney
    lv_cn = fetch_eastmoney_level(EASTMONEY_SECIDS["cn"])
    if lv_cn:
        levels["cn"] = lv_cn
        print(f"  ✓ cn (000905.SS): {lv_cn:,.2f}")
    else:
        print(f"  ⚠ cn: no data from Eastmoney")

    # MY via i3investor
    lv_my = fetch_my_klci()
    if lv_my:
        levels["my"] = lv_my
        print(f"  ✓ my (KLCI): {lv_my:,.2f}")
    else:
        print(f"  ⚠ my: no data from i3investor")

    # ── Step 2: Fetch year-start closes for YTD ──────────
    print("\n📅 Year-start closes for YTD calculation (Eastmoney)…")

    yearstart = {}
    em_ytd_markets = {
        "us": EASTMONEY_SECIDS["us"],
        "sg": EASTMONEY_SECIDS["sg"],
        "hk": EASTMONEY_SECIDS["hk"],
        "jp": EASTMONEY_SECIDS["jp"],
        "cn": EASTMONEY_SECIDS["cn"],
    }
    for mid, secid in em_ytd_markets.items():
        ys = fetch_eastmoney_yearstart(secid)
        time.sleep(0.4)
        if ys:
            yearstart[mid] = ys
            print(f"  ✓ {mid:2s} year-start: {ys:,.2f}")
        else:
            print(f"  ⚠ {mid:2s} year-start: unavailable")

    # MY year-start from Eastmoney (may fail) — fallback to estimate
    ys_my = fetch_my_yearstart()
    if ys_my:
        yearstart["my"] = ys_my
        print(f"  ✓ my year-start: {ys_my:,.2f}")
    else:
        # Estimate: if KLCI level is known, assume ~1.5% YTD
        if "my" in levels:
            ys_my = round(levels["my"] / 1.015, 2)
            yearstart["my"] = ys_my
            print(f"  ~ my year-start (estimated): {ys_my:,.2f}")

    # ── Step 3: Compute YTD % and patch HTML ─────────────
    print("\n📈 Patching level + YTD into index.html…")
    all_markets = ["us", "sg", "hk", "jp", "my", "cn"]

    for mid in all_markets:
        lv = levels.get(mid)
        ys = yearstart.get(mid)

        if lv:
            html, ok = patch_field(html, mid, "level", round(lv))
            if ok:
                print(f"  ✓ {mid:2s} level  = {round(lv):>9,}")
            changes += ok

        if lv and ys:
            ytd = round((lv / ys - 1) * 100, 1)
            html, ok = patch_field(html, mid, "ytd", ytd)
            if ok:
                print(f"  ✓ {mid:2s} ytd    = {ytd:>+6.1f}%")
            changes += ok

    # ── Step 4: PE ratios ─────────────────────────────────
    print("\n📊 PE ratios (worldperatio.com)…")
    for mid in all_markets:
        pe, pe5y, pe10y = fetch_worldpe(mid)
        time.sleep(1.2)
        if pe:
            html, ok = patch_field(html, mid, "ttmPE", round(pe, 2))
            if ok: print(f"  ✓ {mid:2s} ttmPE  = {pe:>6.2f}×")
            changes += ok
        else:
            print(f"  – {mid:2s} ttmPE: no data")
        if pe5y:
            html, ok = patch_field(html, mid, "pe5y",  round(pe5y, 2))
            if ok: print(f"  ✓ {mid:2s} pe5y   = {pe5y:>6.2f}×")
            changes += ok
        if pe10y:
            html, ok = patch_field(html, mid, "pe10y", round(pe10y, 2))
            if ok: print(f"  ✓ {mid:2s} pe10y  = {pe10y:>6.2f}×")
            changes += ok

    # ── Step 5: CAPE ──────────────────────────────────────
    print("\n🔢 CAPE (multpl.com)…")
    cape = fetch_cape()
    if cape:
        html, ok = patch_field(html, "us", "cape", round(cape, 2))
        if ok: print(f"  ✓ us CAPE   = {cape:.2f}")
        changes += ok
    else:
        print("  – CAPE: no data")

    # ── Step 6: Fear & Greed ──────────────────────────────
    print("\n😱 Fear & Greed (alternative.me)…")
    fgi = fetch_fng()
    if fgi is not None:
        html, ok = patch_field(html, "us", "fgi", fgi)
        if ok: print(f"  ✓ us FGI    = {fgi}")
        changes += ok
    else:
        print("  – FGI: no data")

    # ── Step 7: Update date ───────────────────────────────
    html = patch_update_date(html, today)
    print(f"\n📅 updateDate → {today}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✅ Done — {changes} fields updated\n")

    with open("fetch_summary.json", "w") as f:
        json.dump({"date": today, "fields_updated": changes}, f)


if __name__ == "__main__":
    main()
