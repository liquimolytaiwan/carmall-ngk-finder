#!/usr/bin/env python3
"""Read the Taiwan-market MotoDX tables CarMall supplied as spreadsheets.

    tools/source/{kymco,sym,yamaha}_dx.xlsx  ──►  tools/ngk_tw_tables.json

NGK's printed catalogue is the Japanese domestic edition, so the scooters Taiwan
actually rides — KRV, MMBCU, 金發財, 勁多利, 新名流 — are not in it at any year. These
sheets are the Taiwan lineup, listed by the part number CarMall stocks.

Sheet shape
-----------
Two model blocks sit side by side (columns A-C and E-G), and the DX part number is
printed once against the first bike of a run, then left blank for the rest of that run:

    機種              原廠型號   DX型號
    KRV 180          CPR8EA-9  CPR8EDX-9S   ← run starts
    Gsense 125       CPR8EA-9               ← same plug
    RACING S 150     CPR8EA-9               ← same plug
    Krider400(雙缸)   CR9EIA-9  CR9EDX-S     ← next run

So a blank DX cell means "same as the row above", not "no MotoDX". Reading it as empty
would silently drop most of the sheet; the fill-down is the whole encoding.

These tables carry no model years. Anything they cover that the printed catalogue also
covers is left to the catalogue, which does — see build_data.py.
"""
import argparse, json, os, re, sys, zipfile
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "source")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# file, brand, sheet to read, and the (機種, 原廠, DX) column triples of each block.
SHEETS = [
    ("kymco_dx.xlsx", "KYMCO", None, [("A", "B", "C"), ("E", "F", "G")]),
    ("sym_dx.xlsx", "SYM", None, [("A", "B", "C"), ("E", "F", "G")]),
    # The Yamaha workbook's first sheet is a GP/銥合金 table with no MotoDX column at
    # all; only 'DX對應表' is a MotoDX source, and it has no 原廠 column.
    ("yamaha_dx.xlsx", "YAMAHA", "DX對應表", [("A", None, "C"), ("E", None, "G")]),
]

RE_PART = re.compile(r"^[A-Z][A-Z0-9\-]*$")
HEADER_WORDS = ("機種", "原廠", "DX", "對照表", "品番", "規格", "型號")


def read_sheet(path, want_sheet):
    """Rows of one worksheet as {column letter: text}."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    names = [s.get("name") for s in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet")]
    paths = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    idx = names.index(want_sheet) if want_sheet else 0
    if idx >= len(paths):
        sys.exit(f"ERROR: {os.path.basename(path)} has no sheet {want_sheet!r}")

    rows = []
    for row in ET.fromstring(z.read(paths[idx])).iter(NS + "row"):
        cells = {}
        for c in row.iter(NS + "c"):
            col = re.match(r"([A-Z]+)", c.get("r")).group(1)
            v, inline = c.find(NS + "v"), c.find(NS + "is")
            if c.get("t") == "s" and v is not None:
                text = shared[int(v.text)]
            elif inline is not None:
                text = "".join(t.text or "" for t in inline.iter(NS + "t"))
            else:
                text = v.text if v is not None else ""
            cells[col] = re.sub(r"\s+", " ", (text or "")).strip()
        rows.append(cells)
    return rows


def parse_file(fname, brand, sheet, blocks):
    rows = read_sheet(os.path.join(SRC, fname), sheet)
    out = []
    for model_col, oem_col, dx_col in blocks:
        current_dx = None
        for r in rows:
            model = r.get(model_col, "")
            dx = r.get(dx_col, "")
            if not model or any(w in model for w in HEADER_WORDS):
                continue
            if dx:
                if not RE_PART.match(dx):
                    sys.exit(f"ERROR: {fname} {model!r} has an unreadable DX cell {dx!r}")
                current_dx = dx
            if not current_dx:
                # A model above the sheet's first DX value has no plug to inherit.
                sys.exit(f"ERROR: {fname} {model!r} appears before any DX 型號")
            out.append({
                "brand": brand, "model": model,
                "oem": r.get(oem_col, "") if oem_col else "",
                "dx": current_dx,
                "dx_explicit": bool(dx),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, "ngk_tw_tables.json"))
    a = ap.parse_args()

    rows = []
    for fname, brand, sheet, blocks in SHEETS:
        path = os.path.join(SRC, fname)
        if not os.path.exists(path):
            sys.exit(f"ERROR: missing {path}")
        got = parse_file(fname, brand, sheet, blocks)
        print(f"{fname:16s} {brand:8s} {len(got):3d} 車款  "
              f"{len({g['dx'] for g in got})} 種 DX 料號")
        rows.extend(got)

    # A run that never starts, or a sheet read as one long run, both show up here.
    runs = sum(1 for r in rows if r["dx_explicit"])
    print(f"total {len(rows)} 車款 / {runs} 個料號分組")
    if len(rows) < 80 or runs < 8:
        print(f"ERROR: sheets look under-read ({len(rows)} rows, {runs} runs)", file=sys.stderr)
        sys.exit(1)

    json.dump({"source": "CarMall 提供之台灣機種別 MOTO DX 對照表", "rows": rows},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
