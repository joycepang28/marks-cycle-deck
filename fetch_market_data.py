#!/usr/bin/env python3
"""
Auto-fetch market data for the Marks Cycle Deck dashboard.
Patches DEFAULT_DATA values in index.html in-place.

Data sources:
  - Index level (US/HK/JP/SG) : CNBC quote API
  - Index level (MY)           : i3investor.com (klse)
  - Index level (CN)           : Eastmoney push2 API
  - YTD %                      : Eastmoney kline API (year-start close)
  - TTM PE + 5Y/10Y (non-CN)  : worldperatio.com (HTML parse)
  - CN TTM PE (current)        : AkShare stock_zh_index_value_csindex (中证官方市盈率2)
  - CN PE 5Y/10Y avg           : AkShare stock_index_pe_lg (乐咕乐股, scaled to CSIndex basis)
  - CAPE                       : multpl.com/shiller-pe (HTML parse)
  - Fear & Greed               : api.alternative.me/fng/ (free JSON API)
"""

import re, json, time, datetime
import urllib.request, urllib.parse, urllib.error
try:
    import akshare as ak
    import pandas as pd
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

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

# ---------------------------------------------
# 1. CNBC -- index level for US/SG/HK/JP
# ---------------------------------------------
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
        print(f"  Warning CNBC {symbol}: {e}")
    return None

