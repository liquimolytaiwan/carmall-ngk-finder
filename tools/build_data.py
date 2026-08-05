#!/usr/bin/env python3
"""Join the NGK finder crawl with CarMall's live NGK products into the front-end data.json.

Inputs   tools/ngk_raw_moto.json   (fetch_ngk.py --cartype 2)
         tools/ngk_products.json   (fetch_products.py)
Output   data.json                 (repo root, consumed by app.js)

The join is exact on part number: a CarMall variant's SKU is the NGK part number, so a
bike's MOTO DX column value maps straight onto a buyable product. No fuzzy matching, and
deliberately no substitute-plug guessing — a plug that doesn't match is reported as
"no MotoDX for this bike" rather than silently swapped for a near neighbour.
"""
import argparse, datetime, json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DXCOL = "MOTO DX釕合金火星塞"
COLS = {"engine": "引擎", "oem": "原廠火星塞", "dx": DXCOL,
        "gp": "G-POWER白金火星塞", "ix": "IX銥合金火星塞", "count": "支數"}
BLANK = {"", "-", "-----", "─────", "—"}


def norm(s):
    """Collapse whitespace; treat NGK's placeholder dashes as empty."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return "" if s in BLANK else s


def parse_count(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def build_entry(raw, products):
    engines, seen_rows = [], set()
    for r in raw["rows"]:
        row = ({k: norm(r.get(col)) for k, col in COLS.items() if k != "count"}
               | {"count": parse_count(r.get(COLS["count"]))})
        # NGK repeats an identical row for some bikes (e.g. BMW S1000RR lists the same
        # engine twice), which would render as a duplicated spec line. Collapse only
        # byte-identical rows so a genuine second engine variant is still shown.
        sig = tuple(sorted(row.items(), key=lambda kv: kv[0]))
        if sig in seen_rows:
            continue
        seen_rows.add(sig)
        engines.append(row)
    # Distinct MotoDX part numbers this fitment calls for (usually exactly one),
    # each remembering how many plugs that engine needs.
    dx_order, seen, need_of = [], set(), {}
    for e in engines:
        for p in re.split(r"[,/、]", e["dx"]):
            p = p.strip().upper()
            if not p:
                continue
            if p not in seen:
                seen.add(p)
                dx_order.append(p)
            # Match on the exact part number, not a substring — "CR7E" would otherwise
            # steal the count from a row calling for "CR7EDX-S".
            if e["count"] and p not in need_of:
                need_of[p] = e["count"]

    buys = []
    for p in dx_order:
        prod = products.get(p)
        need = need_of.get(p)
        item = {"sku": p, "need": need}
        if prod:
            item["stock"] = prod["qty"]
            # Cyberbiz still reports available=true with 2 units left, but a four-cylinder
            # bike needs 4 — offering "共 4 支 $3,200" the customer cannot actually order
            # is a promise the store can't keep. Withhold the buy link and let the front
            # end say how many are actually left.
            enough = prod["qty"] is None or prod["qty"] >= (need or 1)
            if enough:
                item.update({
                    "title": prod["title"], "url": prod["url"], "price": prod["price"],
                    "available": True,
                    "total": round(prod["price"] * need) if (prod["price"] and need) else None,
                })
        buys.append(item)

    return {
        "year": norm(raw["year"]),
        "engines": engines,
        "recommend": norm(raw.get("recommend")),
        "buys": buys,
        # No MotoDX exists for this bike at all — the front end shows spec + contact-us.
        "no_dx": not dx_order,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.join(BASE, "ngk_raw_moto.json"))
    ap.add_argument("--products", default=os.path.join(BASE, "ngk_products.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data.json"))
    a = ap.parse_args()

    raw = json.load(open(a.raw))
    products = {p["sku"].upper(): p for p in json.load(open(a.products))
                if p.get("available") and p.get("price")}

    brands = []
    stats = {"fitments": 0, "buyable": 0, "no_dx": 0, "dx_out_of_stock": 0}
    for b in raw["cartypes"]["2"]:
        models = {}
        for e in b["entries"]:
            key = (norm(e["model"]), norm(e["displacement"]))
            models.setdefault(key, []).append(build_entry(e, products))
        mlist, dedup = [], {}
        for (name, cc), entries in models.items():
            # Drop the year step entirely when NGK has no real year split for this bike.
            if len(entries) == 1:
                entries[0]["year"] = entries[0]["year"] or ""
            # NGK's own list carries casing duplicates (e.g. "MANY 110 (六期)" and
            # "Many 110 (六期)"). Collapse them only when the fitment data is identical,
            # so a real trim difference is never hidden.
            key = (name.lower(), cc, json.dumps(entries, sort_keys=True, ensure_ascii=False))
            if key in dedup:
                continue
            dedup[key] = True
            mlist.append({"name": name, "cc": cc, "entries": entries})
            for en in entries:
                stats["fitments"] += 1
                if en["no_dx"]:
                    stats["no_dx"] += 1
                elif any("url" in x for x in en["buys"]):
                    stats["buyable"] += 1
                else:
                    stats["dx_out_of_stock"] += 1
        mlist.sort(key=lambda m: (m["name"].lower(), m["cc"]))
        if mlist:
            brands.append({"en": b["name_en"], "tw": b["name_tw"], "models": mlist})
    brands.sort(key=lambda x: x["en"].lower())

    data = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": raw.get("source"),
        "brands": brands,
    }
    json.dump(data, open(a.out, "w"), ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(a.out)
    print(f"wrote {a.out}  ({size/1024:.0f} KB)")
    print(f"  brands   {len(brands)}")
    print(f"  models   {sum(len(b['models']) for b in brands)}")
    print(f"  fitments {stats['fitments']}")
    print(f"    可直接購買          {stats['buyable']}")
    print(f"    有 MotoDX 但庫存不足 {stats['dx_out_of_stock']}")
    print(f"    NGK 無 MotoDX 規格   {stats['no_dx']}")
    if not stats["buyable"]:
        print("ERROR: nothing is buyable — product join failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
