#!/usr/bin/env python3
"""Join NGK's fitment data with CarMall's live NGK products into the front-end data.json.

Inputs   tools/ngk_catalog_moto.json  (parse_catalog.py — printed catalogue, authoritative)
         tools/ngk_raw_moto.json      (fetch_ngk.py --cartype 2 — NGK Taiwan's finder API)
         tools/ngk_products.json      (fetch_products.py)
Output   data.json                    (repo root, consumed by app.js)

Two fitment sources, and which one wins matters
-----------------------------------------------
NGK Taiwan's API answers most motorcycles with a single part number and no model year,
so a bike whose plug changed mid-life is half wrong for every owner — the MT-03 case
that prompted this rebuild. The printed catalogue carries those year breaks, so it is
the source of truth wherever it lists the bike.

It is, however, NGK's *Japanese domestic* catalogue: Taiwan-market scooters (Many,
JET SR, DRG, 金發財, 勁豪, and every 六期/七期 trim) simply are not in it. Those come
from the Taiwan API, which is the only source that has them. So: catalogue first, Taiwan
API only for models the catalogue has never heard of, and each model says which it came
from rather than pretending the two are one dataset.

The plug join is exact on part number — a CarMall variant's SKU is the NGK part number.
Deliberately no substitute-plug guessing: a bike with no MotoDX is reported as such
rather than pointed at a near-neighbour heat range.
"""
import argparse, datetime, json, os, re, sys
from collections import OrderedDict, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_names import display_name

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

DXCOL = "MOTO DX釕合金火星塞"
COLS = {"engine": "引擎", "oem": "原廠火星塞", "dx": DXCOL,
        "gp": "G-POWER白金火星塞", "ix": "IX銥合金火星塞", "count": "支數"}
BLANK = {"", "-", "-----", "─────", "—"}

# Traditional-Chinese brand names. The Taiwan API supplies its own for the brands it
# covers; the catalogue only prints Japanese and English, so the ones it adds are named
# here. A brand missing from both just shows its English name.
BRAND_TW = {
    "HONDA": "本田", "YAMAHA": "山葉", "SUZUKI": "鈴木", "KAWASAKI": "川崎",
    "KYMCO": "光陽", "SYM": "三陽", "PGO": "摩特動力", "Hartford": "哈特佛",
    "TRIUMPH": "凱旋", "APRILIA": "阿普利亞", "PIAGGIO": "比雅久", "VESPA": "偉士牌",
    "HYOSUNG": "曉星", "BENELLI": "貝納利", "DUCATI": "杜卡迪", "BMW": "寶馬",
    "HARLEY-DAVIDSON": "哈雷", "MOTO GUZZI": "moto guzzi", "HUSQVARNA": "husqvarna",
}

# Taiwan trim markers that never change the plug. Stripped only when testing whether a
# better source already covers a model, never from anything shown to a customer.
TRIM_TOKENS = ("ABS", "UBS", "CBS", "TCS", "LED", "EFI", "BREMBO",
               "碟煞", "鼓煞", "雙碟煞", "特仕版", "仕樣", "版")

# Generation markers that DO change the plug and must survive into the match key.
# KYMCO's MANY 110 六期 takes CR7EDX-S and the 七期 takes CPR7EDX-9S; Yamaha's 勁戰
# 1~5代 takes CR7EDX-S and the 水冷 6th generation takes CPR8EDX-9S. Treating those as
# one bike would drop half of them and answer the survivors' owners with the other
# generation's plug — the exact failure this rebuild exists to fix.
RE_GENERATION = re.compile(r"[三四五六七八]期|水冷|空冷|\d\s*[~～]\s*\d\s*代|\d+代")

SRC_TW = {"catalog": "原廠型錄", "tw_table": "台灣對照表", "tw": "台灣官網"}


