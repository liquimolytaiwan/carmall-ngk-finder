#!/usr/bin/env python3
"""Extract the 二輪車 (motorcycle) fitment tables from NGK's book-format catalogue PDF.

    tools/source/ngk_book_2223.pdf  pp.129-200  ──►  tools/ngk_catalog_moto.json

Why this exists
---------------
NGK Taiwan's `/api/finder` returns one recommendation per bike with no model year for
most motorcycles, so a bike whose plug changed mid-life (Yamaha MT-03: CR8EDX-S before
'18.3, LMAR8ADX-9S after) is answered with a single part number — half the owners are
told to fit the wrong plug. The printed catalogue carries the year breaks the API drops,
so it, not the API, is the source of truth for fitment.

How the page is read
--------------------
Each data row is laid out as

    [排気量]  車名(年式)   MotoDX品番 在庫No   イリジウム品番 在庫No   標準/白金品番 在庫No   本数

`排気量` is printed only on the first row of each displacement group, so column
membership cannot be inferred from token order alone — a continuation row simply starts
at the model-name column. We therefore read word bounding boxes (`pdftotext
-bbox-layout`) and calibrate the model-name column's x position per page, which also
survives the CJK width collapsing that makes plain `-layout` text misalign.

The three plug cells are consumed right-to-left from the row's tokens, because the model
name is the only free-form field and it is always leftmost. `――` means "not made in this
line", `―` means "no stock number".
"""
import argparse, json, os, re, statistics, subprocess, sys, tempfile
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
NS = "{http://www.w3.org/1999/xhtml}"

DASH = "―"            # U+2015, used for both "――" (no part) and "―" (no stock no.)
NODATA = DASH * 2
SYMS = set("▼◇◎☆※")   # footnote glyphs, printed above the cell they annotate
TILDE = "～"

SOURCE_NAME = "NGK ブック式適応表 PACJA-010 22-23 (2022-03)"
DEFAULT_PDF = os.path.join(BASE, "source", "ngk_book_2223.pdf")
FIRST_PAGE, LAST_PAGE = 129, 200          # 二輪車: KAWASAKI … 外国車(二輪車)

RE_PART = re.compile(r"^[A-Z0-9][A-Z0-9\-/.]*$")
RE_STOCKNO = re.compile(r"^\d+$")
RE_JP_BRAND = re.compile(r"^(\S+?)／([A-Z][A-Za-z0-9\- ]*)$")        # カワサキ／KAWASAKI
# アプリリア＜APRILIA＞ — the Japanese half may itself contain a space ("ガス ガス＜GAS
# GAS＞"), so it is matched loosely; the fullwidth brackets appear nowhere but headers.
RE_FG_BRAND = re.compile(r"^(.+?)＜([A-Z0-9][A-Za-z0-9 .\-&]*)＞$")

# A parenthetical is a model year only if every token in it is a 2-digit year, optionally
# apostrophed and optionally suffixed モデル/年式. Guards against frame-number ranges
# like "(No.3128592～)", which also contain a tilde.
YR = r"'?\s*\d{2}(?:\.\d{1,2})?(?:モデル|年式)?"
RE_YEAR_GROUP = re.compile(rf"^\s*(?:{YR})?\s*(?:{TILDE}\s*(?:{YR})?)?\s*$")
RE_HAS_YEAR = re.compile(r"\d{2}")
RE_GROUP = re.compile(r"\(([^()]*)\)\)?")   # trailing ")" swallows a catalogue typo

# Rows that belong to the page furniture, never to a bike.
NOISE_SUB = ("Nomble", "熱価", "対照表", "DENSO", "橙文字", "締付", "端子",
             "プラグは", "P3,4", "二 輪 車", "外 国 車", "ご購入")

# Trailing qualifiers NGK appends to a model name. Kept out of the name and surfaced as
# a note, so "MT-03" and "MT-03(逆輸入)" don't look like two unrelated bikes.
QUALIFIERS = {
    "逆輸入": "平行輸入車",
    "国内モデル": "日規車",
    "欧州仕様": "歐規車",
    "北米仕様": "北美規車",
    "教習車": "駕訓車",
    "教習車モデル": "駕訓車",
    "タイ生産": "泰國產",
    "中国生産": "中國產",
    "台湾生産": "台灣產",
    "四輪バギー": "四輪 ATV",
    "三輪バギー": "三輪 ATV",
    "ゴールドメッキ仕様": "鍍金版",
}


def run_pdftotext(pdf, first, last):
    """Word bounding boxes for the requested pages, as an XHTML tree."""
    if not os.path.exists(pdf):
        sys.exit(f"ERROR: catalogue PDF not found: {pdf}\n"
                 f"       download it from the Drive link in README.md")
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        out = tmp.name
    try:
        subprocess.run(["pdftotext", "-bbox-layout", "-f", str(first), "-l", str(last),
                        pdf, out], check=True, capture_output=True)
        return ET.parse(out)
    except FileNotFoundError:
        sys.exit("ERROR: pdftotext not installed  (brew install poppler)")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: pdftotext failed: {e.stderr.decode()[:300]}")
    finally:
        os.unlink(out)


