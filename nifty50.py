#!/usr/bin/env python3
"""
stockpricesdaily_india_no_52w.py

Displays NIFTY50 stock data with 3 decimal precision and highlights negative changes in red boxes.
Timestamps shortened to 'YYYY-MM-DD HH:MM'.
Headers and values centered except for the Symbol column, which is left-aligned.
"""

from __future__ import annotations
import sys, os, json, traceback, webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

try:
    import pandas as pd
    import yfinance as yf
except Exception:
    pd = None
    yf = None

APP_NAME = "MorningStatus"
OUT_DIR = Path.home() / f".{APP_NAME.lower()}"
LOG_FILE = OUT_DIR / "fetch.log"
REPORT_FILE = OUT_DIR / "report2.html"
CACHE_FILE = OUT_DIR / "daily_cache.json"

FALLBACK_NIFTY50 = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","HINDUNILVR.NS","ICICIBANK.NS",
    "KOTAKBANK.NS","SBIN.NS","LT.NS","AXISBANK.NS","ITC.NS","BHARTIARTL.NS",
    "HDFC.NS","MARUTI.NS","ASIANPAINT.NS","HCLTECH.NS","NESTLEIND.NS","SUNPHARMA.NS",
    "BAJFINANCE.NS","BAJAJ-AUTO.NS","BAJAJFINSV.NS","ULTRACEMCO.NS","ONGC.NS","POWERGRID.NS",
    "NTPC.NS","TITAN.NS","TATASTEEL.NS","TECHM.NS","WIPRO.NS","SBILIFE.NS",
    "DIVISLAB.NS","GRASIM.NS","IOC.NS","INDUSINDBK.NS","BRITANNIA.NS","COALINDIA.NS",
    "HDFCLIFE.NS","DRREDDY.NS","JSWSTEEL.NS","BPCL.NS","EICHERMOT.NS","ADANIENT.NS",
    "ADANIPORTS.NS","APOLLOHOSP.NS","BHARATFORG.NS","CIPLA.NS","HINDALCO.NS","M&M.NS"
]

OUT_DIR.mkdir(parents=True, exist_ok=True)

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        print(f"[{ts}] {msg}")

def fetch_nifty50_tickers() -> List[str]:
    url = "https://finance.yahoo.com/quote/%5ENSEI/components"
    try:
        log(f"Fetching NIFTY50 tickers from {url}")
        tables = pd.read_html(url)
        for t in tables:
            cols = [c.lower() for c in t.columns.astype(str)]
            if 'symbol' in cols:
                sym_col = t.columns[[c.lower() == 'symbol' for c in cols]][0]
                syms = t[sym_col].astype(str).tolist()
                clean = []
                for s in syms:
                    s = s.strip()
                    if not s or s.startswith('^') or '/' in s: continue
                    if not s.endswith('.NS'): s += '.NS'
                    clean.append(s)
                if clean:
                    log(f"Fetched {len(clean)} tickers dynamically")
                    return clean
    except Exception as e:
        log(f"Dynamic fetch failed: {repr(e)}")
    log("Using fallback NIFTY50 list")
    return FALLBACK_NIFTY50

def fetch_with_yfinance_fast(tickers: List[str]) -> Dict[str, Any]:
    log("Fetching daily prices via yfinance...")
    if pd is None or yf is None:
        raise RuntimeError("pandas or yfinance missing")
    df = yf.download(tickers, period="7d", interval="1d", group_by='ticker', threads=True, progress=False)
    results = {}
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M')

    def parse(sym: str):
        try:
            if isinstance(df.columns, pd.MultiIndex): sub = df[sym].dropna()
            else: sub = df.dropna()
            if sub.empty: return None
            last, prev = sub.iloc[-1], sub.iloc[-2] if len(sub) >= 2 else None
            lc = float(last.get('Close', last.get('close', 0)))
            pc = float(prev.get('Close', prev.get('close', 0))) if prev is not None else None
            ch = lc - pc if pc else None
            pct = (ch / pc * 100) if pc else None
            return {'symbol': sym.replace('.NS',''),'last_close': lc,'prev_close': pc,'change': ch,'pct_change': pct,'timestamp': now_ts}
        except Exception as e:
            log(f"Error parsing {sym}: {repr(e)}")
            return None

    for s in tickers:
        res = parse(s)
        if res: results[s] = res
    log(f"Fetched {len(results)} tickers")
    return results

def write_html_report(data: Dict[str, Any]):
    try:
        rows = []
        for _, info in sorted(data.items()):
            rows.append((info['symbol'], info['last_close'], info['prev_close'], info['change'], info['pct_change'], info['timestamp']))
        html = [
            "<!doctype html>",
            "<html><head><meta charset='utf-8'><title>Daily India Report</title>",
            "<style>body{font-family:Arial}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:6px;text-align:center}th{background:#f4f4f4}.neg{background:#ffcccc}.left{text-align:left}</style>",
            "</head><body>",
            f"<h2 style='text-align:center'>NIFTY50 Daily Prices — {datetime.now().strftime('%Y-%m-%d %H:%M')}</h2>",
            "<table>",
            "<tr><th>Symbol</th><th>Last Close</th><th>Prev Close</th><th>Change</th><th>%</th><th>Updated</th></tr>"
        ]
        for sym, lc, prev, ch, pct, ts in rows:
            lc_s = f"{lc:.3f}" if lc is not None else "-"
            prev_s = f"{prev:.3f}" if prev is not None else "-"
            ch_s = f"{ch:.3f}" if ch is not None else "-"
            pct_s = f"{pct:.3f}%" if pct is not None else "-"
            cls = "neg" if (ch is not None and ch < 0) else ""
            html.append(f"<tr><td class='left'>{sym}</td><td>{lc_s}</td><td>{prev_s}</td><td class='{cls}'>{ch_s}</td><td class='{cls}'>{pct_s}</td><td>{ts}</td></tr>")
        html.append("</table></body></html>")
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(html))
        log(f"Wrote report to {REPORT_FILE}")
    except Exception as e:
        log(f"Write report failed: {repr(e)}")

def save_cache(data: Dict[str, Any]):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'data': data}, f, indent=2)
    except Exception as e:
        log(f"Save cache failed: {repr(e)}")

def load_cache() -> Dict[str, Any]:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get('data', {})
    except Exception as e:
        log(f"Load cache failed: {repr(e)}")
    return {}

def run_fetch_and_report(auto_open=True):
    try:
        tickers = fetch_nifty50_tickers()
        data = fetch_with_yfinance_fast(tickers)
        if not data:
            log("No data fetched")
            return
        save_cache(data)
        write_html_report(data)
        if auto_open:
            try:
                webbrowser.open(REPORT_FILE.as_uri())
            except Exception as e:
                log(f"Browser open failed: {repr(e)}")
    except Exception as e:
        log(f"Fetch failed: {repr(e)}\n{traceback.format_exc()}")

def main(argv: List[str]):
    auto_open = True
    if "--no-open" in argv: auto_open = False
    if "--no-fetch" in argv:
        load_cache()
        return
    run_fetch_and_report(auto_open)

if __name__ == '__main__':
    main(sys.argv)
