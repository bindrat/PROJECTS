#!/usr/bin/env python3
"""
stockpricesdaily_india_no_52w.py

Variant of stockpricesdaily with Indian (NSE) tickers and automatic opening
of the generated HTML report. The 52-week fetch/refresh has been removed.

Changes in this version:
- Attempts to fetch the latest NIFTY50 tickers dynamically from Yahoo Finance at runtime.
- If dynamic fetch fails, falls back to an embedded list of common NIFTY50 tickers.
- Fetch is now the default behaviour: running the script with no args will perform a fetch and open the report.
- You can still run with `--no-open` to avoid auto-opening the browser, or `--no-fetch` to only write a placeholder.

Usage:
  python stockpricesdaily_india_no_52w.py            # default: fetch and open report
  python stockpricesdaily_india_no_52w.py --no-open  # fetch but don't auto-open
  python stockpricesdaily_india_no_52w.py --no-fetch # don't fetch; just write placeholder

Dependencies: yfinance, pandas, requests (requests is usually bundled; pandas.read_html uses it)
Install: pip install yfinance pandas requests

Notes:
- yfinance expects NSE tickers with the ".NS" suffix for Yahoo Finance symbols (e.g. RELIANCE.NS).
- Report and logs are written to ~/.morningstatus (Windows: C:\\Users\\<you>\\.morningstatus)
"""

from __future__ import annotations
import sys
import os
import json
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

try:
    import pandas as pd
    import yfinance as yf
except Exception:
    pd = None
    yf = None

# ---- Configuration ----
APP_NAME = "MorningStatus"
OUT_DIR = Path.home() / f".{APP_NAME.lower()}"
LOG_FILE = OUT_DIR / "fetch.log"
REPORT_FILE = OUT_DIR / "report2.html"
CACHE_FILE = OUT_DIR / "daily_cache.json"

# If dynamic fetch of NIFTY50 components fails, this embedded fallback list will be used.
# The list uses Yahoo Finance-style symbols with the .NS suffix.
FALLBACK_NIFTY50 = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","HINDUNILVR.NS","ICICIBANK.NS",
    "KOTAKBANK.NS","SBIN.NS","LT.NS","AXISBANK.NS","ITC.NS","BHARTIARTL.NS",
    "MARUTI.NS","ASIANPAINT.NS","HCLTECH.NS","NESTLEIND.NS","SUNPHARMA.NS",
    "BAJFINANCE.NS","BAJAJ-AUTO.NS","BAJAJFINSV.NS","ULTRACEMCO.NS","ONGC.NS","POWERGRID.NS",
    "NTPC.NS","TITAN.NS","TATASTEEL.NS","TECHM.NS","WIPRO.NS","SBILIFE.NS",
    "DIVISLAB.NS","GRASIM.NS","IOC.NS","INDUSINDBK.NS","BRITANNIA.NS","COALINDIA.NS",
    "HDFCLIFE.NS","DRREDDY.NS","JSWSTEEL.NS","BPCL.NS","EICHERMOT.NS","ADANIENT.NS",
    "ADANIPORTS.NS","APOLLOHOSP.NS","BHARATFORG.NS","CIPLA.NS","HINDALCO.NS","M&M.NS"
]

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Simple logger ----

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        print(line, end="")


# ---- Helper: try to fetch NIFTY50 tickers dynamically from Yahoo Finance ----

def fetch_nifty50_tickers() -> List[str]:
    """Attempt to fetch NIFTY50 components from Yahoo Finance components page.
    Returns a list of symbols (with .NS suffix). Falls back to FALLBACK_NIFTY50 on failure.
    """
    url = "https://finance.yahoo.com/quote/%5ENSEI/components"
    try:
        log(f"Attempting to fetch NIFTY50 components from {url}")
        # pandas.read_html can parse the components table; it requires requests/urllib underneath
        tables = pd.read_html(url)
        # Find the table that has a 'Symbol' column
        for t in tables:
            cols = [c.lower() for c in t.columns.astype(str)]
            if 'symbol' in cols:
                sym_col = t.columns[[c.lower() == 'symbol' for c in cols]][0]
                symbols = t[sym_col].astype(str).tolist()
                # Ensure .NS suffix for NSE where missing
                cleaned = []
                for s in symbols:
                    s = s.strip()
                    if s.endswith('.NS'):
                        cleaned.append(s)
                    else:
                        # If the symbol looks like ^ or contains / skip
                        if s.startswith('^') or '/' in s:
                            continue
                        cleaned.append(s + '.NS')
                if cleaned:
                    log(f"Fetched {len(cleaned)} NIFTY50 tickers from Yahoo Finance")
                    return cleaned
    except Exception as e:
        log(f"Dynamic fetch of NIFTY50 failed: {repr(e)}")

    log("Using fallback embedded NIFTY50 tickers")
    return FALLBACK_NIFTY50


# ---- Fetch routine (daily only) ----