# ---------------------------------------------
# 2. Eastmoney -- index level for CN + YTD
# ---------------------------------------------
EASTMONEY_SECIDS = {
    "cn":  "1.000905",
    "us":  "100.SPX",
    "sg":  "100.STI",
    "hk":  "100.HSI",
    "jp":  "100.N225",
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
            return round(float(f43) / 100, 2)
    except Exception as e:
        print(f"  Warning Eastmoney level {secid}: {e}")
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
            parts = klines[0].split(",")
            return safe_float(parts[2])
    except Exception as e:
        print(f"  Warning Eastmoney yearstart {secid}: {e}")
    return None

# ---------------------------------------------
# 3. i3investor.com -- MY KLCI current level
# ---------------------------------------------
def fetch_my_klci():
    """Return current FBM KLCI level from i3investor."""
    url = "https://klse.i3investor.com/web/index/market-index"
    try:
        raw = get(url)
        idx = raw.find("FBM KLCI")
        if idx < 0:
            idx = raw.find("KLCI")
        if idx >= 0:
            segment = raw[max(0, idx-500):idx+500]
            m = re.search(r'<strong>([\d,\.]+)</strong>', segment)
            if m:
                return safe_float(m.group(1))
    except Exception as e:
        print(f"  Warning MY KLCI (i3investor): {e}")
    return None

def fetch_my_yearstart():
    """Try to get MY KLCI year-start from Eastmoney; else estimate."""
    for secid in ["104.KLSE", "105.KLSE", "106.KLSE"]:
        val = fetch_eastmoney_yearstart(secid)
        if val:
            return val
    return None

# ---------------------------------------------
# 4. worldperatio.com -- TTM PE + 5Y/10Y (non-CN)
# ---------------------------------------------
WORLDPE_URLS = {
    "us": "https://worldperatio.com/index/sp-500/",
    "sg": "https://worldperatio.com/area/singapore/",
    "hk": "https://worldperatio.com/area/hong-kong/",
    "jp": "https://worldperatio.com/area/japan/",
    "my": "https://worldperatio.com/area/malaysia/",
}

def fetch_worldpe(market_id):
    """Return (ttm_pe, pe5y, pe10y) from worldperatio.com."""
    url = WORLDPE_URLS.get(market_id)
    if not url:
        return None, None, None
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
        print(f"  Warning worldperatio {market_id}: {e}")
    return None, None, None

# ---------------------------------------------
# 5. AkShare -- CN CSI500 PE (中证官方 + 乐咕乐股)
# ---------------------------------------------
def fetch_cn_pe():
    """
    Return (ttm_pe, pe5y, pe10y) for CSI 500:
      Current: stock_zh_index_value_csindex 市盈率2 (中证指数公司官方)
      History: stock_index_pe_lg 静态市盈率 scaled to CSIndex level (乐咕乐股)
    """
    if not HAS_AKSHARE:
        print("  Warning: AkShare not installed -- CN PE skipped")
        return None, None, None
    try:
        # Current PE from CSIndex official (市盈率2 = dynamic/TTM PE)
        df_cs = ak.stock_zh_index_value_csindex(symbol="000905")
        df_cs['\u65e5\u671f'] = pd.to_datetime(df_cs['\u65e5\u671f'])
        df_cs = df_cs.sort_values('\u65e5\u671f')
        pe_current = round(float(df_cs.iloc[-1]['\u5e02\u76c8\u73872']), 2)

        # Long-history averages from legulegu (2007-present)
        df_lg = ak.stock_index_pe_lg(symbol="\u4e2d\u8bc1500")
        df_lg['date'] = pd.to_datetime(df_lg['\u65e5\u671f'])
        df_lg = df_lg.sort_values('date')
        latest_date = df_lg['date'].max()

        df_5y  = df_lg[df_lg['date'] >= latest_date - pd.DateOffset(years=5)]
        df_10y = df_lg[df_lg['date'] >= latest_date - pd.DateOffset(years=10)]

        # Scale legulegu LYR series to CSIndex level for consistency
        lg_latest_lyr = float(df_lg.iloc[-1]['\u9759\u6001\u5e02\u76c8\u7387'])
        scale = pe_current / lg_latest_lyr if lg_latest_lyr else 1.0

        pe5y  = round(float(df_5y['\u9759\u6001\u5e02\u76c8\u7387'].mean()) * scale, 2)
        pe10y = round(float(df_10y['\u9759\u6001\u5e02\u76c8\u7387'].mean()) * scale, 2)

        return pe_current, pe5y, pe10y
    except Exception as e:
        print(f"  Warning CN PE (AkShare): {e}")
        return None, None, None

# ---------------------------------------------
# 6. multpl.com -- Shiller CAPE (US only)
# ---------------------------------------------
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
        print(f"  Warning CAPE (multpl): {e}")
    return None

# ---------------------------------------------
# 7. alternative.me -- Fear & Greed Index
# ---------------------------------------------
def fetch_fng():
    try:
        raw = get("https://api.alternative.me/fng/?limit=1", accept="application/json,*/*")
        data = json.loads(raw)
        return int(data["data"][0]["value"])
    except Exception as e:
        print(f"  Warning Fear & Greed: {e}")
    return None


def fetch_sg_rsi():
    """Compute STI RSI(14) as a Singapore market sentiment proxy.
    RSI < 30 = oversold/fear, RSI > 70 = overbought/greed, 50 = neutral.
    Returns integer 0-100.
    """
    try:
        import yfinance as yf
        t = yf.Ticker("^STI")
        hist = t.history(period="3mo")
        if hist.empty or len(hist) < 15:
            return None
        closes = hist['Close'].tolist()
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(c, 0) for c in changes[-14:]]
        losses = [abs(min(c, 0)) for c in changes[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi)
    except Exception as e:
        print(f"  Warning SG RSI: {e}")
    return None


def fetch_my_rsi():
    """Compute FBM KLCI RSI(14) as a Malaysia market sentiment proxy.
    Uses Yahoo Finance ^KLSE 3-month daily history.
    RSI < 30 = oversold/fear, RSI > 70 = overbought/greed, 50 = neutral.
    Returns integer 0-100.
    """
    try:
        import yfinance as yf
        t = yf.Ticker("^KLSE")
        hist = t.history(period="3mo")
        if hist.empty or len(hist) < 15:
            return None
        closes = hist['Close'].tolist()
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(c, 0) for c in changes[-14:]]
        losses = [abs(min(c, 0)) for c in changes[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi)
    except Exception as e:
        print(f"  Warning MY RSI: {e}")
    return None


def fetch_cn_rsi():
    """Compute CSI 500 RSI(14) as a China market sentiment proxy.
    Uses AkShare stock_zh_index_daily(symbol='sh000905') daily history.
    RSI < 30 = oversold/fear, RSI > 70 = overbought/greed, 50 = neutral.
    Returns integer 0-100.
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000905")
        if df is None or len(df) < 15:
            return None
        closes = df['close'].astype(float).tolist()
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(c, 0) for c in changes[-14:]]
        losses = [abs(min(c, 0)) for c in changes[-14:]]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi)
    except Exception as e:
        print(f"  Warning CN RSI: {e}")
    return None


def fetch_vhsi():
    """Fetch HSI Volatility Index (VHSI) from CNBC quote page."""
    try:
        raw = get("https://www.cnbc.com/quotes/VHSI")
        m = re.search(r'"last":"?(\d+\.?\d*)"?', raw)
        if m:
            return float(m.group(1))
    except Exception as e:
        print(f"  Warning VHSI: {e}")
    return None


def fetch_nkvi():
    """Fetch Nikkei Average Volatility Index (^NKVI.OS) via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker("^NKVI.OS")
        info = t.fast_info
        val = info.last_price
        if val and val > 0:
            return round(float(val), 2)
    except Exception as e:
        print(f"  Warning NKVI: {e}")
    return None

# ---------------------------------------------
# 8. Patch index.html DEFAULT_DATA in-place
# ---------------------------------------------
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

# ---------------------------------------------
# Main
# ---------------------------------------------
def main():
    today = str(datetime.date.today())
    print(f"\n{'='*55}")
    print(f"  Marks Cycle Deck -- Data Fetch  {today}")
    print(f"{'='*55}\n")

    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    changes = 0
    all_markets = ["us", "sg", "hk", "jp", "my", "cn"]

    # Collector for market_data.json
    mdata = {m: {} for m in all_markets}

    # -- Step 1: Fetch current index levels --
    print("Index levels...")

    levels = {}

    for mid, sym in CNBC_SYMBOLS.items():
        lv = fetch_cnbc(sym)
        time.sleep(0.5)
        if lv:
            levels[mid] = lv
            print(f"  OK {mid} ({sym}): {lv:,.2f}")
        else:
            print(f"  WARN {mid} ({sym}): no data from CNBC")

    lv_cn = fetch_eastmoney_level(EASTMONEY_SECIDS["cn"])
    if lv_cn:
        levels["cn"] = lv_cn
        print(f"  OK cn (000905.SS): {lv_cn:,.2f}")
    else:
        print(f"  WARN cn: no data from Eastmoney")

    lv_my = fetch_my_klci()
    if lv_my:
        levels["my"] = lv_my
        print(f"  OK my (KLCI): {lv_my:,.2f}")
    else:
        print(f"  WARN my: no data from i3investor")

    # -- Step 2: Fetch year-start closes for YTD --
    print("\nYear-start closes for YTD (Eastmoney)...")

    yearstart = {}
    em_ytd = {
        "us": EASTMONEY_SECIDS["us"],
        "sg": EASTMONEY_SECIDS["sg"],
        "hk": EASTMONEY_SECIDS["hk"],
        "jp": EASTMONEY_SECIDS["jp"],
        "cn": EASTMONEY_SECIDS["cn"],
    }
    for mid, secid in em_ytd.items():
        ys = fetch_eastmoney_yearstart(secid)
        time.sleep(0.4)
        if ys:
            yearstart[mid] = ys
            print(f"  OK {mid} year-start: {ys:,.2f}")
        else:
            print(f"  WARN {mid} year-start: unavailable")

    ys_my = fetch_my_yearstart()
    if ys_my:
        yearstart["my"] = ys_my
        print(f"  OK my year-start: {ys_my:,.2f}")
    elif "my" in levels:
        ys_my = round(levels["my"] / 1.015, 2)
        yearstart["my"] = ys_my
        print(f"  ~ my year-start (estimated at +1.5%): {ys_my:,.2f}")

    # -- Step 3: Patch level + YTD --
    print("\nPatching level + YTD...")
    for mid in all_markets:
        lv = levels.get(mid)
        ys = yearstart.get(mid)

        if lv:
            html, ok = patch_field(html, mid, "level", round(lv))
            if ok:
                print(f"  OK {mid} level  = {round(lv):>9,}")
            changes += ok

        if lv and ys:
            ytd = round((lv / ys - 1) * 100, 1)
            html, ok = patch_field(html, mid, "ytd", ytd)
            if ok:
                print(f"  OK {mid} ytd    = {ytd:>+6.1f}%")
            changes += ok

    # -- Step 4: PE ratios (non-CN via worldperatio) --
    non_cn = [m for m in all_markets if m != "cn"]
    print("\nPE ratios (worldperatio.com, non-CN)...")
    for mid in non_cn:
        pe, pe5y, pe10y = fetch_worldpe(mid)
        time.sleep(1.2)
        if pe:
            html, ok = patch_field(html, mid, "ttmPE", round(pe, 2))
            if ok: print(f"  OK {mid} ttmPE  = {pe:>6.2f}x")
            changes += ok
        else:
            print(f"  -- {mid} ttmPE: no data")
        if pe5y:
            html, ok = patch_field(html, mid, "pe5y",  round(pe5y, 2))
            if ok: print(f"  OK {mid} pe5y   = {pe5y:>6.2f}x")
            changes += ok
        if pe10y:
            html, ok = patch_field(html, mid, "pe10y", round(pe10y, 2))
            if ok: print(f"  OK {mid} pe10y  = {pe10y:>6.2f}x")
            changes += ok

    # -- Step 4b: CN PE via AkShare (CSIndex official + legulegu history) --
    print("\nCN PE (CSIndex official + legulegu history)...")
    cn_pe, cn_pe5y, cn_pe10y = fetch_cn_pe()
    if cn_pe:
        html, ok = patch_field(html, "cn", "ttmPE", cn_pe)
        if ok: print(f"  OK cn ttmPE  = {cn_pe:>6.2f}x  (CSIndex official)")
        changes += ok
    else:
        print("  -- cn ttmPE: no data")
    if cn_pe5y:
        html, ok = patch_field(html, "cn", "pe5y",  cn_pe5y)
        if ok: print(f"  OK cn pe5y   = {cn_pe5y:>6.2f}x")
        changes += ok
    if cn_pe10y:
        html, ok = patch_field(html, "cn", "pe10y", cn_pe10y)
        if ok: print(f"  OK cn pe10y  = {cn_pe10y:>6.2f}x")
        changes += ok

    # -- Step 5: CAPE --
    print("\nCAPE (multpl.com)...")
    cape = fetch_cape()
    if cape:
        html, ok = patch_field(html, "us", "cape", round(cape, 2))
        if ok: print(f"  OK us CAPE   = {cape:.2f}")
        changes += ok
    else:
        print("  -- CAPE: no data")

    # -- Step 6: Fear & Greed --
    print("\nFear & Greed (alternative.me)...")
    fgi = fetch_fng()
    if fgi is not None:
        html, ok = patch_field(html, "us", "fgi", fgi)
        if ok: print(f"  OK us FGI    = {fgi}")
        changes += ok
    else:
        print("  -- FGI: no data")

    # -- Step 7a: SG RSI momentum --
    print("\nSingapore RSI(14)...")
    sg_rsi = fetch_sg_rsi()
    if sg_rsi is not None:
        html, ok = patch_field(html, "sg", "fgi", sg_rsi)
        if ok: print(f"  OK sg RSI    = {sg_rsi}")
        changes += ok
    else:
        print("  -- SG RSI: no data")

    # -- Step 7: Volatility Indices (VHSI / NKVI) --
    print("\nVolatility indices...")
    vhsi = fetch_vhsi()
    if vhsi is not None:
        html, ok = patch_field(html, "hk", "vix", round(vhsi, 2))
        if ok: print(f"  OK hk VHSI   = {vhsi:.2f}")
        changes += ok
    else:
        print("  -- VHSI: no data")

    nkvi = fetch_nkvi()
    if nkvi is not None:
        html, ok = patch_field(html, "jp", "vix", round(nkvi, 2))
        if ok: print(f"  OK jp NKVI   = {nkvi:.2f}")
        changes += ok
    else:
        print("  -- NKVI: no data")

    # -- Step 8: MY RSI --
    print("\nMalaysia RSI(14)...")
    my_rsi = fetch_my_rsi()
    if my_rsi is not None:
        html, ok = patch_field(html, "my", "fgi", my_rsi)
        if ok: print(f"  OK my RSI    = {my_rsi}")
        changes += ok
    else:
        print("  -- MY RSI: no data")

    # -- Step 9: CN RSI --
    print("\nChina RSI(14)...")
    cn_rsi = fetch_cn_rsi()
    if cn_rsi is not None:
        html, ok = patch_field(html, "cn", "fgi", cn_rsi)
        if ok: print(f"  OK cn RSI    = {cn_rsi}")
        changes += ok
    else:
        print("  -- CN RSI: no data")

    # -- Step 10: Update date --
    html = patch_update_date(html, today)
    print(f"\nDate -> {today}")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone -- {changes} fields updated\n")

    with open("fetch_summary.json", "w") as f:
        json.dump({"date": today, "fields_updated": changes}, f)

    # -- Write market_data.json for frontend GitHub-raw fetch --
    numeric_fields = ["level", "ytd", "ttmPE", "pe5y", "pe10y", "cape", "fgi", "vix", "stage"]
    market_data_out = {"date": today, "markets": {}}
    for mid in all_markets:
        id_pat = re.compile(rf"id:\s*'{re.escape(mid)}'")
        m = id_pat.search(html)
        if not m:
            continue
        block_start = m.start()
        block_end = html.find("\n    }", block_start) + 6
        block = html[block_start:block_end]
        entry = {}
        for field in numeric_fields:
            fp = re.search(rf"{re.escape(field)}:\s*([^,\n]+)", block)
            if fp:
                raw = fp.group(1).strip().rstrip(",")
                try:
                    entry[field] = float(raw) if "." in raw else (None if raw == "null" else int(raw))
                except ValueError:
                    pass
        market_data_out["markets"][mid] = entry
    with open("market_data.json", "w") as f:
        json.dump(market_data_out, f, indent=2)
    print(f"market_data.json written ({len(all_markets)} markets)")



if __name__ == "__main__":
    main()