def page_rows(page):
    """Words of one page grouped into printed rows, each sorted left to right."""
    words = []
    for w in page.iter(NS + "word"):
        t = "".join(c for c in (w.text or "").strip() if c not in SYMS).strip()
        if not t:
            continue
        words.append((float(w.get("yMin")), float(w.get("yMax")),
                      float(w.get("xMin")), t))
    words.sort(key=lambda w: (w[0], w[2]))

    rows, cur, top = [], [], None
    for ymin, ymax, xmin, t in words:
        mid = (ymin + ymax) / 2
        # Row pitch is ~14pt and words of one row agree on y to <0.1pt; compare against
        # the row's first word rather than a running mean so long rows can't drift into
        # the next line.
        if top is None or abs(mid - top) <= 4.0:
            cur.append((xmin, t))
            top = mid if top is None else top
        else:
            rows.append(sorted(cur))
            cur, top = [(xmin, t)], mid
    if cur:
        rows.append(sorted(cur))
    return rows


def take_plug_cells(tokens):
    """Consume 本数 + three (品番, 在庫No) cells off the right end of a row.

    Returns (head_len, [(part, stockno) x3], count) or None if the row isn't a fitment.
    """
    j = len(tokens) - 1
    if j < 6 or not RE_STOCKNO.match(tokens[j]) or len(tokens[j]) > 2:
        return None
    count = int(tokens[j])
    if not 1 <= count <= 12:
        return None
    j -= 1
    cells = []
    for _ in range(3):
        if j < 0:
            return None
        tok = tokens[j]
        if tok == DASH or RE_STOCKNO.match(tok):        # stock number, part precedes it
            if j - 1 < 0:
                return None
            part, stockno, j = tokens[j - 1], tok, j - 2
        elif tok == NODATA:                             # not made, stock no. omitted
            part, stockno, j = tok, DASH, j - 1
        else:
            return None
        if part != NODATA and not RE_PART.match(part):
            return None
        cells.append((part, stockno))
    cells.reverse()                                     # DX, IX, STD
    return j + 1, cells, count


def split_name(raw):
    """Pull the model year and the spec qualifiers out of a catalogue model name.

    "MT-03(逆輸入)('06～)"        → ('MT-03', "'06～", ['平行輸入車'])
    "XJR400/R('95.3～)/RⅡ('96.1～)" → name kept intact, year spans both variants

    A year group is only removed from the name when the row carries exactly one; rows
    that list two dated variants under one plug spec keep their printed name, because
    dropping either date would misattribute the other.
    """
    groups = [(m.start(), m.end(), m.group(1).strip()) for m in RE_GROUP.finditer(raw)]
    years = [g for g in groups if RE_HAS_YEAR.search(g[2]) and RE_YEAR_GROUP.match(g[2])]
    quals = [g for g in groups if g[2] in QUALIFIERS]

    name, drop = raw, list(quals) + (years if len(years) == 1 else [])
    for s, e, _ in sorted(drop, key=lambda g: -g[0]):
        name = name[:s] + name[e:]
    name = re.sub(r"\s{2,}", " ", name).strip().rstrip("/").strip()

    if len(years) == 1:
        year = years[0][2]
    elif years:                                   # span every dated variant on the row
        parts = [y[2] for y in years]
        lo = parts[0].split(TILDE)[0].strip()
        hi = parts[-1].split(TILDE)[-1].strip()
        year = f"{lo}{TILDE}{hi}"
    else:
        year = ""
    return name, year, [QUALIFIERS[g[2]] for g in quals]


def norm_year(y):
    """"'15.10～'18.3" → ('2015-10', '2018-03'). Two-digit years wrap at 1960."""
    def one(tok):
        tok = re.sub(r"(?:モデル|年式)$", "", tok.strip().lstrip("'").strip())
        m = re.fullmatch(r"(\d{2})(?:\.(\d{1,2}))?", tok)
        if not m:
            return None
        yy = int(m.group(1))
        year = 1900 + yy if yy >= 60 else 2000 + yy
        return f"{year}-{int(m.group(2)):02d}" if m.group(2) else str(year)
    if not y:
        return None, None
    if TILDE in y:
        a, b = y.split(TILDE, 1)
        return one(a), one(b)
    v = one(y)
    return v, v


