#!/usr/bin/env python3
# app.py
"""
Flask service to return gold price converted to INR per gram.

Endpoints:
  GET /price
    - Query params:
        - premium_pct (float, default 6.0)
        - making_per_gram (float, default 150.0)
        - gst_pct (float, default 3.0)
        - format (json | html) (default json)
    - returns pretty JSON (default) or a human-friendly HTML page (format=html)

  GET /health
    - simple health check

Notes:
  - Requires: pip install flask requests yfinance
  - Run: python app.py
"""
from flask import Flask, request, Response, jsonify
from datetime import datetime
import time
import threading
import requests
import yfinance as yf
import json
import html

app = Flask(__name__)

# Constants
OZ_TO_GRAMS = 31.1034768
EXCH_RATE_HOST_CONVERT = "https://api.exchangerate.host/convert"
FRANKFURTER_API = "https://api.frankfurter.app/latest"

# Cache structure
_cache = {"gold": {"value": None, "ts": None}, "fx": {"value": None, "ts": None}}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5 minutes

# ---------------------- Helpers ----------------------
def is_cache_valid(entry):
    return entry["value"] is not None and entry["ts"] is not None and (time.time() - entry["ts"]) < CACHE_TTL

def usd_oz_to_inr_per_gram(usd_per_oz, usd_to_inr):
    return (usd_per_oz / OZ_TO_GRAMS) * usd_to_inr

def retail_price(inr_per_gram, premium_pct=5.0, making_charge_per_gram=0.0, gst_pct=3.0):
    base_plus_premium = inr_per_gram * (1 + premium_pct/100) + making_charge_per_gram
    return base_plus_premium * (1 + gst_pct/100)

def retry(func, attempts=3, delay=1, *args, **kwargs):
    last_exc = None
    for i in range(attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last_exc

# ---------------------- Fetchers ----------------------
def fetch_gold_futures_usd_per_oz(ticker="GC=F"):
    t = yf.Ticker(ticker)
    try:
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1]), hist.index[-1].isoformat(), "yfinance(history)"
    except Exception:
        pass
    try:
        info = t.info
        price = info.get("regularMarketPrice") or info.get("previousClose")
        if price:
            return float(price), datetime.utcnow().isoformat(), "yfinance(info)"
    except Exception:
        pass
    raise RuntimeError("Could not fetch gold futures price")

def fetch_usd_to_inr_exchangerate_host_convert():
    r = requests.get(EXCH_RATE_HOST_CONVERT, params={"from": "USD", "to": "INR"}, timeout=8)
    r.raise_for_status()
    j = r.json()
    rate = j.get("info", {}).get("rate") or j.get("result")
    if not rate:
        raise RuntimeError("exchangerate.host returned no INR rate")
    return float(rate), j.get("date") or datetime.utcnow().date().isoformat(), "exchangerate.host"

def fetch_usd_to_inr_frankfurter():
    r = requests.get(FRANKFURTER_API, params={"from": "USD", "to": "INR"}, timeout=8)
    r.raise_for_status()
    j = r.json()
    rate = j.get("rates", {}).get("INR")
    if not rate:
        raise RuntimeError("frankfurter returned no INR rate")
    return float(rate), j.get("date"), "frankfurter"

def fetch_usd_to_inr_yfinance():
    t = yf.Ticker("INR=X")
    try:
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1]), hist.index[-1].isoformat(), "yfinance(INR=X)"
    except Exception:
        pass
    info = t.info
    price = info.get("regularMarketPrice") or info.get("previousClose")
    if not price:
        raise RuntimeError("yfinance fallback failed")
    return float(price), datetime.utcnow().isoformat(), "yfinance(info-INR=X)"

def fetch_usd_to_inr_with_fallback():
    try:
        return fetch_usd_to_inr_exchangerate_host_convert()
    except Exception:
        try:
            return fetch_usd_to_inr_frankfurter()
        except Exception:
            return fetch_usd_to_inr_yfinance()

# ---------------------- Cached wrappers ----------------------
def get_cached_gold():
    with _cache_lock:
        if is_cache_valid(_cache["gold"]):
            return _cache["gold"]["value"]
    val = retry(fetch_gold_futures_usd_per_oz, attempts=2, delay=0.5)
    with _cache_lock:
        _cache["gold"]["value"] = {"usd_per_oz": val[0], "ts": val[1], "source": val[2]}
        _cache["gold"]["ts"] = time.time()
    return _cache["gold"]["value"]

def get_cached_fx():
    with _cache_lock:
        if is_cache_valid(_cache["fx"]):
            return _cache["fx"]["value"]
    val = retry(fetch_usd_to_inr_with_fallback, attempts=2, delay=0.5)
    with _cache_lock:
        _cache["fx"]["value"] = {"usd_to_inr": val[0], "date": val[1], "source": val[2]}
        _cache["fx"]["ts"] = time.time()
    return _cache["fx"]["value"]

