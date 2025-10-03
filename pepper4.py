#!/usr/bin/env python3
"""
kannur_prices_html.py

Fetch Kannur market prices for multiple commodities and output a fancy HTML dashboard,
then automatically open it in your default browser.

Usage:
  python kannur_prices_html.py --commodities black-pepper,rubber,arecanut --auto-variants --output prices.html
"""

import argparse, time, random, re, webbrowser
import cloudscraper
from bs4 import BeautifulSoup

COMMODITYONLINE = "https://www.commodityonline.com/mandiprices/{slug}/kerala"
KISANDEALS      = "https://www.kisandeals.com/mandiprices/{slug}/KERALA/ALL"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://www.google.com/"
}

VARIANTS = {
    "black-pepper": ["black-pepper", "pepper"],
    "rubber": ["rubber", "rubber-sheet"],
    "arecanut": ["arecanut", "arecanut-dry"]
}

# -------- helpers --------
def fetch_html(url):
    scraper = cloudscraper.create_scraper()
    try:
        r = scraper.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        return {"error": str(e)}

def find_kannur_row(html):
    if not html or isinstance(html, dict): return None
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["td","th"])]
        if any("kannur" in c.lower() for c in cols):
            return cols
    for line in soup.get_text().splitlines():
        if "kannur" in line.lower():
            return [line.strip()]
    return None

def first_num(s):
    if not s: return None
    m = re.search(r"([0-9]{2,})", s.replace(",",""))
    return int(m.group(1)) if m else None

def unit_hint(s):
    if not s: return None
    low = s.lower()
    if "quintal" in low: return "quintal"
    if "kg" in low: return "kg"
    return None

def normalize(n, hint=None):
    if n is None: return (None,None)
    if hint=="quintal": return (n, round(n/100,2))
    if hint=="kg": return (n*100, float(n))
    return (n, round(n/100,2)) if n>=5000 else (n*100, float(n))

def parse_price(row):
    for cell in row:
        num = first_num(cell)
        if num:
            return normalize(num, unit_hint(cell)), cell
    return ((None,None), None)

def get_price(slug, auto_variants=False):
    candidates = [slug]
    if auto_variants and slug in VARIANTS:
        candidates += VARIANTS[slug]

    for site, template in [("commodityonline", COMMODITYONLINE),
                           ("kisandeals", KISANDEALS)]:
        for s in candidates:
            url = template.format(slug=s)
            html = fetch_html(url)
            row = find_kannur_row(html)
            if row:
                (pq, pk), raw = parse_price(row)
                if pq:
                    return {"slug": slug, "site": site, "pq": pq, "pk": pk, "raw": raw}
    return {"slug": slug, "error": "Kannur not found"}

# -------- main --------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commodities","-c",required=True,
                    help="Comma-separated commodity slugs (e.g. black-pepper,rubber,arecanut)")
    ap.add_argument("--auto-variants",action="store_true",help="Try common slug variants")
    ap.add_argument("--output","-o",default="kannur_prices.html",help="HTML output file")
    args = ap.parse_args()

    slugs = [s.strip() for s in args.commodities.split(",") if s.strip()]

    results = []
    for slug in slugs:
        res = get_price(slug, auto_variants=args.auto_variants)
        results.append(res)
        time.sleep(0.5)

    # --- fancy HTML ---
    html = """
<html>
<head>
<meta charset="utf-8">
<title>Kannur Market Prices</title>
<style>
body {font-family: 'Segoe UI', Tahoma, sans-serif; background: #f5f6fa; padding: 20px;}
h2 {text-align: center; margin-bottom: 30px;}
.grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px;}
.card {background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); transition: transform 0.2s;}
.card:hover {transform: translateY(-4px);}
.commodity {font-size: 1.2em; font-weight: bold; margin-bottom: 10px;}
.price {font-size: 1.5em; color: #2c3e50;}
.perkg {font-size: 1.1em; color: #27ae60; margin-top: 5px;}
.source {font-size: 0.85em; color: #888; margin-top: 10px;}
.error {color: red; font-weight: bold;}
</style>
</head>
<body>
<h2>Kannur Market Prices</h2>
<div class="grid">
"""
    for r in results:
        display_name = r['slug'].replace("-", " ").title()
        if r.get("error"):
            html += f"""
<div class="card">
  <div class="commodity">{display_name}</div>
  <div class="error">ERROR: {r['error']}</div>
</div>
"""
        else:
            html += f"""
<div class="card">
  <div class="commodity">{display_name}</div>
  <div class="price">₹{r['pq']:,} / Quintal</div>
  <div class="perkg">≈ ₹{r['pk']:.2f} / Kg</div>
  <div class="source">Source: {r['site']}<br><small>{r['raw']}</small></div>
</div>
"""
    html += """
</div>
</body>
</html>
"""

    with open(args.output,"w",encoding="utf-8") as f:
        f.write(html)

    print(f"Fancy HTML written to {args.output}")
    # Open automatically
    webbrowser.open_new_tab(args.output)

if __name__=="__main__":
    main()
