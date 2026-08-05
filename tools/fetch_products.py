#!/usr/bin/env python3
"""Re-fetch CarMall's NGK spark-plug products (price + stock) from Cyberbiz.

Same approach as the wiper finder: the storefront exposes /sitemap.xml and a public
/products/<handle>.json per product, with no key and no CORS header — so the data has
to be baked in at build time rather than fetched from the browser.

Every NGK plug listing is a single-variant product whose `sku` IS the NGK part number
(e.g. CR7HDX-S), which is what lets build_data.py join straight onto the NGK finder data.

Writes ngk_products.json.
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://www.carmall.com.tw"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
# Handles that must be fetched even if the sitemap lags behind (cf. HELLA on the wiper side).
EXTRA_HANDLES = []


def get(url, retries=4):
    """Cyberbiz occasionally times out; retry transient failures with incremental backoff
    so one blip doesn't fail the whole scheduled refresh."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
    raise last


def is_plug(handle):
    return bool(re.search(r"ngk|火星塞|spark", handle, re.I))


def main():
    sm = get(SITE + "/sitemap.xml")
    urls = sorted(set(re.findall(r"https://www\.carmall\.com\.tw/products/[^< ]+", sm)))
    handles = [h for h in (urllib.parse.unquote(u.rsplit("/products/", 1)[-1]) for u in urls)
               if is_plug(h)]
    for h in EXTRA_HANDLES:
        if h not in handles:
            handles.append(h)

    out, fail = [], []
    for h in handles:
        url = SITE + "/products/" + urllib.parse.quote(h, safe="-") + ".json"
        try:
            d = json.loads(get(url))
        except Exception as e:
            fail.append((h, str(e)))
            continue
        for v in d.get("variants", []):
            sku = (v.get("sku") or "").strip().upper()
            if not sku:
                continue
            out.append({
                "sku": sku,
                "title": d.get("title"),
                "handle": d.get("handle"),
                "url": SITE + (d.get("url") or ("/products/" + h)),
                "price": v.get("price"),
                "qty": v.get("inventory_quantity"),
                "available": bool(v.get("available")),
                "variant_id": v.get("id"),
                "vendor": d.get("vendor"),
                "product_type": d.get("product_type"),
            })

    out.sort(key=lambda x: x["sku"])
    print(f"NGK products: {len(out)} SKUs | failures: {len(fail)}")
    for f in fail:
        print("  FAIL", f[0], f[1])

    # Never overwrite good inventory with a partial fetch. A dropped SKU does not fail
    # loudly downstream — it silently turns every bike using that plug into "out of
    # stock" and removes its buy button until the next good run. Keep the previous file
    # and let the scheduled job go red instead.
    if fail:
        print(f"ERROR: {len(fail)} product(s) failed to fetch; keeping previous "
              f"ngk_products.json rather than publishing partial inventory",
              file=sys.stderr)
        sys.exit(1)
    if not out:
        print("ERROR: no products fetched", file=sys.stderr)
        sys.exit(1)

    json.dump(out, open(os.path.join(BASE, "ngk_products.json"), "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
