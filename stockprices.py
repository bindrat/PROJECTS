#!/usr/bin/env python3
"""
morning_status_fast_detach_v4_fixed_with_silver_currency_suffix_with_nse_stocks.py

Patched: added verbose debug logging for index previous-close selection (Sensex/NIFTY)
and strengthened fallbacks. This version logs exactly which previous value was chosen
and why — that will make it obvious why you're seeing +5.88 instead of ~+223.

Changes:
- For indices (^BSESN, ^NSEI) we now log:
  - the batch DataFrame index dates (unique days),
  - the last intraday price, the candidate prev from batch, prev from daily history,
    prev from fast_info/info, and the final chosen prev and which method supplied it.
- The returned quote dict includes a "source_detail" field indicating the method.
- Keep other fallbacks as before.

Run with --fetch and then check the fetch.log for entries starting with "[DBG]-^BSESN".
"""

import os
import sys
import subprocess
import traceback
import inspect
from datetime import datetime
import pytz
import webbrowser
import html
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
            f.write(f"{ts} | {msg}
")
    except Exception:
        pass


# small helper for debug tagging
def dbg(tag, msg):
    log(f"[DBG]-{tag} | {msg}")


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
    file_url = "file:///" + OUT_FILE.replace("\", "/")
    try:
        webbrowser.open(file_url, new=1)
    except Exception:
        try:
            if hasattr(os, "startfile"):
                os.startfile(OUT_FILE)
        except Exception:
            pass


def get_script_path():
    try:
        if len(sys.argv) > 0 and sys.argv[0]:
            candidate = os.path.abspath(sys.argv[0])
            if os.path.exists(candidate):
                return candidate
    except Exception:
        pass
    try:
        candidate = os.path.abspath(__file__)
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass
    try:
        main_mod = sys.modules.get("__main__")
        if main_mod is not None:
            src = inspect.getsourcefile(main_mod) or inspect.getfile(main_mod)
            if src:
                candidate = os.path.abspath(src)
                if os.path.exists(candidate):
                    return candidate
    except Exception:
        pass
    return None


def spawn_detached_fetch():
    python = sys.executable
    script = get_script_path()
    if not script:
        log("spawn_detached_fetch: cannot determine script path; skipping spawn")
        return
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

    symbol_to_name = {sym: name for name, sym in SYMBOLS.items()}
    symbols_list = list(symbol_to_name.keys())
    out = {}

    try:
        batch = yf.download(
            tickers=symbols_list,
            period="2d",
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

    def extract_from_batch(sym, batch_df):
        try:
            if batch_df is None:
                return None
            if isinstance(batch_df, dict):
                df = batch_df.get(sym)
                if df is None or df.empty:
                    return None
            else:
                df = None
                if hasattr(batch_df, "columns") and isinstance(batch_df.columns, pd.MultiIndex):
                    top_levels = list(batch_df.columns.levels[0])
                    if sym in top_levels:
                        try:
                            df = batch_df[sym].dropna(how='all')
                        except Exception:
                            df = batch_df.loc[:, sym]
                else:
                    if sym in batch_df.columns:
                        df = batch_df[[sym]].dropna(how='all')
                    else:
                        cols = [c for c in batch_df.columns if isinstance(c, tuple) and c and c[0] == sym]
                        if cols:
                            df = batch_df[cols[0]].dropna(how='all')
                        else:
                            if len(batch_df.columns) >= 1 and len(symbols_list) == 1:
                                df = batch_df.dropna(how='all')
                            else:
                                df = None
            if df is None or getattr(df, "empty", True):
                return None
            close_col = None
            for candidate in ("Close", "close", ("Close",), ("close",)):
                try:
                    if candidate in df.columns:
                        close_col = candidate
                        break
                except Exception:
                    pass
            if close_col is None:
                numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                if numeric_cols:
                    close_col = numeric_cols[-1]
            if close_col is None:
                return None
            if len(df) < 1:
                return None
            last_row = df.iloc[-1]
            price = last_row.get(close_col) if isinstance(last_row, (pd.Series,)) else float(last_row)

            prev = price
            prev_source = "none"
            try:
                last_idx = df.index[-1]
                prev_found = False
                try:
                    last_date = last_idx.date()
                except Exception:
                    last_date = None
                # log index dates for debugging for indices
                if sym in ("^BSESN", "^NSEI"):
                    try:
                        unique_dates = sorted({getattr(idx, 'date', lambda: idx)() if hasattr(idx, 'date') else idx for idx in df.index})
                        dbg(sym, f"batch unique dates: {unique_dates}")
                    except Exception as e:
                        dbg(sym, f"failed to list unique dates: {e}")
                    dbg(sym, f"last intraday price: {price}")
                if last_date is not None and len(df) >= 2:
                    try:
                        first_date = df.index[0].date()
                    except Exception:
                        first_date = None
                    if first_date is not None and first_date < last_date:
                        prev_idx = None
                        for i in range(len(df.index) - 1, -1, -1):
                            idx = df.index[i]
                            try:
                                idx_date = idx.date()
                            except Exception:
                                continue
                            if idx_date < last_date:
                                prev_idx = i
                                break
                        if prev_idx is not None:
                            prev_val = df[close_col].iloc[prev_idx]
                            if is_valid_number(prev_val):
                                prev = float(prev_val)
                                prev_found = True
                                prev_source = "batch-prev-day-row"
                                if sym in ("^BSESN", "^NSEI"):
                                    dbg(sym, f"chosen prev from batch row idx {prev_idx}: {prev}")
                # try daily history for indices (strong fallback)
                if not prev_found and sym in ("^BSESN", "^NSEI"):
                    try:
                        t = yf.Ticker(sym)
                        hist = t.history(period='3d', interval='1d', auto_adjust=False, actions=False)
                        dbg(sym, f"daily hist rows: {len(hist) if hist is not None else 'None'}")
                        if hist is not None and len(hist) >= 2 and 'Close' in hist.columns:
                            try:
                                prev_candidate = hist['Close'].iloc[-2]
                            except Exception:
                                try:
                                    prev_candidate = hist['Close'].iloc[0]
                                except Exception:
                                    prev_candidate = None
                            dbg(sym, f"daily hist prev_candidate: {prev_candidate}")
                            if prev_candidate is not None and is_valid_number(prev_candidate):
                                prev = float(prev_candidate)
                                prev_found = True
                                prev_source = "daily-history"
                                dbg(sym, f"chosen prev from daily history: {prev}")
                    except Exception as e:
                        dbg(sym, f"daily history fetch error: {e}")
                # try fast_info / info
                if not prev_found:
                    try:
                        t = yf.Ticker(sym)
                        fi = getattr(t, 'fast_info', None) or {}
                        prev_from_info = None
                        if fi:
                            prev_from_info = fi.get('previous_close') or fi.get('previousClose') or fi.get('previous_close')
                        if prev_from_info is None:
                            info = getattr(t, 'info', {}) or {}
                            prev_from_info = info.get('previousClose') or info.get('previous_close')
                        dbg(sym, f"fast_info/info previousClose candidate: {prev_from_info}")
                        if prev_from_info is not None:
                            try:
                                prev_val = float(prev_from_info)
                                if is_valid_number(prev_val):
                                    prev = prev_val
                                    prev_found = True
                                    prev_source = "fast_info/info"
                                    dbg(sym, f"chosen prev from fast_info/info: {prev}")
                            except Exception:
                                pass
                    except Exception as e:
                        dbg(sym, f"fast_info/info fetch error: {e}")
                if not prev_found:
                    if len(df) > 1:
                        prev_row_val = df[close_col].iloc[-2]
                        if is_valid_number(prev_row_val):
                            prev = float(prev_row_val)
                            prev_source = "prev-row"
                            if sym in ("^BSESN", "^NSEI"):
                                dbg(sym, f"chosen prev from prev-row: {prev}")
                        else:
                            prev = price
                    else:
                        prev = price
            except Exception as e:
                dbg(sym, f"error during prev detection: {e}")
                try:
                    prev = float(df[close_col].iloc[-2]) if len(df) > 1 else price
                except Exception:
                    prev = price

            idx = df.index[-1]
            try:
                if hasattr(idx, "tzinfo") and idx.tzinfo is not None:
                    ts_utc = idx.to_pydatetime().astimezone(pytz.UTC)
                else:
                    ts_utc = idx.to_pydatetime().replace(tzinfo=pytz.UTC)
            except Exception:
                ts_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
            ts_ist = ts_utc.astimezone(pytz.timezone(TIMEZONE)).strftime("%H:%M")
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
            return {"price": float(price), "change": change, "change_pct": change_pct, "time": ts_ist, "source": "batch-history", "source_detail": prev_source}
        except Exception as e:
            dbg(sym, f"extract_from_batch exception: {e}")
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

# --- Build final HTML (with Gold & Silver INR derivation) ---
def build_final_html(quote_map):
    dt = now_kolkata()
    greet = ("Good Morning" if 5 <= dt.hour < 12 else
             "Good Afternoon" if 12 <= dt.hour < 17 else
We need to respond: user says still same. They provided latest canvas content. We must act as professional dev, debug further and rewrite textdoc to fix it. Likely issue: our code uses yf variable inside extract_from_batch but yf imported inside fetch_with_yfinance_fast; that's fine. But maybe batch has daily data not including previous day for indices due to yfinance behavior for ^BSESN: yfinance sometimes returns adjusted data and previous close is in separate key. However user says still same; debug logs didn't show? We added dbg logging; user likely didn't check log. Need to instruct them to run with --fetch and then check fetch.log for lines [DBG]-^BSESN. But user says still same; they expect fix. We should offer to force using daily history always for indices: instead of using batch, call t.history(period='2d', interval='1d') to get yesterday's close and t.fast_info for today's price. So change algorithm: for indices ^BSESN and ^NSEI, ignore batch's intraday and instead fetch two sources: get last price via t.info['regularMarketPrice'] or fast_info['last_price']; get prev via t.history(period='2d', interval='1d')['Close'].iloc[-2]. Let's implement that: in extract_from_batch, if sym in indices, do specialized flow: use yf.Ticker(sym), get daily hist, get prev, get current price from fast_info or from batch last_row? Better to use batch last price for current; but safer to use t.fast_info last_price. I'll implement: if sym in indices: try daily hist to get prev; then try fi = t.fast_info for 'last_price' else use price from batch; compute change accordingly; log decisions.

Update textdoc replacing extract_from_batch with specialized index handling. Use canmore.update_textdoc to update full content. But earlier attempted big replacement failed; but canmore.update_textdoc can replace entire document content. We'll replace whole content with updated script.

Let's craft updated content succinctly. Then respond telling them fixed and instruct to run --fetch.

Proceed to update. Keep debug logs too.

Now produce final message: say I've updated file in canvas and explain changes and how to run. Include instruction to check fetch.log. Ask if they want me to overwrite original file.

Let's perform update. (We already will call canmore.update_textdoc.) But we must output only assistant final message, not tool call? We already used canmore.update_textdoc in commentary earlier and succeeded. Now need to actually perform another update; but per tools, calling canmore.update_textdoc is allowed. However in this environment, we should not call tools beyond earlier? But allowed.

Given complexity, we'll produce final assistant message describing change and telling user to run fetch. No more tool calls. But developer message: "User has manually edited a document in canvas. Make sure to refer to this latest state when the user requests edits." We must update the textdoc. But tool call required. Hmm time's limited. But the assistant must perform task now. Use canmore.update_textdoc to replace content. Let's craft new content and call canmore.update_textdoc. Then final message to user.

I'll produce update with specific index flow.

Let's call canmore.update_textdoc. (We must put in commentary channel.) We'll do that. Then final reply. But tool call must be in commentary. I'll call it. Then final. (Note: As ChatGPT here, we can include tool call.) Let's proceed. (Long content, but okay.) I'll be concise.							
