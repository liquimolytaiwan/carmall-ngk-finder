#!/usr/bin/env python3
"""Crawl the NGK Taiwan spark-plug finder (ngksparkplugs.com.tw) into structured JSON.

The public finder is backed by four unauthenticated POST endpoints:
    /api/carbrand   {cartype}                                  -> [{id,cartype,name_en,name_tw,parts_count}]
    /api/carmodel   {carbrand}                                 -> ["MODEL / DISPLACEMENT", ...]
    /api/caryear    {modelname,displacement}                   -> ["2004 - 2008", ...]
    /api/finder     {carbrand,modelname,displacement,caryear}  -> HTML fragment (one row per engine)

cartype 1 = 汽車, 2 = 機車. The server rate-limits to 60 req/min, so every call is paced.

Result columns differ per cartype (cars get Premium RX + IX MAX, bikes get MOTO DX), so the
HTML table is parsed off each cell's `data-th` attribute rather than by column position.

Usage:  fetch_ngk.py [--cartype 1|2] [--out ngk_raw.json]
"""
import argparse, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://ngksparkplugs.com.tw"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
PACE = 1.15          # seconds between requests (server allows 60/min)
_last = [0.0]


def post(path, data, retries=4):
    """POST form-encoded, paced under the rate limit, with backoff on transient errors."""
    body = urllib.parse.urlencode(data, encoding="utf-8").encode()
    last = None
    for attempt in range(retries):
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(SITE + path, data=body, headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SITE + "/product/plugs/finder",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            # 429 = we out-ran the limiter; back off hard and retry.
            time.sleep(20 if e.code == 429 else 3 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def post_json(path, data):
    return json.loads(post(path, data))


TAG = re.compile(r"<[^>]+>")
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r'<td[^>]*data-th="([^"]*)"[^>]*>(.*?)</td>', re.S)
RECOMMEND = re.compile(r'recommend-highlight"><div>[^<]*</div><div>(.*?)</div>', re.S)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s))).strip()


def parse_finder(fragment):
    """-> {recommend: str|None, rows: [{column-name: value}]}"""
    m = RECOMMEND.search(fragment)
    rows = []
    for raw in ROW.findall(fragment):
        cells = CELL.findall(raw)
        if not cells:
            continue                      # <thead> row
        row = {clean(k): clean(v) for k, v in cells}
        if any(row.values()):
            rows.append(row)
    return {"recommend": clean(m.group(1)) if m else None, "rows": rows}


def crawl(cartypes):
    """Returns (data, failures). A non-empty failures list means the crawl is incomplete
    and its output must not be published — see main()."""
    out = {"source": SITE + "/product/plugs/finder", "cartypes": {}}
    failures = []
    for ct in cartypes:
        brands = post_json("/api/carbrand", {"cartype": ct})
        print(f"cartype {ct}: {len(brands)} brands", flush=True)
        bucket = []
        for bi, br in enumerate(brands, 1):
            models = post_json("/api/carmodel", {"carbrand": br["id"]})
            entries = []
            for mstr in models:
                # value is "MODEL / DISPLACEMENT"; the model name itself may contain " / ".
                modelname, _, displacement = mstr.rpartition(" / ")
                if not modelname:
                    modelname, displacement = mstr, ""
                try:
                    years = post_json("/api/caryear", {"modelname": modelname,
                                                       "displacement": displacement})
                except Exception as e:
                    failures.append(f"caryear {br['name_en']} {mstr}: {e}")
                    print(f"    ! caryear fail {br['name_en']} {mstr}: {e}", flush=True)
                    continue
                for y in years:
                    try:
                        frag = post("/api/finder", {"carbrand": br["id"], "modelname": modelname,
                                                    "displacement": displacement, "caryear": y})
                    except Exception as e:
                        failures.append(f"finder {br['name_en']} {mstr} {y}: {e}")
                        print(f"    ! finder fail {br['name_en']} {mstr} {y}: {e}", flush=True)
                        continue
                    entries.append({"model": modelname, "displacement": displacement,
                                    "year": y, **parse_finder(frag)})
            bucket.append({**br, "entries": entries})
            print(f"  [{bi}/{len(brands)}] {br['name_en']}: "
                  f"{len(models)} models -> {len(entries)} fitments", flush=True)
        out["cartypes"][str(ct)] = bucket
    return out, failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cartype", type=int, choices=[1, 2], action="append",
                    help="repeatable; default = both")
    ap.add_argument("--out", default=os.path.join(BASE, "ngk_raw.json"))
    a = ap.parse_args()
    data, failures = crawl(a.cartype or [1, 2])
    n = sum(len(b["entries"]) for bs in data["cartypes"].values() for b in bs)

    # A dropped model or fitment does not surface as an error downstream — the bike
    # simply disappears from the dropdown. Refuse to publish an incomplete crawl and
    # keep the last good file instead; the scheduled run goes red and can be re-run.
    if failures:
        print(f"ERROR: crawl incomplete ({len(failures)} request(s) failed after "
              f"retries); keeping previous {a.out}", file=sys.stderr)
        for f in failures[:20]:
            print("  " + f, file=sys.stderr)
        sys.exit(1)
    if not n:
        print("ERROR: no fitments fetched", file=sys.stderr)
        sys.exit(1)

    json.dump(data, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out}: {n} fitments")


if __name__ == "__main__":
    main()