# Same bike, named too differently for match_key to see it. Each entry says which
# catalogue model the Taiwan model is, so the catalogue's year-split answer wins instead
# of the bike appearing twice with two different recommendations. Kept explicit rather
# than loosening match_key: fuzzier matching merged 勁風光 with Cygnus-GRYPHUS and JOG 125
# with JOG 50, which is a worse failure than a duplicate row.
TW_SAME_AS_CATALOG = {
    ("SUZUKI", "GSX1300R隼"): "GSX1300R Hayabusa 隼",
    ("SUZUKI", "Swish 125"): "Swish / Limited",
    ("SYM", "野狼T2 ABS"): "T2 250",
    ("PGO", "X-HOT"): "X-HOT 150",
    ("SYM", "野狼T2 250"): "T2 250",
    ("YAMAHA", "R3"): "YZF-R3",
    ("YAMAHA", "勁戰(1~5代)"): "Cygnus X 勁戰 (XC125)",
    # NGK Taiwan calls it "R3 ABS" and answers with only the post-2018 plug. Left
    # unmapped it ships alongside the catalogue's year-split YZF-R3, and a 2015-2017
    # owner who picks the Taiwan-named one is sent LMAR8ADX-9S instead of CR8EDX-S —
    # the precise failure this rebuild exists to remove.
    ("YAMAHA", "R3 ABS"): "YZF-R3",
    ("YAMAHA", "N-MAX"): "NMAX 155",
    ("YAMAHA", "Tracer 900 GT"): "TRACER900 ABS/GT ABS",
}

# Typos in the supplied spreadsheets. Corrected here rather than in the file so the
# sheet CarMall sent stays byte-identical to what they can re-send.
TW_TABLE_FIXES = {("YAMAHA", "YZK-R7"): "YZF-R7"}