# ---------------------- HTML rendering ----------------------
def render_price_html(response_dict):
    # basic inline CSS for a tidy look
    css = """
    body { font-family: Arial, Helvetica, sans-serif; background:#f7fafc; color:#111; padding:20px; }
    .card { background:white; border-radius:8px; padding:18px; max-width:720px; margin:12px auto; box-shadow:0 6px 18px rgba(0,0,0,0.08); }
    h1 { font-size:20px; margin:0 0 8px 0; }
    table { width:100%; border-collapse:collapse; margin-top:12px; }
    th, td { text-align:left; padding:8px 6px; border-bottom:1px solid #eee; }
    th { color:#444; width:40%; }
    .muted { color:#666; font-size:13px; }
    .note { margin-top:12px; font-size:13px; color:#444; }
    """
    # escape texts where needed
    notes = html.escape(response_dict.get("notes", ""))
    gold_src = html.escape(response_dict.get("sources", {}).get("gold", ""))
    fx_src = html.escape(response_dict.get("sources", {}).get("fx", ""))
    served = html.escape(response_dict.get("timestamps", {}).get("served_at", ""))
    gold_ts = html.escape(response_dict.get("timestamps", {}).get("gold_source_ts", ""))
    fx_date = html.escape(response_dict.get("timestamps", {}).get("fx_source_date", ""))

    html_content = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Gold price → INR/gram</title>
      <style>{css}</style>
    </head>
    <body>
      <div class="card">
        <h1>Gold price — INR per gram</h1>
        <div class="muted">Reference: COMEX futures (GC=F). Served at: {served}</div>

        <table>
          <tr><th>Gold (USD / troy oz)</th><td>USD {response_dict['usd_per_oz']:,}</td></tr>
          <tr><th>USD per gram</th><td>USD {response_dict['usd_per_gram']:,}</td></tr>
          <tr><th>USD → INR</th><td>₹ {response_dict['usd_to_inr']:,}  <span class="muted">({fx_src} — {fx_date})</span></td></tr>
          <tr><th>INR per gram (converted)</th><td><strong>₹ {response_dict['inr_per_gram']:,}</strong></td></tr>
          <tr><th>Estimated retail / gram</th><td><strong>₹ {response_dict['retail_estimate_per_gram']:,}</strong></td></tr>
        </table>

        <h2 style="font-size:15px; margin-top:14px;">Calculation parameters</h2>
        <table>
          <tr><th>Premium (%)</th><td>{response_dict['calc_params']['premium_pct']}</td></tr>
          <tr><th>Making charge (₹ / gram)</th><td>{response_dict['calc_params']['making_per_gram']}</td></tr>
          <tr><th>GST (%)</th><td>{response_dict['calc_params']['gst_pct']}</td></tr>
        </table>

        <div class="note">
          <div><strong>Sources:</strong> Gold — {gold_src}; FX — {fx_src}</div>
          <div><strong>Source timestamps:</strong> Gold — {gold_ts}; FX — {fx_date}</div>
          <div style="margin-top:8px;">{notes}</div>
        </div>
      </div>
    </body>
    </html>
    """
    return html_content

# ---------------------- Flask endpoints ----------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()}), 200

@app.route("/price")
def price():
    # parse args
    try:
        premium_pct = float(request.args.get("premium_pct", 6.0))
    except Exception:
        return jsonify({"error": "invalid premium_pct"}), 400
    try:
        making_per_gram = float(request.args.get("making_per_gram", 150.0))
    except Exception:
        return jsonify({"error": "invalid making_per_gram"}), 400
    try:
        gst_pct = float(request.args.get("gst_pct", 3.0))
    except Exception:
        return jsonify({"error": "invalid gst_pct"}), 400

    fmt = (request.args.get("format") or "json").lower()

    # fetch cached data
    try:
        gold = get_cached_gold()
    except Exception as e:
        return jsonify({"error": "failed to fetch gold price", "details": str(e)}), 502
    try:
        fx = get_cached_fx()
    except Exception as e:
        return jsonify({"error": "failed to fetch USD->INR rate", "details": str(e)}), 502

    usd_per_oz = gold["usd_per_oz"]
    usd_to_inr = fx["usd_to_inr"]
    inr_per_gram = usd_oz_to_inr_per_gram(usd_per_oz, usd_to_inr)
    est_retail = retail_price(inr_per_gram, premium_pct, making_per_gram, gst_pct)

    response = {
        "usd_per_oz": round(usd_per_oz, 4),
        "usd_per_gram": round(usd_per_oz / OZ_TO_GRAMS, 6),
        "usd_to_inr": round(usd_to_inr, 6),
        "inr_per_gram": round(inr_per_gram, 2),
        "retail_estimate_per_gram": round(est_retail, 2),
        "calc_params": {"premium_pct": premium_pct, "making_per_gram": making_per_gram, "gst_pct": gst_pct},
        "timestamps": {
            "gold_source_ts": gold.get("ts"),
            "fx_source_date": fx.get("date"),
            "served_at": datetime.utcnow().isoformat()
        },
        "sources": {"gold": gold.get("source"), "fx": fx.get("source")},
        "notes": "Gold futures (COMEX GC=F). Retail estimate includes premium + making + GST. Retail may vary."
    }

    if fmt in ("html", "pretty"):
        html_page = render_price_html(response)
        return Response(html_page, mimetype="text/html")
    else:
        # pretty JSON response
        return Response(json.dumps(response, indent=2, sort_keys=False), mimetype="application/json")

if __name__ == "__main__":
    # open browser to the HTML view shortly after the server starts
    import webbrowser, threading, time

    def _open_browser():
        try:
            # use loopback address so it works locally
            webbrowser.open_new("http://127.0.0.1:5000/price?format=html")
        except Exception:
            pass

    # start a short timer so the server has time to bind before the browser opens
    threading.Timer(1.5, _open_browser).start()

    # start the Flask dev server (or waitress if you prefer)
    app.run(host="0.0.0.0", port=5000, debug=False)


