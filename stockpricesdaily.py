#!/usr/bin/env python3
"""
morning_status_daily_with_52w_cached.py

- Daily closes (interval=1d, period=2d) -> today's close vs yesterday's close
- Currency suffixes
- Derived Gold (INR/10g) and Silver (INR/kg) when USD/oz + USDINR available
- 52-week High / Low fetched on demand but cached once per calendar day to avoid hanging
- Per-ticker timeouts for 52-week fetch to keep script responsive
"""

import os
import sys
import subprocess
import traceback
from datetime import datetime, date
import pytz
import webbrowser
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import json
import time

# ---------- Config ----------
TIMEZONE = "Asia/Kolkata"
SYMBOLS = {
    "Sensex": "^BSESN",
    "NIFTY": "^NSEI",
    "Paradeep": "PARADEEP.NS",
    "DMart": "DMART.NS",
    # NSE large caps
    "Reliance Industries": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "SBI": "SBIN.NS",
    "ITC": "ITC.NS",
    "Tata Motors": "TATAMOTORS.NS",
    "Nestle India": "NESTLEIND.NS",
    # FX / crypto / commodities
    "USD → INR": "USDINR=X",
    "Bitcoin (USD)": "BTC-USD",
    "Brent (USD/bbl)": "BZ=F",
    "Gold (USD/oz)": "GC=F",
    "Silver (USD/oz)": "SI=F",
}
OUT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MorningStatus")
OUT_FILE = os.path.join(OUT_DIR, "report2.html")
LOG_FILE = os.path.join(OUT_DIR, "fetch.log")
CACHE_FILE = os.path.join(OUT_DIR, "52w_cache.json")
META_REFRESH = 3
# per-ticker timeout (seconds) when refreshing 52-week info
PER_TICKER_TIMEOUT = 8
# max worker threads when refreshing 52w
MAX_52W_WORKERS = 6
# --------------------------------

CURRENCY_SUFFIX = {
    "^BSESN": "₹", "^NSEI": "₹",
    "PARADEEP.NS": "₹", "DMART.NS": "₹",
    "RELIANCE.NS": "₹", "TCS.NS": "₹", "HDFCBANK.NS": "₹", "SBIN.NS": "₹",
    "ITC.NS": "₹", "TATAMOTORS.NS": "₹", "NESTLEIND.NS": "₹",
    "USDINR=X": "₹", "BTC-USD": "$", "BZ=F": "$", "GC=F": "$", "SI=F": "$",
    "GC=F-INR": "₹", "SI=F-INR": "₹",
}


def now_kolkata():
    return datetime.now(pytz.timezone(TIMEZONE))


def today_kolkata_date():
    return now_kolkata().date()


def ensure_outdir():
    os.makedirs(OUT_DIR, exist_ok=True)


def log(msg):
    ensure_outdir()
    ts = datetime.utcnow().isoformat()
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {msg}\n")
    except Exception:
        pass


