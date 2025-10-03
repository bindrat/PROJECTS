#!/usr/bin/env python3
"""
morning_status_fast_detach_v4_fixed_with_silver_currency_suffix_with_nse_stocks.py

Same script as before but appends currency symbols at the END of displayed prices with a space (e.g., 1,234.56 ₹).

This file is a corrected, complete version (previous edit accidentally truncated the fetch function).
Added: Reliance, TCS, HDFC Bank, ITC, Tata Motors, Nestle India (NSE tickers).
"""

import os, sys, subprocess, traceback
from datetime import datetime
import pytz, webbrowser, html
from concurrent.futures import ThreadPoolExecutor, as_completed
import math

# ---------- Config ----------
TIMEZONE = "Asia/Kolkata"
SYMBOLS = {
    "Sensex": "^BSESN",
    "NIFTY": "^NSEI",
    "Paradeep": "PARADEEP.NS",
    "DMart": "DMART.NS",
    # === Added NSE large caps ===
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
    "Silver (USD/oz)": "SI=F",   # <-- added silver
}
OUT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MorningStatus")
OUT_FILE = os.path.join(OUT_DIR, "report.html")
LOG_FILE = os.path.join(OUT_DIR, "fetch.log")
META_REFRESH = 3
BATCH_INTERVAL = "5m"
# --------------------------------

# explicit mapping for currency suffix to be appended after numeric price
CURRENCY_SUFFIX = {
    "^BSESN": "₹",
    "^NSEI": "₹",
    "PARADEEP.NS": "₹",
    "DMART.NS": "₹",
    # === added explicit NSE mappings ===
    "RELIANCE.NS": "₹",
    "TCS.NS": "₹",
    "HDFCBANK.NS": "₹",
    "SBIN.NS": "₹",
    "ITC.NS": "₹",
    "TATAMOTORS.NS": "₹",
    "NESTLEIND.NS": "₹",
    "USDINR=X": "₹",
    "BTC-USD": "$",
    "BZ=F": "$",
    "GC=F": "$",
    "SI=F": "$",
    # derived
    "GC=F-INR": "₹",
    "SI=F-INR": "₹",
}


def now_kolkata():
    return datetime.now(pytz.timezone(TIMEZONE))


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