def norm(s):
    """Collapse whitespace; treat NGK's placeholder dashes as empty."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return "" if s in BLANK else s


def parse_count(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def match_key(name):
    """Identity of a bike for cross-source matching — not for display.

    "Cygnus X 勁戰 (XC125)" and "Cygnus-X" have to collide, or the customer is offered
    the same bike twice with two different answers. Parentheticals, Chinese aliases,
    punctuation and Taiwan trim suffixes are all dropped; the model number is not.
    """
    gens = sorted({re.sub(r"\s+", "", g) for g in RE_GENERATION.findall(name)})
    s = re.sub(r"\([^()]*\)", " ", name)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    latin = re.sub(r"[　-鿿＀-￯]", " ", s)   # drop kana, CJK, fullwidth
    # Only trust the Latin-only form when there is a Latin name in there. "新名流 125"
    # and "キャプチャー125" both reduce to "125" otherwise, and two unrelated bikes
    # would silently merge — the Taiwan model vanishing behind a Japanese one.
    s = latin if re.search(r"[A-Za-z]", latin) else s
    toks = [t for t in s.upper().split() if t]
    while toks and toks[-1] in TRIM_TOKENS:
        toks.pop()
    return "".join(toks) + "".join(gens)


def year_label(y_from, y_to, raw):
    """'2015-10','2018-03' → '2015/10 – 2018/03'."""
    fmt = lambda v: v.replace("-", "/") if v else ""
    if y_from and y_to and y_from == y_to:
        return fmt(y_from)
    if y_from and y_to:
        return f"{fmt(y_from)} – {fmt(y_to)}"
    if y_from:
        return f"{fmt(y_from)} 起"
    if y_to:
        return f"{fmt(y_to)} 以前"
    return norm(raw)


def parse_tw_year(s):
    """NGK Taiwan's year field → ('2009', '2021'). Returns (None, None) if it has none.

    The API leaves this blank for most motorcycles, but where it is filled in it is a
    real range — "2009-2021", "2018-", "2015.04~" — and dropping it would make the front
    end tell customers the source named no year while the header shows one.
    """
    s = norm(s).replace("～", "~")
    if not s:
        return None, None
    part = r"(\d{4})(?:\.(\d{1,2}))?"
    fmt = lambda y, m: f"{y}-{int(m):02d}" if m else y
    m = re.fullmatch(rf"{part}\s*[-~]\s*{part}", s)
    if m:
        return fmt(m.group(1), m.group(2)), fmt(m.group(3), m.group(4))
    m = re.fullmatch(rf"{part}\s*[-~]", s)
    if m:
        return fmt(m.group(1), m.group(2)), None
    m = re.fullmatch(rf"[-~]\s*{part}", s)
    if m:
        return None, fmt(m.group(1), m.group(2))
    m = re.fullmatch(part, s)
    if m:
        v = fmt(m.group(1), m.group(2))
        return v, v
    return None, None


def sort_year(e):
    """Oldest first, so the picker reads as a timeline; undated rows last."""
    return (0 if e["year_from"] else 1, e["year_from"] or "", e["year_to"] or "")


def month_index(v, end=False):
    """'2018-03' → 24219. A bare year widens to Jan..Dec so ranges stay comparable."""
    if not v:
        return None
    parts = v.split("-")
    y = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else (12 if end else 1)
    return y * 12 + m


def close_open_ranges(entries, label, log):
    """Bound an open-ended row that a later row starts inside.

    The catalogue prints Honda's ジョルノ as two rows, `'11.1～` → CR7HDX-S and
    `'15.10～` → CPR8EDX-9S, with no end date on the first. Taken literally a 2016 owner
    matches both and is offered two different plugs with nothing to choose between them.
    Every other dated row in the table is a closed range, and one bike cannot take two
    plugs in the same year, so the earlier row ends where the later one begins.

    Only applied between rows describing the same variant: a note like 平行輸入 marks a
    version sold alongside the other, not after it, and those really can overlap.
    """
    for prev, cur in zip(entries, entries[1:]):
        if (prev["year_from"] and not prev["year_to"] and cur["year_from"]
                and prev["notes"] == cur["notes"]):
            prev["year_to"] = cur["year_from"]
            prev["year"] = year_label(prev["year_from"], prev["year_to"], "")
            log.append(f"{label}: {prev['year']}（原為開放式，以下一段起始年份收邊）")
    return entries


def merge_runs(entries):
    """Fold consecutive year rows that recommend exactly the same plugs into one.

    The catalogue splits a bike's timeline whenever *any* column changes, so a bike can
    carry two rows that differ only in the iridium part while the MotoDX answer is
    identical. Asking someone to pick between two years that lead to the same plug adds
    a step with no right answer, and makes the years that do matter look like noise.
    Rows are only folded when they are contiguous — a genuine gap stays a gap.
    """
    out = []
    for e in entries:
        prev = out[-1] if out else None
        same = prev and (
            [x["dx"] for x in prev["engines"]] == [x["dx"] for x in e["engines"]]
            and [x["oem"] for x in prev["engines"]] == [x["oem"] for x in e["engines"]]
            and [x["ix"] for x in prev["engines"]] == [x["ix"] for x in e["engines"]]
            and [x["count"] for x in prev["engines"]] == [x["count"] for x in e["engines"]]
            and prev["notes"] == e["notes"])
        pt, cf = month_index(prev["year_to"], end=True) if prev else None, month_index(e["year_from"])
        contiguous = pt is not None and cf is not None and cf - pt <= 1
        if same and contiguous:
            prev["year_to"] = e["year_to"]
            prev["year"] = year_label(prev["year_from"], prev["year_to"], "")
            continue
        out.append(e)
    return out


def attach_buys(entry, dx_parts, need_of, products):
    """Turn the MotoDX part numbers a fitment calls for into buyable cards."""
    buys = []
    for p in dx_parts:
        prod = products.get(p)
        need = need_of.get(p)
        item = {"sku": p, "need": need}
        if prod:
            item["stock"] = prod["qty"]
            # Cyberbiz still reports available=true with 2 units left, but a four-cylinder
            # bike needs 4 — offering "共 4 支 $3,200" the customer cannot actually order
            # is a promise the store can't keep. Withhold the buy link and let the front
            # end say how many are actually left.
            if prod["qty"] is None or prod["qty"] >= (need or 1):
                item.update({
                    "title": prod["title"], "url": prod["url"], "price": prod["price"],
                    "available": True,
                    "total": round(prod["price"] * need) if (prod["price"] and need) else None,
                })
        buys.append(item)
    entry["buys"] = buys
    entry["no_dx"] = not dx_parts
    return entry


# ---------------------------------------------------------------- catalogue source ----

def catalog_models(rows, products, closed):
    """Group catalogue rows into brand → model → year entries.

    Only rows with a MotoDX part are kept: the finder exists to sell MotoDX, and a bike
    NGK never made one for has nothing to offer here.
    """
    groups = OrderedDict()
    for r in rows:
        if not r["dx"]:
            continue
        name = display_name(r["name_ja"])
        # Spec qualifiers (逆輸入 / 教習車 / ATV) sit on the year row, not the model:
        # a bike's timeline can cross them, as PCX does when production moved from
        # Thailand, and splitting the model there would break the year sequence.
        # Case-folded, because the catalogue prints Triumph's T120 both as the Latin
        # "BONNEVILLE T120" and as "ボンネビルT120", which model_names maps to
        # "Bonneville T120". Grouping case-sensitively puts two identical 1200cc
        # Bonneville T120 rows in the picker with nothing to tell them apart.
        key = (r["brand"], name.casefold(), r["cc"])
        groups.setdefault(key, {"name": name, "name_ja": r["name_ja"],
                                "cc": r["cc"], "src": "catalog", "entries": []})
        entry = {
            "year": year_label(r["year_from"], r["year_to"], r["year_raw"]),
            "year_from": r["year_from"], "year_to": r["year_to"],
            "notes": r["notes"],
            "engines": [{"engine": "", "oem": r["std"], "dx": r["dx"],
                         "gp": "", "ix": r["ix"], "count": r["count"]}],
            "recommend": r["dx"],
        }
        groups[key]["entries"].append(
            attach_buys(entry, [r["dx"]], {r["dx"]: r["count"]}, products))

    by_brand = defaultdict(list)
    for (brand, _, cc), m in groups.items():
        m["entries"].sort(key=sort_year)
        m["entries"] = merge_runs(
            close_open_ranges(m["entries"], f'{brand} {m["name"]} {cc}cc', closed))
        by_brand[brand].append(m)
    return by_brand


# -------------------------------------------------------------- Taiwan API source ----

def tw_entry(raw, products):
    engines, seen = [], set()
    for r in raw["rows"]:
        row = ({k: norm(r.get(col)) for k, col in COLS.items() if k != "count"}
               | {"count": parse_count(r.get(COLS["count"]))})
        # NGK repeats an identical row for some bikes (e.g. BMW S1000RR lists the same
        # engine twice), which would render as a duplicated spec line. Collapse only
        # byte-identical rows so a genuine second engine variant is still shown.
        sig = tuple(sorted(row.items(), key=lambda kv: kv[0]))
        if sig in seen:
            continue
        seen.add(sig)
        engines.append(row)

    dx_order, seen_p, need_of = [], set(), {}
    for e in engines:
        for p in re.split(r"[,/、]", e["dx"]):
            p = p.strip().upper()
            if not p:
                continue
            if p not in seen_p:
                seen_p.add(p)
                dx_order.append(p)
            # Match on the exact part number, not a substring — "CR7E" would otherwise
            # steal the count from a row calling for "CR7EDX-S".
            if e["count"] and p not in need_of:
                need_of[p] = e["count"]

    y_from, y_to = parse_tw_year(raw["year"])
    entry = {"year": year_label(y_from, y_to, raw["year"]),
             "year_from": y_from, "year_to": y_to, "notes": [],
             "engines": engines, "recommend": norm(raw.get("recommend"))}
    return attach_buys(entry, dx_order, need_of, products)


# ------------------------------------------------------- Taiwan spreadsheet source ----

def api_plug_counts(raw):
    """How many plugs each bike takes, keyed by brand + match_key, from NGK Taiwan.

    The supplied spreadsheets list a part number per model but never a quantity, and a
    quantity is not something to infer from a model name — getting it wrong quotes the
    wrong total and lets someone order half a set. So it is looked up, and left unknown
    when no source states it.
    """
    counts = {}
    for b in raw["cartypes"]["2"]:
        for e in b["entries"]:
            for r in e["rows"]:
                n = parse_count(r.get(COLS["count"]))
                if n:
                    counts.setdefault((b["name_en"], match_key(norm(e["model"]))), set()).add(n)
    # Only trust it where every listing for that bike agrees.
    return {k: v.pop() for k, v in counts.items() if len(v) == 1}


def model_dx(m):
    return {x["dx"] for e in m["entries"] for x in e["engines"] if x["dx"]}


def superseded_by(model, candidates):
    """The already-listed model that answers this bike, if one does.

    Displacement is the hard gate. A name match alone is not enough: "MT-03" matches both
    the 320 and the 660 parallel import, "NMAX" matches the 125 and Taiwan's 155, and
    those take different plugs. Same name at a different size is a different bike, so it
    stays listed separately.

    Among size-compatible candidates the best is the one that agrees on the part, then
    one that splits the bike by year — that split is the better answer by construction.
    Failing both, a lone candidate still wins on source priority, and the disagreement is
    returned so the build can report it rather than bury it.
    """
    want = model_dx(model)
    fits = [c for c in candidates
            if not (model["cc"] and c["cc"]
                    and abs(c["cc"] - model["cc"]) > max(10, model["cc"] * 0.1))]
    for c in fits:
        if want & model_dx(c):
            return c, True
    for c in fits:
        if len(model_dx(c)) > 1:
            return c, True
    return (fits[0], False) if len(fits) == 1 else (None, True)


def guess_cc(name):
    """Displacement printed in the model name, when it unambiguously is one.

    "RACING S 150" → 150, "Krider400(雙缸)" → 400, but "MT-09" and "R3" are model
    numbers, not displacements, so they stay unknown rather than become 9cc and 3cc.
    """
    nums = [int(n) for n in re.findall(r"\d+", name)]
    big = [n for n in nums if 50 <= n <= 1300]
    return max(big) if big else None


def tw_table_models(rows, counts, products):
    by_brand = defaultdict(list)
    for r in rows:
        brand = r["brand"]
        name = TW_TABLE_FIXES.get((brand, r["model"]), r["model"])
        need = counts.get((brand, match_key(name)))
        entry = {"year": "", "year_from": None, "year_to": None, "notes": [],
                 "engines": [{"engine": "", "oem": r["oem"], "dx": r["dx"],
                              "gp": "", "ix": "", "count": need}],
                 "recommend": r["dx"]}
        by_brand[brand].append({
            "name": name, "name_ja": "", "cc": guess_cc(name), "src": "tw_table",
            "entries": [attach_buys(entry, [r["dx"]], {r["dx"]: need}, products)]})
    return by_brand


def tw_models(raw, products, closed):
    by_brand, tw_names = defaultdict(list), {}
    for b in raw["cartypes"]["2"]:
        tw_names[b["name_en"]] = b["name_tw"]
        models = OrderedDict()
        for e in b["entries"]:
            models.setdefault((norm(e["model"]), norm(e["displacement"])), []).append(
                tw_entry(e, products))
        dedup = set()
        for (name, cc), entries in models.items():
            # NGK's own list carries casing duplicates (e.g. "MANY 110 (六期)" and
            # "Many 110 (六期)"). Collapse them only when the fitment data is identical,
            # so a real trim difference is never hidden.
            sig = (name.lower(), cc, json.dumps(entries, sort_keys=True, ensure_ascii=False))
            if sig in dedup:
                continue
            dedup.add(sig)
            entries.sort(key=sort_year)
            by_brand[b["name_en"]].append({
                "name": name, "name_ja": "", "cc": int(cc) if cc.isdigit() else None,
                "src": "tw", "entries": merge_runs(close_open_ranges(
                    entries, f'{b["name_en"]} {name} {cc}cc', closed))})
    return by_brand, tw_names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.path.join(BASE, "ngk_catalog_moto.json"))
    ap.add_argument("--raw", default=os.path.join(BASE, "ngk_raw_moto.json"))
    ap.add_argument("--tw-tables", default=os.path.join(BASE, "ngk_tw_tables.json"))
    ap.add_argument("--products", default=os.path.join(BASE, "ngk_products.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data.json"))
    a = ap.parse_args()

    catalog = json.load(open(a.catalog))
    raw = json.load(open(a.raw))
    tw_tables = json.load(open(a.tw_tables))
    products = {p["sku"].upper(): p for p in json.load(open(a.products))
                if p.get("available") and p.get("price")}

    closed = []
    cat_by_brand = catalog_models(catalog["rows"], products, closed)
    table_by_brand = tw_table_models(tw_tables["rows"], api_plug_counts(raw), products)
    api_by_brand, tw_names = tw_models(raw, products, closed)

    # Priority. The printed catalogue first because it is the only source that knows
    # where a bike's plug changed mid-life; then CarMall's Taiwan sheets, which cover the
    # local lineup the Japanese catalogue never lists; then NGK Taiwan's finder API for
    # whatever neither has. Later sources only ever add bikes, never override one.
    brands, dropped, conflicts = [], {"tw_table": 0, "tw": 0}, []
    all_brands = set(cat_by_brand) | set(table_by_brand) | set(api_by_brand)
    for brand in sorted(all_brands, key=str.lower):
        models = list(cat_by_brand.get(brand, []))
        index = defaultdict(list)
        for m in models:
            index[match_key(m["name"])].append(m)
        for src in ("tw_table", "tw"):
            for m in (table_by_brand if src == "tw_table" else api_by_brand).get(brand, []):
                # A bike with no MotoDX has nothing to sell and no better source to fall
                # back on, so it is left out — the same rule the catalogue side applies.
                if all(e["no_dx"] for e in m["entries"]):
                    continue
                alias = TW_SAME_AS_CATALOG.get((brand, m["name"]))
                key = match_key(alias or m["name"])
                hit, agreed = superseded_by(m, index[key])
                if not agreed:
                    # Two sources, same bike, different part, and no year split to explain
                    # it. Source priority still decides which one ships, but a genuine
                    # contradiction is something a person has to settle — so it is
                    # printed rather than buried in the build.
                    conflicts.append((brand, m["name"], src, sorted(model_dx(m)),
                                      hit["name"], hit["src"], sorted(model_dx(hit))))
                if hit:
                    dropped[src] += 1
                    continue
                index[key].append(m)
                models.append(m)
        if not models:
            continue
        models.sort(key=lambda m: (m["name"].lower(), m["cc"] or 0))
        brands.append({"en": brand, "tw": tw_names.get(brand) or BRAND_TW.get(brand, ""),
                       "models": models})

    stats = {"fitments": 0, "buyable": 0, "short": 0}
    for b in brands:
        for m in b["models"]:
            for e in m["entries"]:
                stats["fitments"] += 1
                if any("url" in x for x in e["buys"]) and \
                        all("url" in x for x in e["buys"]):
                    stats["buyable"] += 1
                else:
                    stats["short"] += 1

    n = {s: sum(1 for b in brands for m in b["models"] if m["src"] == s)
         for s in ("catalog", "tw_table", "tw")}
    no_count = sum(1 for b in brands for m in b["models"] for e in m["entries"]
                   if any(x["count"] is None for x in e["engines"]))
    print(f"  brands   {len(brands)}")
    print(f"  models   {sum(n.values())}"
          f"   (原廠型錄 {n['catalog']} ／ 台灣對照表 {n['tw_table']} ／ 台灣官網 {n['tw']})")
    print(f"  年份分段  {stats['fitments']}")
    print(f"    可直接購買  {stats['buyable']}")
    print(f"    現貨不足    {stats['short']}")
    print(f"  支數不明     {no_count}")
    print(f"  因較可信來源已涵蓋而略過  台灣對照表 {dropped['tw_table']}"
          f" ／ 台灣官網 {dropped['tw']}")
    if closed:
        print(f"  型錄開放式年份收邊 {len(closed)} 筆：")
        for c in closed:
            print(f"      {c}")
    if conflicts:
        print(f"  ⚠ 兩份來源對同一台車給出不同料號 {len(conflicts)} 筆（採用較可信來源，需人工確認）：")
        for brand, name, src, dx, cname, csrc, cdx in conflicts:
            print(f"      {brand}「{name}」{SRC_TW[src]}{dx}"
                  f"  vs  「{cname}」{SRC_TW[csrc]}{cdx} ← 採用")
    # Validate before writing anything. A truncated input should leave the last good
    # data.json in place and show up as a red build, not replace a working finder with a
    # short one and then exit non-zero — by then the damage is on disk.
    if not stats["buyable"]:
        sys.exit("ERROR: nothing is buyable — product join failed")
    if n["catalog"] < 400 or n["tw_table"] < 40 or n["tw"] < 20:
        sys.exit(f"ERROR: source mix looks wrong: {n}")

    data = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {"catalog": catalog["source"], "tw_table": tw_tables["source"],
                    "tw": raw.get("source")},
        "brands": brands,
    }
    tmp = a.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, a.out)
    print(f"wrote {a.out}  ({os.path.getsize(a.out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