def fetch_with_yfinance_fast(tickers: List[str]) -> Dict[str, Any]:
    log("Starting daily fetch for Indian tickers (yfinance)")
    if pd is None or yf is None:
        err = "pandas or yfinance not installed"
        log(f"Import error: {err}")
        raise RuntimeError(err)

    try:
        df = yf.download(tickers, period="7d", interval="1d", group_by='ticker', threads=True, progress=False)
    except Exception as e:
        log(f"yf.download failed: {repr(e)}")
        raise

    results: Dict[str, Any] = {}
    now_ts = datetime.now().isoformat()

    def _extract_for_symbol(sym: str):
        try:
            if isinstance(df.columns, pd.MultiIndex):
                sub = df[sym].dropna()
                if sub.empty:
                    return None
                last_row = sub.iloc[-1]
                prev_row = sub.iloc[-2] if len(sub) >= 2 else None
                last_close = float(last_row.get('Close', last_row.get('close', None)))
                prev_close = float(prev_row.get('Close', prev_row.get('close', None))) if prev_row is not None else None
            else:
                sub = df.dropna()
                if sub.empty:
                    return None
                last_row = sub.iloc[-1]
                prev_row = sub.iloc[-2] if len(sub) >= 2 else None
                last_close = float(last_row.get('Close', last_row.get('close', None)))
                prev_close = float(prev_row.get('Close', prev_row.get('close', None))) if prev_row is not None else None

            change = None
            pct = None
            if prev_close is not None and prev_close != 0:
                change = last_close - prev_close
                pct = (change / prev_close) * 100.0
            # For nicer display strip .NS suffix in symbol label
            label = sym.replace('.NS','')
            return {
                'symbol': label,
                'raw_symbol': sym,
                'last_close': last_close,
                'prev_close': prev_close,
                'change': change,
                'pct_change': pct,
                'timestamp': now_ts,
            }
        except Exception as e:
            log(f"Error parsing data for {sym}: {repr(e)}")
            return None

    for s in tickers:
        try:
            entry = _extract_for_symbol(s)
            if entry:
                results[s] = entry
            else:
                log(f"No data for {s}")
        except Exception:
            log(f"Exception while extracting {s}: {traceback.format_exc()}")

    log(f"Daily fetch complete; fetched {len(results)} symbols")
    return results


# ---- Report generation ----

def write_html_report(data: Dict[str, Any]) -> None:
    try:
        rows = []
        for raw_sym, info in sorted(data.items(), key=lambda x: x[0]):
            rows.append((info['symbol'], info['last_close'], info['prev_close'], info['change'], info['pct_change'], info['timestamp']))

        html = [
            "<!doctype html>",
            "<html><head><meta charset=\"utf-8\"><title>Daily India Report</title>",
            "<style>body{font-family:Arial,Helvetica,sans-serif}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:right}th{text-align:left;background:#f4f4f4}</style>",
            "</head><body>",
            f"<h2>India Daily Prices — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</h2>",
            "<table>",
            "<tr><th>Symbol</th><th>Last Close</th><th>Prev Close</th><th>Change</th><th>%</th><th>Updated</th></tr>",
        ]

        for sym, lc, prev, ch, pct, ts in rows:
            ch_s = f"{ch:.2f}" if ch is not None else "-"
            pct_s = f"{pct:.2f}%" if pct is not None else "-"
            html.append(f"<tr><td style=\"text-align:left\">{sym}</td><td>{lc}</td><td>{prev}</td><td>{ch_s}</td><td>{pct_s}</td><td>{ts}</td></tr>")

        html.append("</table>")
        html.append("</body></html>")

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(html))

        log(f"Wrote report to {REPORT_FILE}")
    except Exception as e:
        log(f"Error writing report: {repr(e)}")
        raise


# ---- Cache helpers ----

def save_cache(data: Dict[str, Any]) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({'generated_at': datetime.now().isoformat(), 'data': data}, f, indent=2)
        log(f"Saved daily cache to {CACHE_FILE}")
    except Exception as e:
        log(f"Failed to save cache: {repr(e)}")


def load_cache() -> Dict[str, Any]:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                obj = json.load(f)
                return obj.get('data', {})
    except Exception as e:
        log(f"Failed to load cache: {repr(e)}")
    return {}


# ---- Main flow ----

def run_fetch_and_report(auto_open: bool = True):
    try:
        tickers = fetch_nifty50_tickers()
        results = fetch_with_yfinance_fast(tickers)
        if not results:
            log("Fetch completed but returned no results — leaving previous cache/report untouched")
            return
        save_cache(results)
        write_html_report(results)

        if auto_open:
            try:
                webbrowser.open(REPORT_FILE.as_uri())
                log(f"Opened report in browser: {REPORT_FILE}")
            except Exception as e:
                log(f"Failed to open browser automatically: {repr(e)}")
    except Exception as e:
        log(f"Fetch failed: {repr(e)}\n{traceback.format_exc()}")


def main(argv: List[str]):
    # Default behaviour: perform fetch and open report (unless --no-fetch passed)
    auto_open = True
    if "--no-open" in argv:
        auto_open = False

    if "--no-fetch" in argv:
        cached = load_cache()
        if cached:
            log("Serving page from last cache")
        else:
            log("No cache available; nothing to serve")
        placeholder = OUT_DIR / "loading.html"
        try:
            with open(placeholder, "w", encoding="utf-8") as f:
                f.write("<html><body><h3>Report generated separately.</h3><p>Run the script without --no-fetch to update data.</p></body></html>")
            log(f"Wrote placeholder {placeholder}")
        except Exception as e:
            log(f"Failed to write placeholder: {repr(e)}")
        return

    # Otherwise, perform fetch (default)
    run_fetch_and_report(auto_open=auto_open)


if __name__ == '__main__':
    main(sys.argv)
