#!/usr/bin/env python3
"""
update_52w_cache.py

Fetches 52-week high / low for configured tickers and saves to
<LOCALAPPDATA>/MorningStatus/52w_cache.json (or ~/MorningStatus on non-Windows).

This version writes an additional "symbols" mapping into the JSON:
  {
    "date": "YYYY-MM-DD",
    "symbols": { "Sensex": "^BSESN", ... },
    "values": {
       "^BSESN": {"yearHigh": ..., "yearLow": ..., "close": ..., "previousClose": ...},
       ...
    }
  }

Added: each ticker now attempts to capture both 'close' (current/last) and
'previousClose' (previous official close) where possible.
"""
import os
import sys
import json
import time
import traceback
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------- Config ----------
TIMEZONE = "Asia/Kolkata"
SYMBOLS = {
    "Sensex": "^BSESN",
    "NIFTY": "^NSEI",
    "Paradeep": "PARADEEP.NS",
    "DMart": "DMART.NS",
    "Reliance Industries": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "SBI": "SBIN.NS",
    "ITC": "ITC.NS",
    "Tata Motors": "TATAMOTORS.NS",
    "Nestle India": "NESTLEIND.NS",
    "USD → INR": "USDINR=X",
    "Bitcoin (USD)": "BTC-USD",
    "Brent (USD/bbl)": "BZ=F",
    "Gold (USD/oz)": "GC=F",
    "Silver (USD/oz)": "SI=F",
}
OUT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MorningStatus")
CACHE_FILE = os.path.join(OUT_DIR, "52w_cache.json")
LOG_FILE = os.path.join(OUT_DIR, "fetch.log")

PER_TICKER_TIMEOUT = 20        # seconds to wait for each ticker result
MAX_WORKERS = 6               # parallel worker threads
# --------------------------------

def now_kolkata():
    return datetime.now(pytz.timezone(TIMEZONE))

def today_kolkata_date_str():
    return now_kolkata().date().isoformat()

def ensure_outdir():
    os.makedirs(OUT_DIR, exist_ok=True)

def log(msg, also_print=False):
    ensure_outdir()
    ts = datetime.utcnow().isoformat() + "Z"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {msg}\n")
    except Exception:
        pass
    if also_print:
        print(msg)

def load_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        log(f"load_cache error: {repr(e)}", also_print=True)
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        log(f"saved cache to {CACHE_FILE}", also_print=True)
    except Exception as e:
        log(f"save_cache error: {repr(e)}", also_print=True)

def safe_float(x):
    if x is None:
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None