def write_loading_page():
    ensure_outdir()
    dt = now_kolkata()
    title = "Loading Market Data..."
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta http-equiv="refresh" content="{META_REFRESH}"><style>body{{font-family:Segoe UI,Roboto,Arial;background:#f3f4f6;margin:0}}.card{{max-width:760px;margin:10vh auto;background:white;padding:20px;border-radius:10px;box-shadow:0 8px 30px rgba(2,6,23,0.08)}}h1{{margin:0}}p{{color:#475569}}</style>
</head><body><div class="card"><h1>{title}</h1><p>Opened at {html.escape(dt.strftime('%I:%M:%S %p (%Z)'))} — this page refreshes every {META_REFRESH}s until data appears.</p>
<p style="color:#94a3b8">If nothing appears after ~15s, open fetch.log in the MorningStatus folder for diagnostics.</p></div></body></html>"""
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(page)


def open_report_immediately():
    file_url = "file:///" + OUT_FILE.replace("\\", "/")
    try:
        webbrowser.open(file_url, new=1)
    except Exception:
        try:
            os.startfile(OUT_FILE)
        except Exception:
            pass


def spawn_detached_fetch():
    python = sys.executable
    script = os.path.abspath(__file__)
    args = [python, script, "--fetch"]
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200
        try:
            subprocess.Popen(args, creationflags=creationflags, close_fds=True)
            return
        except Exception as e:
            log(f"spawn_detached_fetch Popen error: {repr(e)}")
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except Exception as e:
        log(f"spawn_detached_fetch fallback Popen error: {repr(e)}")


# ----------------- 52-week cache helpers -----------------
def load_52w_cache():
    try:
        if not os.path.exists(CACHE_FILE):
            return {}
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Expect structure: {"date": "YYYY-MM-DD", "values": {"SYM": {"yearHigh": x, "yearLow": y}, ...}}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log(f"load_52w_cache error: {repr(e)}")
        return {}


def save_52w_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        log(f"save_52w_cache error: {repr(e)}")


def cache_is_fresh(cache):
    try:
        if not cache:
            return False
        cdate = cache.get("date")
        if not cdate:
            return False
        return cdate == today_kolkata_date().isoformat()
    except Exception:
        return False


# ----------------- Fetching: DAILY BARS only (simpler daily-close logic) + cached 52w -----------------
def fetch_with_yfinance_fast():
    try:
        import yfinance as yf
        import pandas as pd
    except Exception as e:
        log(f"yfinance import error: {repr(e)}")
        return {}

    symbol_to_name = {sym: name for name, sym in SYMBOLS.items()}
    symbols_list = list(symbol_to_name.keys())
    out = {}

    # Batch fetch 2 daily bars (today + yesterday) - run with threads=False and a wrapper timeout
    batch = None
    try:
        # run download in worker to allow timeout
        def _do_download():
            return yf.download(
                tickers=symbols_list,
                period="2d",
                interval="1d",
                group_by="ticker",
                threads=False,  # more reliable
                progress=False,
            )
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_do_download)
            try:
                batch = fut.result(timeout=30)
            except Exception as e:
                fut.cancel()
                log(f"yf.download timed out/failed: {repr(e)}")
                batch = None
    except Exception as e:
        log(f"batch download wrapper error: {repr(e)}")
        batch = None

    def extract_from_batch(sym, batch_df):
        try:
            if batch_df is None or getattr(batch_df, "empty", True):
                return None
            # multi-ticker DataFrame?
            if isinstance(batch_df.columns, pd.MultiIndex):
                if sym not in batch_df.columns.levels[0]:
                    return None
                df = batch_df[sym].dropna(how="all")
            else:
                df = batch_df.dropna(how="all")
            if len(df) < 2:
                return None
            # find Close column
            close_col = "Close" if "Close" in df.columns else ("close" if "close" in df.columns else None)
            if close_col is None:
                numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                if not numeric_cols:
                    return None
                close_col = numeric_cols[-1]
            today_close = float(df[close_col].iloc[-1])
            yday_close = float(df[close_col].iloc[-2])
            change = today_close - yday_close
            change_pct = (change / yday_close * 100) if yday_close else 0.0
            # timestamp
            idx = df.index[-1]
            try:
                ts_dt = idx.to_pydatetime()
                ts_ist = ts_dt.astimezone(pytz.timezone(TIMEZONE)).strftime("%H:%M")
            except Exception:
                ts_ist = now_kolkata().strftime("%H:%M")
            return {"price": today_close, "change": change, "change_pct": change_pct, "time": ts_ist, "source": "daily-bars"}
        except Exception as e:
            log(f"extract_from_batch error {sym}: {repr(e)}")
            return None

    if batch is not None:
        for sym in symbols_list:
            try:
                res = extract_from_batch(sym, batch)
                if res:
                    out[sym] = {"display_name": symbol_to_name[sym], **res}
            except Exception as e:
                log(f"extract_from_batch error for {sym}: {repr(e)}")

    # ----------------- 52-week logic with caching -----------------
    # load cache
    cache = load_52w_cache()
    if cache_is_fresh(cache):
        log("Using fresh 52w cache")
        cached_values = cache.get("values", {})
        for s in symbols_list:
            if s not in out:
                out[s] = {"display_name": symbol_to_name.get(s, s)}
            vals = cached_values.get(s, {})
            out[s]["yearHigh"] = vals.get("yearHigh")
            out[s]["yearLow"] = vals.get("yearLow")
    else:
        # refresh cache (fetch 52w for all symbols, but with per-ticker timeout)
        log("Refreshing 52w cache (this runs with per-ticker timeouts)")
        results = {}

        def fetch_52w_for(s):
            try:
                t = yf.Ticker(s)
                fi = getattr(t, "fast_info", None)
                info = getattr(t, "info", {}) or {}
                yr_high = None
                yr_low = None
                if fi:
                    yr_high = fi.get("yearHigh") or fi.get("fiftyTwoWeekHigh") or fi.get("52WeekHigh")
                    yr_low = fi.get("yearLow") or fi.get("fiftyTwoWeekLow") or fi.get("52WeekLow")
                if yr_high is None:
                    yr_high = info.get("fiftyTwoWeekHigh") or info.get("52WeekHigh")
                if yr_low is None:
                    yr_low = info.get("fiftyTwoWeekLow") or info.get("52WeekLow")
                return s, {"yearHigh": yr_high, "yearLow": yr_low}
            except Exception as e:
                log(f"52w fetch error {s}: {repr(e)}")
                return s, {"yearHigh": None, "yearLow": None}

        # Use a limited threadpool and per-future timeout
        with ThreadPoolExecutor(max_workers=min(MAX_52W_WORKERS, len(symbols_list))) as ex:
            futures = {ex.submit(fetch_52w_for, s): s for s in symbols_list}
            for fut in as_completed(futures):
                s = futures[fut]
                try:
                    sret, vals = fut.result(timeout=PER_TICKER_TIMEOUT)
                    results[sret] = vals
                except Exception as e:
                    # timeout or exception -> mark as None
                    log(f"52w future error/timeout for {s}: {repr(e)}")
                    results[s] = {"yearHigh": None, "yearLow": None}

        # save cache with today's date (in IST)
        cache_payload = {"date": today_kolkata_date().isoformat(), "values": results}
        try:
            save_52w_cache(cache_payload)
            log("Saved new 52w cache")
        except Exception as e:
            log(f"save_52w_cache failed: {repr(e)}")

        # merge results into out
        for s in symbols_list:
            if s not in out:
                out[s] = {"display_name": symbol_to_name.get(s, s)}
            vals = results.get(s, {})
            out[s]["yearHigh"] = vals.get("yearHigh")
            out[s]["yearLow"] = vals.get("yearLow")

    return out


# --- Build final HTML (with Gold & Silver INR derivation) ---
def build_final_html(quote_map):
    dt = now_kolkata()
    greet = ("Good Morning" if 5 <= dt.hour < 12 else
             "Good Afternoon" if 12 <= dt.hour < 17 else
             "Good Evening" if 17 <= dt.hour < 22 else "Hello")
    title = f"{greet} Super Genius Master!"
    timestamp = dt.strftime("%A, %d %b %Y %I:%M %p (%Z)")

    # derive Gold (INR/10g) and Silver (INR/kg) if possible
    usd_inr_sym = "USDINR=X"
    gold_sym = "GC=F"
    silver_sym = "SI=F"
    if usd_inr_sym in quote_map and gold_sym in quote_map:
        usd_inr = quote_map.get(usd_inr_sym, {}).get("price")
        gold_usd = quote_map.get(gold_sym, {}).get("price")
        if usd_inr is not None and gold_usd is not None:
            try:
                inr_per_10g = gold_usd * usd_inr / 3.11035
                quote_map["GC=F-INR"] = {"display_name": "Gold (INR/10g)", "price": inr_per_10g, "change": None, "change_pct": None, "time": quote_map[gold_sym].get("time"), "source": "derived"}
            except Exception:
                pass
    if usd_inr_sym in quote_map and silver_sym in quote_map:
        usd_inr = quote_map.get(usd_inr_sym, {}).get("price")
        silver_usd = quote_map.get(silver_sym, {}).get("price")
        if usd_inr is not None and silver_usd is not None:
            try:
                inr_per_kg = silver_usd * usd_inr * (1000.0 / 31.1035)
                quote_map["SI=F-INR"] = {"display_name": "Silver (INR/kg)", "price": inr_per_kg, "change": None, "change_pct": None, "time": quote_map[silver_sym].get("time"), "source": "derived"}
            except Exception:
                pass

    def get_suffix_for_symbol(sym):
        if not sym:
            return ""
        if sym in CURRENCY_SUFFIX:
            return CURRENCY_SUFFIX[sym]
        if sym.endswith('.NS') or sym.startswith('^') or 'INR' in sym:
            return '₹'
        return '$'

    def format_cell_value(val, sym, digits=2):
        if val is None:
            return "N/A"
        try:
            suffix = get_suffix_for_symbol(sym)
            return f"{float(val):,.{digits}f} {suffix}"
        except Exception:
            return str(val)

    def make_row(display_name, e, sym=None):
        price = e.get("price") if e else None
        price_str = format_cell_value(price, sym) if price is not None else "N/A"
        change = e.get("change") if e else None
        change_pct = e.get("change_pct") if e else None
        chs = f"{change:+.2f}" if change is not None and not math.isnan(change) else "—"
        pc = f"{change_pct:+.2f}%" if change_pct is not None and not math.isnan(change_pct) else "—"
        time_str = e.get("time") if e else ""
        cls = "neutral"
        try:
            if change is not None and not math.isnan(change):
                cls = "up" if float(change) > 0 else ("down" if float(change) < 0 else "neutral")
        except Exception:
            cls = "neutral"
        yr_high = e.get("yearHigh") if e else None
        yr_low = e.get("yearLow") if e else None
        high_str = format_cell_value(yr_high, sym) if yr_high is not None else "—"
        low_str = format_cell_value(yr_low, sym) if yr_low is not None else "—"
        return f"<tr><td>{html.escape(display_name)}</td><td style='text-align:right;font-weight:700'>{price_str}</td><td style='text-align:right' class='{cls}'>{chs}</td><td style='text-align:right' class='{cls}'>{pc}</td><td style='text-align:right'>{html.escape(time_str)}</td><td style='text-align:right'>{low_str}</td><td style='text-align:right'>{high_str}</td></tr>"

    rows_html = ""
    for display_name, sym in SYMBOLS.items():
        e = quote_map.get(sym, {})
        rows_html += make_row(display_name, e, sym)

    # derived rows
    if "GC=F-INR" in quote_map:
        rows_html += make_row(quote_map["GC=F-INR"]["display_name"], quote_map["GC=F-INR"], "GC=F-INR")
    if "SI=F-INR" in quote_map:
        rows_html += make_row(quote_map["SI=F-INR"]["display_name"], quote_map["SI=F-INR"], "SI=F-INR")

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>:root{{--bg:#f7fafc;--card:#fff;--muted:#94a3b8;--green:#059669;--red:#ef4444;--accent:#0ea5a4}}
body{{font-family:Segoe UI,Roboto,Arial;background:var(--bg);margin:18px;color:#0f172a}}
.card{{max-width:980px;margin:18px auto;background:var(--card);padding:18px;border-radius:10px;box-shadow:0 6px 18px rgba(2,6,23,0.06)}}
h1{{margin:0;font-size:20px}}.sub{{color:#475569;margin-top:6px;font-size:13px}}
table{{width:100%;border-collapse:collapse;margin-top:12px;font-variant-numeric:tabular-nums}}
th,td{{padding:10px 8px;font-size:13px}}
th{{text-transform:uppercase;font-size:11px;color:#64748b;font-weight:700}}
tr+tr{{border-top:1px solid #eef2f7}}
.up{{color:var(--green);font-weight:700}}.down{{color:var(--red);font-weight:700}}.neutral{{color:#374151}}.muted{{color:var(--muted)}}
.controls{{margin-top:14px;display:flex;justify-content:space-between;align-items:center}}.btn{{background:var(--accent);color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font-weight:700}}
</style></head><body>
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div><h1>{html.escape(title)}</h1><div class="sub">{html.escape(timestamp)}</div></div>
    <div style="text-align:right"><div class="sub">Updated</div></div>
  </div>
  <table><thead><tr>
    <th>Instrument</th><th style="text-align:right">Price</th><th style="text-align:right">Change</th><th style="text-align:right">%Chg</th><th style="text-align:right">Time (IST)</th><th style="text-align:right">52Wk Low</th><th style="text-align:right">52Wk High</th>
  </tr></thead>
  <tbody>{rows_html}</tbody></table>
  <div class="controls"><div class="sub">Source: yfinance (daily-bars; cached 52w). Derived Gold & Silver INR when available.</div><div><a class="btn" href="#" onclick="location.reload();return false;">Refresh</a></div></div>
</div></body></html>"""
    return page


# --- Fetch & write ---
def fetch_and_write():
    ensure_outdir()
    log("fetch_and_write start - daily-bars with cached 52w")
    try:
        quote_map = fetch_with_yfinance_fast()
        html_text = build_final_html(quote_map)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.write(html_text)
        ok = [v.get("display_name", k) for k, v in quote_map.items() if v and v.get("price") is not None]
        log(f"fetch_and_write complete; symbols: {ok}")
    except Exception as e:
        log(f"fetch_and_write ERROR: {repr(e)}\n{traceback.format_exc()}")


# --- Main entry points ---
def main_parent():
    write_loading_page()
    open_report_immediately()
    spawn_detached_fetch()


def main_fetch_mode():
    fetch_and_write()


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        main_fetch_mode()
    else:
        main_parent()
