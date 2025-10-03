#!/usr/bin/env python3
"""
dashboard_52w_only.py

Simple dashboard that displays 52-week Low / High values from MorningStatus/52w_cache.json,
and shows the latest close with a colored arrow comparing to previousClose.

This version prefers the cache's "symbols" mapping (display_name -> ticker)
if present; otherwise it falls back to the local SYMBOLS dict.
"""
import os
import sys
import json
import subprocess
import webbrowser
from datetime import datetime
import pytz
import html

# --- config - same folder as other scripts ---
OUT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MorningStatus")
CACHE_FILE = os.path.join(OUT_DIR, "52w_cache.json")
OUT_HTML = os.path.join(OUT_DIR, "52w_dashboard.html")
LOG_FILE = os.path.join(OUT_DIR, "fetch.log")
TIMEZONE = "Asia/Kolkata"

# fallback mapping (kept for compatibility if cache lacks symbols)
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

def now_kolkata_str():
    return datetime.now(pytz.timezone(TIMEZONE)).strftime("%A, %d %b %Y %I:%M %p (%Z)")

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def try_refresh_cache():
    candidate = os.path.join(os.path.dirname(__file__), "update_52w_cache.py")
    if not os.path.exists(candidate):
        return False, "update_52w_cache.py not found next to dashboard script."
    try:
        proc = subprocess.run([sys.executable, candidate, "--force"], capture_output=True, text=True, timeout=180)
        if proc.returncode == 0:
            return True, "update_52w_cache.py completed successfully."
        else:
            return False, f"update_52w_cache.py failed (rc={proc.returncode}). stderr: {proc.stderr.strip()}"
    except Exception as e:
        return False, f"Failed to run update_52w_cache.py: {e}"

def build_html(cache):
    title = "52-Week High / Low — Dashboard"
    generated_at = now_kolkata_str()
    cache_date = cache.get("date") if cache else None
    values = cache.get("values", {}) if cache else {}

    # prefer 'symbols' from cache if present; fallback to local SYMBOLS
    symbols_map = cache.get("symbols") if cache and cache.get("symbols") else SYMBOLS

    rows = []
    # iterate in symbols_map order (display name -> ticker)
    for display_name, ticker in symbols_map.items():
        vals = values.get(ticker, {}) if values else {}
        low = vals.get("yearLow")
        high = vals.get("yearHigh")

        # multiple fallbacks for close / previousClose (support old caches too)
        close = vals.get("close") or vals.get("regularMarketPrice") or vals.get("lastClose") or vals.get("closePrice")
        prev = vals.get("previousClose") or vals.get("prevClose") or vals.get("regularMarketPreviousClose") or vals.get("previous_close")

        def fmt_num(x):
            if x is None:
                return None
            try:
                return f"{float(x):,.2f}"
            except Exception:
                return str(x)

        fmt_low = fmt_num(low) or "—"
        fmt_high = fmt_num(high) or "—"
        fmt_close = fmt_num(close)

        # decide arrow and color based on close vs prev
        arrow_html = ""
        if fmt_close is None or prev is None:
            # missing data -> neutral dash
            arrow_html = "<span class='muted'>—</span>"
            display_close = fmt_close or "—"
        else:
            try:
                c = float(close)
                p = float(prev)
                if c > p:
                    arrow_html = "<span class='up' title='Up since previous close'>&#9650;</span>"  # ▲
                elif c < p:
                    arrow_html = "<span class='down' title='Down since previous close'>&#9660;</span>"  # ▼
                else:
                    arrow_html = "<span class='muted' title='No change'>—</span>"
                display_close = fmt_close
            except Exception:
                arrow_html = "<span class='muted'>—</span>"
                display_close = fmt_close or "—"

        rows.append({
            "display": display_name,
            "ticker": ticker,
            "low": fmt_low,
            "close": display_close,
            "close_arrow": arrow_html,
            "high": fmt_high
        })

    cache_status = f"Cache date: {html.escape(str(cache_date))}" if cache_date else "Cache missing or unreadable."

    html_rows = "\n".join(
        f"<tr>"
        f"<td>{html.escape(r['display'])}</td>"
        f"<td style='text-align:left'><code>{html.escape(r['ticker'])}</code></td>"
        f"<td style='text-align:right'>{r['low']}</td>"
        f"<td style='text-align:right'><strong style='font-weight:700'>{r['close']}</strong> {r['close_arrow']}</td>"
        f"<td style='text-align:right'>{r['high']}</td>"
        f"</tr>"
        for r in rows
    )

    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body {{ font-family: Inter, Roboto, Arial, sans-serif; margin:18px; background:#f7fafc; color:#0f172a; }}
    .card {{ max-width:980px; margin:18px auto; background:white; padding:18px; border-radius:10px; box-shadow:0 6px 18px rgba(2,6,23,0.06); }}
    h1 {{ margin:0; font-size:18px; }}
    .sub {{ color:#475569; margin-top:6px; font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:12px; font-variant-numeric:tabular-nums; }}
    th, td {{ padding:10px 8px; font-size:14px; border-bottom:1px solid #eef2f7; }}
    th {{ text-transform:uppercase; font-size:11px; color:#64748b; text-align:right; }}
    th:first-child, td:first-child {{ text-align:left; }}
    code {{ background:#f1f5f9; padding:2px 6px; border-radius:6px; font-size:13px; }}
    .muted {{ color:#94a3b8; }}
    .up {{ color:#067d68; font-weight:700; margin-left:6px; }}   /* green */
    .down {{ color:#b91c1c; font-weight:700; margin-left:6px; }} /* red */
    .controls {{ margin-top:12px; display:flex; justify-content:space-between; align-items:center; gap:8px; }}
    .btn {{ background:#0ea5a4; color:white; padding:8px 12px; border-radius:8px; text-decoration:none; font-weight:700; }}
  </style>
</head>
<body>
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h1>{html.escape(title)}</h1>
        <div class="sub">{html.escape(generated_at)}</div>
        <div class="sub muted">{cache_status}</div>
      </div>
      <div style="text-align:right">
        <div class="sub">Local file dashboard</div>
      </div>
    </div>

    <table aria-label="52-week table">
      <thead>
        <tr>
          <th>Instrument</th>
          <th>Ticker</th>
          <th style="text-align:right">52Wk Low</th>
          <th style="text-align:right">Close</th>
          <th style="text-align:right">52Wk High</th>
        </tr>
      </thead>
      <tbody>
        {html_rows}
      </tbody>
    </table>

    <div class="controls">
      <div class="muted">Source: local cache file (<code>{html.escape(CACHE_FILE)}</code>)</div>
      <div>
        <a class="btn" href="#" onclick="location.reload();return false;">Refresh page</a>
      </div>
    </div>
  </div>
</body>
</html>
"""
    return page

def save_and_open(html_text):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_text)
    webbrowser.open("file:///" + OUT_HTML.replace("\\", "/"))

def main(argv):
    do_refresh = "--refresh" in argv or "-r" in argv
    if do_refresh:
        ok, msg = try_refresh_cache()
        print("Refresh attempt:", msg)
    cache = load_cache()
    html_text = build_html(cache)
    save_and_open(html_text)
    print("Dashboard written to:", OUT_HTML)
    if cache is None:
        print("Warning: cache missing or unreadable. Run `python update_52w_cache.py` to create it, or run this script with --refresh if update_52w_cache.py is next to this script.")

if __name__ == "__main__":
    main(sys.argv[1:])