def fetch_52w_for_symbol(sym, debug=False):
    """
    Returns tuple (sym, { "yearHigh": ..., "yearLow": ..., "close": ..., "previousClose": ... })
    Attempts multiple sources for each value (fast_info, info, computed from history).
    """
    try:
        import yfinance as yf
    except Exception as e:
        log(f"yfinance import error: {repr(e)}", also_print=True)
        return sym, {"yearHigh": None, "yearLow": None, "close": None, "previousClose": None}

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            t = yf.Ticker(sym)
            fi = getattr(t, "fast_info", None) or {}
            info = getattr(t, "info", {}) or {}
            yr_high = None
            yr_low = None
            close = None
            prev_close = None

            # --- try fast_info and info for highs/lows and close-like fields ---
            if fi and isinstance(fi, dict):
                yr_high = fi.get("yearHigh") or fi.get("fiftyTwoWeekHigh") or fi.get("52WeekHigh")
                yr_low = fi.get("yearLow") or fi.get("fiftyTwoWeekLow") or fi.get("52WeekLow")
                # possible close keys in fast_info
                close = close or fi.get("lastPrice") or fi.get("regularMarketPrice") or fi.get("last_close")
                prev_close = prev_close if 'prev_close' in locals() else None
                prev_close = prev_close or fi.get("previousClose") or fi.get("regularMarketPreviousClose")

            if yr_high is None and info:
                yr_high = info.get("fiftyTwoWeekHigh") or info.get("52WeekHigh") or info.get("yearHigh")
            if yr_low is None and info:
                yr_low = info.get("fiftyTwoWeekLow") or info.get("52WeekLow") or info.get("yearLow")

            # try common info keys for close/current price and previous close
            if info:
                close = close or info.get("regularMarketPrice") or info.get("currentPrice") or info.get("close") or info.get("lastClose")
                prev_close = prev_close or info.get("previousClose") or info.get("regularMarketPreviousClose")

            # --- fallback: compute highs/lows and closes from history if necessary ---
            hist = None
            need_hist = (yr_high is None or yr_low is None or close is None or prev_close is None)
            if need_hist:
                try:
                    # try to fetch 1y history (unadjusted to preserve official closes)
                    hist = t.history(period="1y", actions=False, auto_adjust=False)
                except Exception as e_hist1:
                    log(f"[WARN {sym}] history(period=1y) error: {repr(e_hist1)}")
                    try:
                        hist = t.history(period="1y", actions=False, auto_adjust=True)
                    except Exception as e_hist2:
                        log(f"[WARN {sym}] history fallback also failed: {repr(e_hist2)}")

            if hist is not None and not getattr(hist, "empty", True):
                # compute highs/lows if needed
                if ("High" in hist.columns) and ("Low" in hist.columns):
                    computed_high = float(hist["High"].max())
                    computed_low = float(hist["Low"].min())
                    if yr_high is None:
                        yr_high = computed_high
                    if yr_low is None:
                        yr_low = computed_low
                # derive close & previousClose from the most recent Close values if needed
                if "Close" in hist.columns:
                    closes = hist["Close"].dropna()
                    if not closes.empty:
                        try:
                            # most recent close
                            last_close = float(closes.iloc[-1])
                            close = close or last_close
                        except Exception:
                            pass
                        # previous close = second-last valid close, if present
                        try:
                            if len(closes) >= 2:
                                prev = float(closes.iloc[-2])
                                prev_close = prev_close or prev
                        except Exception:
                            pass
            else:
                # try 2y history as a last resort
                try:
                    hist2 = t.history(period="2y", actions=False, auto_adjust=False)
                    if hist2 is not None and not getattr(hist2, "empty", True):
                        if ("High" in hist2.columns) and ("Low" in hist2.columns):
                            computed_high = float(hist2["High"].max())
                            computed_low = float(hist2["Low"].min())
                            if yr_high is None:
                                yr_high = computed_high
                            if yr_low is None:
                                yr_low = computed_low
                        if "Close" in hist2.columns:
                            closes2 = hist2["Close"].dropna()
                            if not closes2.empty:
                                try:
                                    last_close = float(closes2.iloc[-1])
                                    close = close or last_close
                                except Exception:
                                    pass
                                try:
                                    if len(closes2) >= 2:
                                        prev = float(closes2.iloc[-2])
                                        prev_close = prev_close or prev
                                except Exception:
                                    pass
                    else:
                        log(f"[WARN {sym}] history 1y and 2y empty or unavailable", also_print=True)
                except Exception as e_hist2y:
                    log(f"[WARN {sym}] history(period=2y) error: {repr(e_hist2y)}", also_print=True)

            yr_high = safe_float(yr_high)
            yr_low = safe_float(yr_low)
            close = safe_float(close)
            prev_close = safe_float(prev_close)

            log(f"Fetched {sym}: yearHigh={yr_high} yearLow={yr_low} close={close} previousClose={prev_close}")
            return sym, {"yearHigh": yr_high, "yearLow": yr_low, "close": close, "previousClose": prev_close}

        except Exception as e:
            log(f"fetch_52w_for_symbol attempt {attempt} error for {sym}: {repr(e)}", also_print=True)
            if attempt == max_retries:
                log(f"fetch_52w_for_symbol final failure for {sym}\n{traceback.format_exc()}", also_print=True)
                return sym, {"yearHigh": None, "yearLow": None, "close": None, "previousClose": None}
            time.sleep(1.5)

def refresh_52w_cache(symbol_values, debug_single=None):
    ensure_outdir()
    tickers = list(symbol_values.values()) if debug_single is None else [debug_single]
    results = {}
    log(f"Starting 52w refresh for {len(tickers)} tickers at {now_kolkata().isoformat()} (IST)", also_print=True)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tickers) or 1)) as ex:
        futures = {ex.submit(fetch_52w_for_symbol, tk, debug=(debug_single is not None)): tk for tk in tickers}
        for fut in as_completed(futures):
            tk = futures[fut]
            try:
                sym, vals = fut.result(timeout=PER_TICKER_TIMEOUT)
                results[sym] = vals
                log(f"Result {sym}: {vals}", also_print=True)
            except Exception as e:
                log(f"Timeout/exception fetching 52w for {tk}: {repr(e)}", also_print=True)
                results[tk] = {"yearHigh": None, "yearLow": None, "close": None, "previousClose": None}

    # build cache payload: include symbols mapping so downstream scripts can display tickers
    payload = {"date": today_kolkata_date_str(), "symbols": symbol_values, "values": results}
    save_cache(payload)
    return payload

def main(force_refresh=False, single_ticker=None):
    ensure_outdir()
    try:
        cache = load_cache()
        if not force_refresh and cache.get("date") == today_kolkata_date_str() and not single_ticker:
            log("Cache already fresh for today; no refresh needed.", also_print=True)
            print(f"Cache already fresh: {CACHE_FILE}")
            return
        payload = refresh_52w_cache(SYMBOLS, debug_single=single_ticker)
        print("Saved 52w cache to:", CACHE_FILE)
        log("52w refresh complete", also_print=True)
    except Exception as e:
        log(f"main error: {repr(e)}\n{traceback.format_exc()}", also_print=True)
        print("Error:", e)
        sys.exit(1)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Fetch and cache 52-week high/low for tickers (writes symbols mapping)")
    p.add_argument("--force", action="store_true", help="Force refresh even if cache is fresh for today")
    p.add_argument("--single", type=str, help="Debug single ticker (ticker symbol), e.g. RELIANCE.NS")
    args = p.parse_args()
    main(force_refresh=args.force, single_ticker=args.single)