def parse(pdf, first, last):
    tree = run_pdftotext(pdf, first, last)
    out, unparsed, per_page = [], [], {}
    brand = brand_ja = brand_kind = None
    cc = None

    for pno, page in enumerate(tree.iter(NS + "page"), start=first):
        rows = page_rows(page)
        per_page[pno] = 0

        # Calibrate the model-name column: on rows that start with a displacement cell,
        # the second word is the start of the name.
        name_x = [r[1][0] for r in rows
                  if len(r) > 2 and re.fullmatch(r"\d{2,4}", r[0][1])
                  and take_plug_cells([t for _, t in r[2:]])]
        name_x = statistics.median(name_x) if name_x else None

        for r in rows:
            texts = [t for _, t in r]
            # Brand headers must be matched before the noise filter: on the first page of
            # a brand the header shares a printed row with the footnote legend.
            #
            # Match the joined row as well as each word, because a brand whose Latin name
            # contains a space is tokenised across two words — "ティーエムレーシング＜TM"
            # + "RACING＞". Missing the header does not fail loudly; it silently files
            # that brand's bikes under whichever brand came before it, which is how TM
            # Racing's TM250/TM400 ended up listed as Titans.
            hit = False
            joined = " ".join(t for t in texts if t != "■")
            for t in texts + [joined]:
                m = RE_JP_BRAND.match(t)
                if m and "■" in texts:
                    brand_ja, brand, brand_kind, cc = m.group(1), m.group(2).strip(), "jp", None
                    hit = True
                    break
                m = RE_FG_BRAND.match(t)
                if m:
                    brand_ja, brand, brand_kind, cc = m.group(1), m.group(2).strip(), "fg", None
                    hit = True
                    break
            if hit:
                continue
            line = " ".join(texts)
            if any(n in line for n in NOISE_SUB):
                continue

            got = take_plug_cells(texts)
            if not got:
                if len(texts) > 3 and any(c.isdigit() for c in line):
                    unparsed.append((pno, line[:160]))
                continue
            head_len, cells, count = got
            head = r[:head_len]
            if not head or brand is None:
                continue
            if (name_x is not None and len(head) > 1 and head[0][0] < name_x - 2
                    and re.fullmatch(r"\d{2,4}", head[0][1])):
                cc = int(head[0][1])
                head = head[1:]
            elif (name_x is not None and len(head) == 1 and head[0][0] < name_x - 2
                    and re.fullmatch(r"\d{2,4}", head[0][1])):
                continue                                # stray printed page number
            raw_name = " ".join(t for _, t in head)
            name, year, notes = split_name(raw_name)
            if not name:
                continue
            y_from, y_to = norm_year(year)
            val = lambda x: "" if x == NODATA else x
            out.append({
                "page": pno,
                "brand": brand, "brand_ja": brand_ja, "brand_kind": brand_kind,
                "cc": cc,
                "name_ja": name, "raw": raw_name, "notes": notes,
                "year_raw": year, "year_from": y_from, "year_to": y_to,
                "dx": val(cells[0][0]), "ix": val(cells[1][0]), "std": val(cells[2][0]),
                "count": count,
            })
            per_page[pno] += 1
    return out, unparsed, per_page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=DEFAULT_PDF)
    ap.add_argument("--first", type=int, default=FIRST_PAGE)
    ap.add_argument("--last", type=int, default=LAST_PAGE)
    ap.add_argument("--out", default=os.path.join(BASE, "ngk_catalog_moto.json"))
    ap.add_argument("--min-rows", type=int, default=3300,
                    help="fail if fewer fitment rows are recovered than this")
    a = ap.parse_args()

    rows, unparsed, per_page = parse(a.pdf, a.first, a.last)
    dx = [r for r in rows if r["dx"]]

    print(f"pages   {a.first}-{a.last}")
    print(f"rows    {len(rows)}")
    print(f"  with MotoDX  {len(dx)}")
    print(f"  brands       {len({r['brand'] for r in rows})}")
    print(f"  MotoDX 料號   {len({r['dx'] for r in dx})}")

    # Fail loudly rather than write a short file: a parser regression shows up as rows
    # quietly going missing, and a half-empty catalogue reads as "this bike has no plug".
    blank = [p for p, n in per_page.items() if n == 0]
    real_unparsed = [u for u in unparsed if "熱" not in u[1]]
    if blank:
        print(f"ERROR: no rows recovered from pages {blank}", file=sys.stderr)
        sys.exit(1)
    if len(rows) < a.min_rows:
        print(f"ERROR: only {len(rows)} rows, expected >= {a.min_rows}", file=sys.stderr)
        sys.exit(1)
    if real_unparsed:
        print(f"ERROR: {len(real_unparsed)} table rows did not parse:", file=sys.stderr)
        for p, u in real_unparsed[:10]:
            print(f"  p{p}  {u}", file=sys.stderr)
        sys.exit(1)

    json.dump({"source": SOURCE_NAME, "pages": [a.first, a.last], "rows": rows},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out}  ({os.path.getsize(a.out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