# --- Fetching: batch + robust extraction + fast_info fallback ---
def fetch_with_yfinance_fast():
    try:
        import yfinance as yf
        import pandas as pd
    except Exception as e:
        log(f"yfinance import error: {repr(e)}")
        return {}

    # reverse mapping for convenience
    symbol_to_name = {sym: name for name, sym in SYMBOLS.items()}
    symbols_list = list(symbol_to_name.keys())
    out = {}

    # Attempt batch download (2 days so we can compute vs previous trading day close)
    try:
        batch = yf.download(
            tickers=symbols_list,
            period="2d",            # <-- changed from "1d" to "2d"
            interval=BATCH_INTERVAL,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as e:
        log(f"batch download failed: {repr(e)}")
        batch = None

    def is_valid_number(x):
        return x is not None and not (isinstance(x, float) and math.isnan(x))

    # robust extractor for various batch shapes
    def extract_from_batch(sym, batch_df):
        try:
            if batch_df is None:
                return None
            # Case 1: dictionary-like (older yfinance) - sometimes returns dict
            if isinstance(batch_df, dict):
                df = batch_df.get(sym)
                if df is None or df.empty:
                    return None
            else:
                df = None
                # MultiIndex columns? e.g. columns.levels[0] contains symbol
                if hasattr(batch_df, "columns") and isinstance(batch_df.columns, pd.MultiIndex):
                    top_levels = list(batch_df.columns.levels[0])
                    if sym in top_levels:
                        try:
                            df = batch_df[sym].dropna(how='all')
                        except Exception:
                            df = batch_df.loc[:, sym]
                else:
                    # Single level columns: sometimes yfinance returns DataFrame with ('Close',) or direct Close column when single ticker
                    if sym in batch_df.columns:
                        df = batch_df[[sym]].dropna(how='all')
                    else:
                        # try heuristics: find columns that are tuples with first element equal to sym
                        cols = [c for c in batch_df.columns if isinstance(c, tuple) and c and c[0] == sym]
                        if cols:
                            df = batch_df[cols[0]].dropna(how='all')
                        else:
                            # if batch_df is a DataFrame for single ticker, try using it directly
                            if len(batch_df.columns) >= 1 and len(symbols_list) == 1:
                                df = batch_df.dropna(how='all')
                            else:
                                df = None
            if df is None or getattr(df, "empty", True):
                return None
            # find a Close column in df
            close_col = None
            for candidate in ("Close", "close", ("Close",), ("close",)):
                try:
                    if candidate in df.columns:
                        close_col = candidate
                        break
                except Exception:
                    pass
            # fallback: if df has exactly one numeric column, use that
            if close_col is None:
                numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                if numeric_cols:
                    close_col = numeric_cols[-1]
            if close_col is None:
                return None
            # ensure there is at least one row
            if len(df) < 1:
                return None
            last_row = df.iloc[-1]
            price = last_row.get(close_col) if isinstance(last_row, (pd.Series,)) else float(last_row)
            # previous value: prefer previous calendar-day close (previous trading day).
            prev = price
            try:
                last_idx = df.index[-1]
                # try to get a date object (works for pandas.Timestamp)
                try:
                    last_date = last_idx.date()
                except Exception:
                    # fallback: treat as same-day only, so previous-row logic will apply below
                    last_date = None
                prev_found = False
                if last_date is not None:
                    # find the most recent row with date < last_date
                    prev_idx = None
                    for i in range(len(df.index) - 1, -1, -1):
                        idx = df.index[i]
                        try:
                            idx_date = idx.date()
                        except Exception:
                            # if we can't get date, skip
                            continue
                        if idx_date < last_date:
                            prev_idx = i
                            break
                    if prev_idx is not None:
                        prev_val = df[close_col].iloc[prev_idx]
                        if is_valid_number(prev_val):
                            prev = float(prev_val)
                            prev_found = True
                if not prev_found:
                    # fallback: use previous row if available
                    if len(df) > 1:
                        prev_row_val = df[close_col].iloc[-2]
                        if is_valid_number(prev_row_val):
                            prev = float(prev_row_val)
                        else:
                            prev = price
                    else:
                        prev = price
            except Exception:
                # any error -> fallback to previous-row or price itself
                try:
                    prev = float(df[close_col].iloc[-2]) if len(df) > 1 else price
                except Exception:
                    prev = price
            # timestamp from index
            idx = df.index[-1]
            # make tz-aware: if tzinfo present, treat as is, else assume UTC
            try:
                if hasattr(idx, "tzinfo") and idx.tzinfo is not None:
                    ts_utc = idx.to_pydatetime().astimezone(pytz.UTC)
                else:
                    ts_utc = idx.to_pydatetime().replace(tzinfo=pytz.UTC)
            except Exception:
                # fallback to now
                ts_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
            ts_ist = ts_utc.astimezone(pytz.timezone(TIMEZONE)).strftime("%H:%M")
            # compute change safely
            try:
                price_f = float(price)
                prev_f = float(prev) if prev is not None else price_f
                change = price_f - prev_f
                change_pct = (change / prev_f * 100) if prev_f else 0.0
            except Exception:
                change = None
                change_pct = None
            if not is_valid_number(price):
                return None
            return {"price": float(price), "change": change, "change_pct": change_pct, "time": ts_ist, "source": "batch-history"}
        except Exception:
            return None

    # fill out from batch
    if batch is not None:
        for sym in symbols_list:
            try:
                res = extract_from_batch(sym, batch)
                if res:
                    out[sym] = {"display_name": symbol_to_name[sym], **res}
            except Exception as e:
                log(f"extract_from_batch error for {sym}: {repr(e)}")

    # prepare missing list
    missing = [s for s in symbols_list if s not in out]

    # fast_info fallback in parallel for missing
    if missing:
        def fetch_fast(s):
            try:
                t = yf.Ticker(s)
                fi = getattr(t, "fast_info", None)
                price = None
                source = None
                prev_from_info = None
                info = {}
                if fi:
                    # try common fields
                    price = fi.get("last_price") or fi.get("last") or fi.get("previous_close")
                    prev_from_info = fi.get("previous_close") or fi.get("previousClose") or fi.get("previous_close")
                    source = "fast_info"
                else:
                    # try minimal info
                    info = getattr(t, "info", {}) or {}
                    price = info.get("regularMarketPrice") or info.get("previousClose")
                    prev_from_info = info.get("previousClose") or info.get("previous_close")
                    source = "info_fallback"
                # ensure numeric
                if price is not None:
                    price = float(price)
                try:
                    prev_val = float(prev_from_info) if prev_from_info is not None else None
                except Exception:
                    prev_val = None
                change = None
                change_pct = None
                if price is not None and prev_val is not None:
                    try:
                        change = price - prev_val
                        change_pct = (change / prev_val * 100) if prev_val else 0.0
                    except Exception:
                        change = None
                        change_pct = None
                ts_ist = now_kolkata().strftime("%H:%M")
                return s, {"display_name": symbol_to_name.get(s, s), "price": price, "change": change, "change_pct": change_pct, "time": ts_ist, "source": source}
            except Exception as e:
                return s, {"display_name": symbol_to_name.get(s, s), "price": None, "change": None, "change_pct": None, "time": None, "source": None}

        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as ex:
            futures = {ex.submit(fetch_fast, s): s for s in missing}
            for fut in as_completed(futures):
                s, res = fut.result()
                out[s] = res

    return out


    def is_valid_number(x):
        return x is not None and not (isinstance(x, float) and math.isnan(x))

    # robust extractor for various batch shapes
    def extract_from_batch(sym, batch_df):
        try:
            if batch_df is None:
                return None
            # Case 1: dictionary-like (older yfinance) - sometimes returns dict
            if isinstance(batch_df, dict):
                df = batch_df.get(sym)
                if df is None or df.empty:
                    return None
            else:
                df = None
                # MultiIndex columns? e.g. columns.levels[0] contains symbol
                if hasattr(batch_df, "columns") and isinstance(batch_df.columns, pd.MultiIndex):
                    top_levels = list(batch_df.columns.levels[0])
                    if sym in top_levels:
                        try:
                            df = batch_df[sym].dropna(how='all')
                        except Exception:
                            df = batch_df.loc[:, sym]
                else:
                    # Single level columns: sometimes yfinance returns DataFrame with ('Close',) or direct Close column when single ticker
                    if sym in batch_df.columns:
                        df = batch_df[[sym]].dropna(how='all')
                    else:
                        # try heuristics: find columns that are tuples with first element equal to sym
                        cols = [c for c in batch_df.columns if isinstance(c, tuple) and c and c[0] == sym]
                        if cols:
                            df = batch_df[cols[0]].dropna(how='all')
                        else:
                            # if batch_df is a DataFrame for single ticker, try using it directly
                            if len(batch_df.columns) >= 1 and len(symbols_list) == 1:
                                df = batch_df.dropna(how='all')
                            else:
                                df = None
            if df is None or getattr(df, "empty", True):
                return None
            # find a Close column in df
            close_col = None
            for candidate in ("Close", "close", ("Close",), ("close",)):
                try:
                    if candidate in df.columns:
                        close_col = candidate
                        break
                except Exception:
                    pass
            # fallback: if df has exactly one numeric column, use that
            if close_col is None:
                numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                if numeric_cols:
                    close_col = numeric_cols[-1]
            if close_col is None:
                return None
            # ensure there is at least one row
            if len(df) < 1:
                return None
            last_row = df.iloc[-1]
            price = last_row.get(close_col) if isinstance(last_row, (pd.Series,)) else float(last_row)
            # previous value
            if len(df) > 1:
                prev_row = df[close_col].iloc[-2]
                prev = float(prev_row) if is_valid_number(prev_row) else price
            else:
                prev = price
            # timestamp from index
            idx = df.index[-1]
            # make tz-aware: if tzinfo present, treat as is, else assume UTC
            try:
                if hasattr(idx, "tzinfo") and idx.tzinfo is not None:
                    ts_utc = idx.to_pydatetime().astimezone(pytz.UTC)
                else:
                    ts_utc = idx.to_pydatetime().replace(tzinfo=pytz.UTC)
            except Exception:
                # fallback to now
                ts_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
            ts_ist = ts_utc.astimezone(pytz.timezone(TIMEZONE)).strftime("%H:%M")
            # compute change safely
            try:
                price_f = float(price)
                prev_f = float(prev) if prev is not None else price_f
                change = price_f - prev_f
                change_pct = (change / prev_f * 100) if prev_f else 0.0
            except Exception:
                change = None
                change_pct = None
            if not is_valid_number(price):
                return None
            return {"price": float(price), "change": change, "change_pct": change_pct, "time": ts_ist, "source": "batch-history"}
        except Exception:
            return None

    # fill out from batch
    if batch is not None:
        for sym in symbols_list:
            try:
                res = extract_from_batch(sym, batch)
                if res:
                    out[sym] = {"display_name": symbol_to_name[sym], **res}
            except Exception as e:
                log(f"extract_from_batch error for {sym}: {repr(e)}")

    # prepare missing list
    missing = [s for s in symbols_list if s not in out]

    # fast_info fallback in parallel for missing
    if missing:
        def fetch_fast(s):
            try:
                t = yf.Ticker(s)
                fi = getattr(t, "fast_info", None)
                price = None
                source = None
                if fi:
                    # try common fields
                    price = fi.get("last_price") or fi.get("last") or fi.get("previous_close")
                    source = "fast_info"
                else:
                    # try minimal info
                    info = getattr(t, "info", {}) or {}
                    price = info.get("regularMarketPrice") or info.get("previousClose")
                    source = "info_fallback"
                # ensure numeric
                if price is not None:
                    price = float(price)
                ts_ist = now_kolkata().strftime("%H:%M")
                return s, {"display_name": symbol_to_name.get(s, s), "price": price, "change": None, "change_pct": None, "time": ts_ist, "source": source}
            except Exception as e:
                return s, {"display_name": symbol_to_name.get(s, s), "price": None, "change": None, "change_pct": None, "time": None, "source": None}

        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as ex:
            futures = {ex.submit(fetch_fast, s): s for s in missing}
            for fut in as_completed(futures):
                s, res = fut.result()
                out[s] = res

    return out

# --- Build final HTML (with Gold & Silver INR derivation) ---
def build_final_html(quote_map):
    dt = now_kolkata()
    greet = ("Good Morning" if 5 <= dt.hour < 12 else
             "Good Afternoon" if 12 <= dt.hour < 17 else
             "Good Evening" if 17 <= dt.hour < 22 else "Hello")
    title = f"{greet} Super Genius Master!"
    timestamp = dt.strftime("%A, %d %b %Y %I:%M %p (%Z)")

    # derive Gold (INR/10g) if possible
    usd_inr_sym = "USDINR=X"
    gold_sym = "GC=F"
    silver_sym = "SI=F"
    if usd_inr_sym in quote_map and gold_sym in quote_map:
        usd_inr = quote_map.get(usd_inr_sym, {}).get("price")
        gold_usd = quote_map.get(gold_sym, {}).get("price")
        if usd_inr is not None and gold_usd is not None:
            try:
                inr_per_10g = gold_usd * usd_inr / 3.11035  # 1 oz -> 31.1035 g -> 3.11035 * 10g
                quote_map["GC=F-INR"] = {"display_name": "Gold (INR/10g)", "price": inr_per_10g, "change": None, "change_pct": None, "time": quote_map[gold_sym].get("time"), "source": "derived"}
            except Exception:
                pass

    # derive Silver (INR/kg) if possible
    if usd_inr_sym in quote_map and silver_sym in quote_map:
        usd_inr = quote_map.get(usd_inr_sym, {}).get("price")
        silver_usd = quote_map.get(silver_sym, {}).get("price")
        if usd_inr is not None and silver_usd is not None:
            try:
                # 1 oz = 31.1035 g ; 1 kg = 1000 g
                # convert USD/oz -> INR/kg: silver_usd * usd_inr * (1000 / 31.1035)
                inr_per_kg = silver_usd * usd_inr * (1000.0 / 31.1035)
                quote_map["SI=F-INR"] = {"display_name": "Silver (INR/kg)", "price": inr_per_kg, "change": None, "change_pct": None, "time": quote_map[silver_sym].get("time"), "source": "derived"}
            except Exception:
                pass

    def get_suffix_for_symbol(sym):
        if not sym:
            return ""
        if sym in CURRENCY_SUFFIX:
            return CURRENCY_SUFFIX[sym]
        # heuristics: if .NS or endswith .NS -> INR
        if sym.endswith('.NS') or sym.startswith('^') or sym.endswith('INR=X') or 'INR' in sym and '=' in sym:
            return '₹'
        # default USD
        return '$'

    def format_cell_value(val, sym):
        if val is None:
            return "N/A"
        try:
            suffix = get_suffix_for_symbol(sym)
            return f"{float(val):,.2f} {suffix}"  # <-- space before suffix
        except Exception:
            return str(val)

    def make_row(display_name, e, sym=None):
        if not e or e.get("price") is None:
            return f"<tr><td>{html.escape(display_name)}</td><td style='text-align:right;color:#94a3b8'>N/A</td><td style='text-align:right;color:#94a3b8'>—</td><td style='text-align:right;color:#94a3b8'>—</td><td style='text-align:right'>—</td></tr>"
        price_val = e.get("price")
        price_str = format_cell_value(price_val, sym)
        change = e.get("change")
        chs = f"{change:+.2f}" if change is not None and not math.isnan(change) else "—"
        change_pct = e.get("change_pct")
        pc = f"{change_pct:+.2f}%" if change_pct is not None and not math.isnan(change_pct) else "—"
        time_str = e.get("time") or ""
        cls = "neutral"
        try:
            if change is not None and not math.isnan(change):
                cls = "up" if float(change) > 0 else ("down" if float(change) < 0 else "neutral")
        except Exception:
            cls = "neutral"
        return f"<tr><td>{html.escape(display_name)}</td><td style='text-align:right;font-weight:700'>{price_str}</td><td style='text-align:right' class='{cls}'>{chs}</td><td style='text-align:right' class='{cls}'>{pc}</td><td style='text-align:right'>{html.escape(time_str)}</td></tr>"

    rows_html = ""
    # keep the same SYMBOLS order
    for display_name, sym in SYMBOLS.items():
        e = quote_map.get(sym)
        rows_html += make_row(display_name, e, sym)
    # add derived rows if present
    if "GC=F-INR" in quote_map:
        rows_html += make_row(quote_map["GC=F-INR"]["display_name"], quote_map["GC=F-INR"], "GC=F-INR")
    if "SI=F-INR" in quote_map:
        rows_html += make_row(quote_map["SI=F-INR"]["display_name"], quote_map["SI=F-INR"], "SI=F-INR")

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>:root{{--bg:#f7fafc;--card:#fff;--muted:#94a3b8;--green:#059669;--red:#ef4444;--accent:#0ea5a4}}
body{{font-family:Segoe UI,Roboto,Arial;background:var(--bg);margin:18px;color:#0f172a}}
.card{{max-width:760px;margin:18px auto;background:var(--card);padding:18px;border-radius:10px;box-shadow:0 6px 18px rgba(2,6,23,0.06)}}
h1{{margin:0;font-size:20px}}.sub{{color:#475569;margin-top:6px;font-size:13px}}
table{{width:100%;border-collapse:collapse;margin-top:12px;font-variant-numeric:tabular-nums}}
th,td{{padding:10px 8px;font-size:14px}}
th{{text-transform:uppercase;font-size:11px;color:#64748b;font-weight:700}}
tr+tr{{border-top:1px solid #eef2f7}}
.up{{color:var(--green);font-weight:700}}.down{{color:var(--red);font-weight:700}}.neutral{{color:#374151}}.muted{{color:var(--muted)}}
.controls{{margin-top:14px;display:flex;justify-content:space-between;align-items:center}}.btn{{background:var(--accent);color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font-weight:700}}</style>
</head><body>
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div><h1>{html.escape(title)}</h1><div class="sub">{html.escape(timestamp)}</div></div>
    <div style="text-align:right"><div class="sub">Updated</div></div>
  </div>
  <table><thead><tr><th>Instrument</th><th style="text-align:right">Price</th><th style="text-align:right">Change</th><th style="text-align:right">%Chg</th><th style="text-align:right">Time (IST)</th></tr></thead>
  <tbody>{rows_html}</tbody></table>
  <div class="controls"><div class="sub">Source: yfinance (batch + fast_info; derived Gold & Silver INR)</div><div><a class="btn" href="#" onclick="location.reload();return false;">Refresh</a></div></div>
</div></body></html>"""
    return page

# --- Fetch & write ---
def fetch_and_write():
    ensure_outdir()
    log("fetch_and_write start - fixed fast mode (with silver) - currency suffixes")
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
