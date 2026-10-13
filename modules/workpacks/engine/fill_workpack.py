#!/usr/bin/env python3
"""
Fill certification forms from one input workbook.

The blank templates are NEVER modified. The tool reads a blank template, writes a filled COPY
to the output folder, and then proves the copy differs from the template only in the cells it
was asked to fill (all other parts of the file are byte-for-byte identical, including the
document protection settings).

Usage:
    python fill_workpack.py                            (no arguments: opens file/folder pickers)
    python fill_workpack.py --make-sheet "<new input workbook.xlsx>"
    python fill_workpack.py "<input workbook.xlsx>" --templates "<templates folder>" --out "<output folder>"
                            [--overwrite] [--add-rows] [--validate] [--no-open]

It only writes new files inside the output folder, and refuses to run if the output folder is
the template folder or inside it.
"""
import argparse, copy, csv, datetime, io, os, re, sys, zipfile
from collections import OrderedDict, defaultdict
from lxml import etree

try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    openpyxl = None

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"
q = lambda t: "{%s}%s" % (W, t)

# =========================================================================== form catalogue
# Folder each form is written to, mirroring the workpack section folders.
SECTION = {
    "SH1": "2.0 SYSTEM HANDOVER", "MC1": "3.0 MC1", "PL1 A": "4.0 PL1", "PL1 B": "4.0 PL1",
    "AS1": "6.0 MECHANICAL CERTIFICATION", "JI1": "6.0 MECHANICAL CERTIFICATION",
    "MP1": "6.0 MECHANICAL CERTIFICATION", "SL1": "6.0 MECHANICAL CERTIFICATION",
    "EE12": "7.0 E&I CERTIFICATION", "SC1": "7.0 E&I CERTIFICATION",
}
DEFAULT_SECTION = "99 OTHER FORMS"

# Header block fields: key -> accepted label texts (compared ignoring case, spaces and colons)
HEADER_LABELS = OrderedDict([
    ("title", ["projecttitle"]),
    ("project_no", ["projectno", "fcpno"]),
    ("workpack", ["workpackno", "wpkno"]),
    ("sh1", ["sh1no", "sh1number"]),
    ("mc1", ["mc1no"]),
    ("site", ["site"]),
    ("punch_no", ["punchlistnumber"]),
    ("discipline", ["discipline"]),
    ("hdr_location", ["location"]),
])
HEADER_BOOKMARK = {"bmProjectCodeDesc": "title", "bmProjectCode": "project_no", "bmCertWorkpack": "workpack",
                   "bmSH1": "sh1", "bmUniqueSecondaryHandoverNo": "mc1", "bmSiteCode": "site",
                   "bmPrimaryHandoverProjectCodeDesc": "title", "bmPrimaryHandoverNumber": "sh1",
                   "bmPrimaryHandoverSiteCode": "site", "bmSecondaryHandoverProjectCodeDesc": "title",
                   "bmSecondaryHandoverProjectCode": "project_no", "bmSecondaryHandoverSiteCode": "site",
                   "bmPL": "punch_no", "bmDiscipline": "discipline", "bmLocation": "hdr_location"}

# Body field slots. loc = (table index in main part, row, col); label = (row, col, expected label text)
# slot: "bm" = the empty run inside the cell's bookmark; "para:N" = paragraph N of the cell.
BODY_FIELDS = {
    "AS1": [("equipment", (0, 0, 1), (0, 0, "equipment"), "bm"), ("location", (0, 0, 3), (0, 2, "location"), "bm"),
            ("area", (0, 1, 1), (1, 0, "area"), "bm"), ("system", (0, 1, 3), (1, 2, "system"), "bm"),
            ("drawing", (0, 2, 1), (2, 0, "drawing"), "bm"), ("subsystem", (0, 2, 3), (2, 2, "sub-system"), "bm"),
            ("scope", (0, 3, 0), (3, 0, "scope of certificate"), "para:1")],
    "EE12": [("equipment", (0, 0, 1), (0, 0, "equipment"), "bm"), ("location", (0, 0, 3), (0, 2, "location"), "bm"),
             ("drawing", (0, 1, 1), (1, 0, "sld"), "bm"), ("system", (0, 1, 3), (1, 2, "system"), "bm"),
             ("subsystem", (0, 2, 2), (2, 1, "sub-system"), "bm")],
    "SC1": [("equipment", (0, 0, 1), (0, 0, "equipment"), "bm"), ("location", (0, 0, 3), (0, 2, "location"), "bm"),
            ("description", (0, 1, 1), (1, 0, "equipment description"), "bm"), ("system", (0, 1, 3), (1, 2, "system"), "bm"),
            ("drawing", (0, 2, 3), (2, 2, "p & id"), "bm"), ("procedure", (0, 4, 0), (3, 0, "commissioning procedure no"), "para:0")],
    "MP1": [("equipment", (0, 0, 1), (0, 0, "equipment"), "bm"), ("location", (0, 0, 3), (0, 2, "location"), "bm"),
            ("drawing", (0, 1, 1), (1, 0, "p & id"), "bm"), ("system", (0, 1, 3), (1, 2, "system"), "bm"),
            ("subsystem", (0, 2, 2), (2, 1, "sub-system"), "bm")],
    "SL1": [("equipment", (0, 0, 1), (0, 0, "equipment"), "bm"), ("location", (0, 0, 3), (0, 2, "location"), "bm"),
            ("system", (0, 1, 3), (1, 2, "system"), "bm")],
    "JI1": [("location", (0, 0, 1), (0, 0, "location"), "bm"),
            ("system", (0, 0, 3), (0, 2, "system"), "para:0"), ("subsystem", (0, 0, 5), (0, 4, "sub-system"), "para:0")],
    "SH1": [("handover_title", (0, 0, 0), (0, 0, "handover title"), "bm"),
            ("handover_includes", (0, 3, 0), (3, 0, "handover includes"), "bm"),
            ("handover_excludes", (0, 6, 0), (6, 0, "handover excludes"), "bm"),
            ("sh1_number_block", (1, 1, 2), (1, 1, "sh1 number"), "bm"),
            ("mc1_cert_nos", (0, 1, 2), (1, 1, "mc1 certificate no"), "bm")],
    "MC1": [("handover_title", (0, 0, 0), (0, 0, "handover title"), "para:1"),
            ("handover_includes", (0, 2, 0), (2, 0, "handover includes"), "bm"),
            ("mc1_number_block", (1, 1, 1), (1, 1, "mc1 number"), "bm")],
}
# Repeating-row tables: (table index, first data row, {column: key}, header labels to verify)
ROW_TABLES = {
    "SL1": (1, 2, {0: "pid", 1: "line", 3: "from", 4: "to"}, [(0, 0, "p & id no"), (0, 1, "line no")], "Lines"),
    "MP1": (1, 2, {0: "pid", 1: "line", 3: "from", 4: "to"}, [(0, 0, "iso no"), (0, 1, "line no")], "Lines"),
    "JI1": (1, 3, {0: "joint", 1: "drawing", 2: "size", 3: "rating", 4: "type", 6: "torque"}, [(0, 0, "joint number"), (0, 1, "drawing")], "Joints"),
}

# =========================================================================== small helpers
class FillError(Exception):
    pass

def norm_label(s):
    return re.sub(r"[^a-z0-9&]", "", (s or "").lower())

def ptext(p):
    return "".join(t.text or "" for t in p.iter(q("t")))

def ctext(tc):
    return " ".join(ptext(p) for p in tc.findall(q("p"))).strip()

def main_part_name(z):
    rels = z.read("_rels/.rels").decode("utf-8", "ignore")
    m = re.search(r'Type="[^"]*/officeDocument"[^>]*Target="([^"]+)"', rels) or re.search(r'Target="([^"]+)"[^>]*Type="[^"]*/officeDocument"', rels)
    if m:
        return m.group(1).lstrip("/")
    for n in z.namelist():
        if re.match(r"word/document\d*\.xml$", n):
            return n
    raise FillError("no main document part found")

def top_tables(root):
    return [t for t in root.iter(q("tbl")) if not any(a.tag == q("tbl") for a in t.iterancestors())]

def get_cell(tbl, r, c):
    rows = tbl.findall(q("tr"))
    if r >= len(rows):
        raise FillError("table has %d rows, wanted row %d" % (len(rows), r))
    cells = rows[r].findall(q("tc"))
    if c >= len(cells):
        raise FillError("row %d has %d cells, wanted cell %d" % (r, len(cells), c))
    return cells[c]

def para_rpr(p):
    """Run formatting a new run should carry: what Word would use when typing in this paragraph."""
    ppr = p.find(q("pPr"))
    if ppr is not None and ppr.find(q("rPr")) is not None:
        rpr = copy.deepcopy(ppr.find(q("rPr")))
        return rpr
    for r in reversed(p.findall(q("r"))):
        if r.find(q("rPr")) is not None:
            return copy.deepcopy(r.find(q("rPr")))
    return None

def set_t(r, text):
    for t in r.findall(q("t")):
        r.remove(t)
    t = etree.SubElement(r, q("t"))
    t.text = text
    if text != text.strip() or "  " in text:
        t.set("{%s}space" % XML, "preserve")

def new_run(p, text, before=None):
    r = etree.Element(q("r"))
    rpr = para_rpr(p)
    if rpr is not None:
        r.append(rpr)
    set_t(r, text)
    if before is not None:
        before.addprevious(r)
    else:
        p.append(r)
    return r

def bookmark_slot(p):
    """The empty run (or position) inside the paragraph's named bookmark, or None."""
    for bs in p.iter(q("bookmarkStart")):
        name = bs.get(q("name")) or ""
        if name.startswith("_"):
            continue
        be = None
        nxt = bs.getnext()
        runs = []
        while nxt is not None and not (nxt.tag == q("bookmarkEnd") and nxt.get(q("id")) == bs.get(q("id"))):
            if nxt.tag == q("r"):
                runs.append(nxt)
            nxt = nxt.getnext()
        return name, bs, runs, nxt
    return None

def write_paragraph(p, text, mode="bm", allow_existing_label=False):
    """Put text into paragraph p at its slot. Refuses to overwrite typed text."""
    slot = bookmark_slot(p) if mode == "bm" else None
    if slot:
        name, bs, runs, be = slot
        existing = "".join(ptext(r) for r in runs)
        if existing.strip():
            raise FillError("slot '%s' already holds text '%s'" % (name, existing.strip()[:30]))
        if runs:
            set_t(runs[0], text)
            for extra in runs[1:]:
                for t in extra.findall(q("t")):
                    t.text = ""
        else:
            new_run(p, text, before=be) if be is not None else new_run(p, text)
        return name
    # no bookmark: paragraph must be empty (whitespace only) apart from allowed label text
    if ptext(p).strip() and not allow_existing_label:
        raise FillError("paragraph already holds text '%s'" % ptext(p).strip()[:30])
    rs = p.findall(q("r"))
    blank = [r for r in rs if not ptext(r).strip()]
    if blank and len(blank) == len(rs):
        set_t(blank[0], text)
        for extra in blank[1:]:
            for t in extra.findall(q("t")):
                t.text = ""
    else:
        new_run(p, text)
    return None

def clone_empty_paragraph(p):
    n = copy.deepcopy(p)
    for child in list(n):
        if child.tag != q("pPr"):
            n.remove(child)
    return n

# =========================================================================== template access
def find_template(tpl_dir, code):
    best = None
    for dp, dn, fn in os.walk(tpl_dir):
        for f in sorted(fn):
            if f.lower().endswith(".docx") and not f.startswith("~$"):
                stem = os.path.splitext(f)[0]
                if stem.lower() == code.lower() or stem.lower().startswith(code.lower() + " "):
                    if best is None:
                        best = os.path.join(dp, f)
    return best

class Doc:
    """A template opened read-only; edits happen on in-memory XML trees."""
    def __init__(self, path):
        self.path = path
        self.zin = zipfile.ZipFile(path, "r")
        self.main = main_part_name(self.zin)
        self.trees = {}
        self.changed = set()
        self.touched = []          # (part, description) audit trail

    def tree(self, name):
        if name not in self.trees:
            self.trees[name] = etree.fromstring(self.zin.read(name))
        return self.trees[name]

    def header_parts(self):
        return [n for n in self.zin.namelist() if re.match(r"word/header\d*\.xml$", n)]

    def save(self, out_path):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with zipfile.ZipFile(out_path, "w") as zout:
            for it in self.zin.infolist():
                data = self.zin.read(it.filename)
                if it.filename in self.changed:
                    data = etree.tostring(self.trees[it.filename], xml_declaration=True, encoding="UTF-8", standalone=True)
                zi = zipfile.ZipInfo(it.filename, it.date_time)
                zi.compress_type = it.compress_type
                zi.external_attr = it.external_attr
                zout.writestr(zi, data)

# =========================================================================== filling operations
def fill_header(doc, values, log):
    filled = set()
    for part in doc.header_parts():
        root = doc.tree(part)
        for tbl in root.iter(q("tbl")):
            for tr in tbl.findall(q("tr")):
                cells = tr.findall(q("tc"))
                for i, c in enumerate(cells):
                    first = norm_label(ptext(c.findall(q("p"))[0])) if c.findall(q("p")) else ""
                    for key, labels in HEADER_LABELS.items():
                        if key not in values or not values[key]:
                            continue
                        if first not in labels:
                            continue
                        # value location: the next cell in the row, or (for SITE) the second paragraph of the same cell
                        if key == "site" and len(c.findall(q("p"))) >= 2 and "site" in first and len(cells[i + 1:]) >= 0 and c is cells[i]:
                            target = c.findall(q("p"))[1]
                        else:
                            if i + 1 >= len(cells):
                                continue
                            ps = cells[i + 1].findall(q("p"))
                            target = next((p for p in ps if bookmark_slot(p)), ps[0] if ps else None)
                        if target is None:
                            continue
                        # a label such as "Location:" also exists in body tables, but we only scan header parts
                        bm = bookmark_slot(target)
                        try:
                            used = write_paragraph(target, values[key], "bm" if bm else "none")
                        except FillError as e:
                            raise FillError("header '%s': %s" % (key, e))
                        if bm and bm[0] in HEADER_BOOKMARK and HEADER_BOOKMARK[bm[0]] != key:
                            log.append(("WARN", "bookmark '%s' normally belongs to %s but sits on the cell labelled %s; filled by label" % (bm[0], HEADER_BOOKMARK[bm[0]], key)))
                        doc.changed.add(part)
                        doc.touched.append((part, "header " + key))
                        filled.add(key)
    return filled

def fill_body(doc, form, values, log):
    root = doc.tree(doc.main)
    tables = top_tables(root)
    for key, (ti, ri, ci), (lr, lc, lab), slot in BODY_FIELDS.get(form, []):
        if key not in values or values[key] in (None, ""):
            continue
        if ti >= len(tables):
            raise FillError("template has no table %d for field '%s'" % (ti, key))
        tbl = tables[ti]
        got = norm_label(ctext(get_cell(tbl, lr, lc)))
        if not got.startswith(norm_label(lab)):
            raise FillError("label check failed for '%s': expected '%s' beside the slot, found '%s'" % (key, lab, got[:40]))
        tc = get_cell(tbl, ri, ci)
        text = str(values[key])
        paras = tc.findall(q("p"))
        if slot == "bm":
            p = next((p for p in paras if bookmark_slot(p)), None)
            if p is None:
                raise FillError("no bookmark slot found for '%s'" % key)
            lines = text.split("\n")
            write_paragraph(p, lines[0], "bm", allow_existing_label=True)
            prev = p
            for extra in lines[1:]:
                nxt = prev.getnext()
                if nxt is not None and nxt.tag == q("p") and not ptext(nxt).strip():
                    write_paragraph(nxt, extra, "none")
                    prev = nxt
                else:
                    n = clone_empty_paragraph(prev)
                    prev.addnext(n)
                    write_paragraph(n, extra, "none")
                    prev = n
        else:
            idx = int(slot.split(":")[1])
            while len(paras) <= idx:
                n = clone_empty_paragraph(paras[-1])
                paras[-1].addnext(n)
                paras = tc.findall(q("p"))
            lines = text.split("\n")
            prev = paras[idx]
            write_paragraph(prev, lines[0], "none")
            for extra in lines[1:]:
                nxt = prev.getnext()
                if nxt is not None and nxt.tag == q("p") and not ptext(nxt).strip():
                    write_paragraph(nxt, extra, "none")
                    prev = nxt
                else:
                    n = clone_empty_paragraph(prev)
                    prev.addnext(n)
                    write_paragraph(n, extra, "none")
                    prev = n
        doc.changed.add(doc.main)
        doc.touched.append((doc.main, "%s table %d row %d col %d" % (key, ti, ri, ci)))

def fill_rows(doc, form, rows, add_rows, log, spare_rows=None):
    spec = ROW_TABLES.get(form)
    if not spec or not rows:
        return
    ti, first, cols, headers, _ = spec
    root = doc.tree(doc.main)
    tables = top_tables(root)
    tbl = tables[ti]
    for (r, c, lab) in headers:
        got = norm_label(ctext(get_cell(tbl, r, c)))
        if not got.startswith(norm_label(lab)):
            raise FillError("table header check failed: expected '%s', found '%s'" % (lab, got[:40]))
    trs = tbl.findall(q("tr"))
    width = len(trs[first].findall(q("tc")))
    capacity = []
    for k in range(first, len(trs)):
        cells = trs[k].findall(q("tc"))
        if len(cells) != width:
            break
        if any(ctext(cells[c]).strip() and ctext(cells[c]).strip().upper() not in ("YES/NO",) for c in cols):
            break
        capacity.append(trs[k])
    if len(rows) > len(capacity):
        if not add_rows:
            raise FillError("%d line rows supplied but the template has room for %d (use --add-rows to add rows)" % (len(rows), len(capacity)))
        last = capacity[-1]
        while len(capacity) < len(rows):
            n = copy.deepcopy(last)
            last.addnext(n)
            last = n
            capacity.append(n)
            log.append(("WARN", "added a table row (template had %d)" % (len(capacity) - 1)))
    for tr, rec in zip(capacity, rows):
        cells = tr.findall(q("tc"))
        for c, key in cols.items():
            v = rec.get(key)
            if v in (None, ""):
                continue
            ps = cells[c].findall(q("p"))
            p = next((p for p in ps if bookmark_slot(p)), ps[0])
            write_paragraph(p, str(v), "bm" if bookmark_slot(p) else "none")
    if spare_rows is not None:
        keep = len(rows) + spare_rows
        removed = 0
        for tr in capacity[keep:]:
            tr.getparent().remove(tr)
            removed += 1
        if removed:
            log.append(("INFO", "removed %d unused blank row(s), keeping %d spare" % (removed, spare_rows)))
    doc.changed.add(doc.main)
    doc.touched.append((doc.main, "%d rows in table %d" % (len(rows), ti)))

# ---- EE12: description of tests + nested tag/drawing table
NESTED_COLS = [1524, 3913, 1560, 3188]

def _run(text, bold=False, font=None):
    r = etree.Element(q("r"))
    rpr = etree.SubElement(r, q("rPr"))
    if font:
        f = etree.SubElement(rpr, q("rFonts"))
        f.set(q("ascii"), font); f.set(q("hAnsi"), font)
    if bold:
        etree.SubElement(rpr, q("b"))
    set_t(r, text)
    return r

def _cell(width, text, header=False):
    tc = etree.Element(q("tc"))
    pr = etree.SubElement(tc, q("tcPr"))
    tw = etree.SubElement(pr, q("tcW")); tw.set(q("w"), str(width)); tw.set(q("type"), "dxa")
    if header:
        sh = etree.SubElement(pr, q("shd")); sh.set(q("val"), "clear"); sh.set(q("color"), "auto"); sh.set(q("fill"), "D9D9D9")
    va = etree.SubElement(pr, q("vAlign")); va.set(q("val"), "center")
    p = etree.SubElement(tc, q("p"))
    ppr = etree.SubElement(p, q("pPr"))
    jc = etree.SubElement(ppr, q("jc")); jc.set(q("val"), "center")
    if text or header:
        p.append(_run(text, bold=header, font="Trebuchet MS" if header else None))
    return tc

def build_tag_table(tags):
    tbl = etree.Element(q("tbl"))
    pr = etree.SubElement(tbl, q("tblPr"))
    tw = etree.SubElement(pr, q("tblW")); tw.set(q("w"), str(sum(NESTED_COLS))); tw.set(q("type"), "dxa")
    ti = etree.SubElement(pr, q("tblInd")); ti.set(q("w"), "108"); ti.set(q("type"), "dxa")
    b = etree.SubElement(pr, q("tblBorders"))
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = etree.SubElement(b, q(side)); e.set(q("val"), "single"); e.set(q("sz"), "4"); e.set(q("space"), "0"); e.set(q("color"), "auto")
    lay = etree.SubElement(pr, q("tblLayout")); lay.set(q("type"), "fixed")
    grid = etree.SubElement(tbl, q("tblGrid"))
    for w in NESTED_COLS:
        g = etree.SubElement(grid, q("gridCol")); g.set(q("w"), str(w))
    def row(vals, header=False, height=362):
        tr = etree.SubElement(tbl, q("tr"))
        trp = etree.SubElement(tr, q("trPr"))
        h = etree.SubElement(trp, q("trHeight")); h.set(q("val"), str(567 if header else height))
        for w, v in zip(NESTED_COLS, vals):
            tr.append(_cell(w, v, header))
    row(["TAG", "DRAWING No.", "COMPLETE", "REMARKS"], header=True)
    for t in tags:
        row([t.get("tag") or "", t.get("drawing") or "", "", ""])
    return tbl

def unbold(p):
    """Free text should read as plain text, even when the template's paragraph mark is bold."""
    for r in p.findall(q("r")):
        rpr = r.find(q("rPr"))
        if rpr is not None:
            for tag in ("b", "bCs"):
                for e in rpr.findall(q(tag)):
                    rpr.remove(e)

TABLE_MARKER = "[TAGS]"

def fill_ee12_block(doc, description, tags, log):
    """Description-of-tests text and the nested TAG / DRAWING list, in the 'description' cell.
    A line containing only [TAGS] marks where the tag table goes; without it the table follows the text."""
    if not description and not tags:
        return
    root = doc.tree(doc.main)
    tables = top_tables(root)
    if len(tables) < 2:
        raise FillError("EE12 template layout not recognised (expected 2 tables)")
    tc = get_cell(tables[1], 0, 0)
    if not norm_label(ctext(tc)).startswith("descriptionoftestscarriedout"):
        raise FillError("EE12 description cell not found (label check failed)")
    if tc.find(q("tbl")) is not None:
        raise FillError("EE12 description cell already contains a table")
    paras = tc.findall(q("p"))
    if any(ptext(p).strip() for p in paras[1:]):
        raise FillError("EE12 description cell already holds text")
    anchor = paras[1] if len(paras) > 1 else paras[0]
    lines = (description or "").split(chr(10))
    if TABLE_MARKER in [l.strip() for l in lines]:
        k = [l.strip() for l in lines].index(TABLE_MARKER)
        before, after = lines[:k], lines[k + 1:]
    else:
        before, after = lines, []
    prev = anchor
    first = True
    def put(line, prev, first):
        p = anchor if first else clone_empty_paragraph(anchor)
        if not first:
            prev.addnext(p)
        if line:
            write_paragraph(p, line, "none", allow_existing_label=True)
            unbold(p)
        return p
    for line in before:
        prev = put(line, prev, first)
        first = False
    if tags:
        tbl = build_tag_table(tags)
        prev.addnext(tbl)
        prev = tbl
        # a paragraph must follow a table inside a cell: the text after the marker, or a spacer
        for line in (after if after else [""]):
            p = clone_empty_paragraph(anchor)
            prev.addnext(p)
            if line:
                write_paragraph(p, line, "none", allow_existing_label=True)
                unbold(p)
            prev = p
    elif after:
        for line in after:
            prev = put(line, prev, False)
    doc.changed.add(doc.main)
    doc.touched.append((doc.main, "EE12 description and %d tag rows" % len(tags or [])))

# =========================================================================== verification
def part_cells(root):
    """{path: text} for every cell and every body paragraph outside tables, to compare before and after."""
    out = {}
    def walk(tbl, pref):
        for ri, tr in enumerate(tbl.findall(q("tr"))):
            for ci, tc in enumerate(tr.findall(q("tc"))):
                out["%s r%d c%d" % (pref, ri, ci)] = "\n".join(ptext(p) for p in tc.findall(q("p")))
                for ni, nt in enumerate(tc.findall(q("tbl"))):
                    walk(nt, "%s r%d c%d n%d" % (pref, ri, ci, ni))
    for ti, t in enumerate(top_tables(root)):
        walk(t, "t%d" % ti)
    return out

# =========================================================================== input workbook
PROJECT_FIELDS = [
    ("title", "Project title", "Shown in every form header, e.g. the wellbay clearance title"),
    ("project_no", "Project number (FCP)", "Header: Project No"),
    ("workpack", "Workpack number (Apache document / CCHP no)", "Header: Workpack No (forms that have it)"),
    ("sh1", "SH1 number", "Header: SH1 No, and the SH1 number block on the SH1 form"),
    ("mc1", "MC1 number", "Header: MC1 No, and the MC1 number block on the MC1 form"),
    ("site", "Site", "Header: SITE"),
    ("location", "Default location", "Used when a certificate row leaves Location blank"),
    ("system", "Default system", "Used when a certificate row leaves System blank"),
    ("subsystem", "Default sub-system", "Used when a certificate row leaves Sub-system blank"),
    ("handover_title", "Handover title (SH1 / MC1)", "Leave blank to use the project title"),
    ("handover_includes", "Handover includes (SH1 / MC1)", "One line per line of text; blank lines are kept"),
    ("handover_excludes", "Handover excludes (SH1)", "e.g. N/A"),
    ("ee12_description", "Standard description of tests (EE12)", "Used for every EE12 unless the certificate row has its own. A line containing only [TAGS] marks where the tag table goes"),
]
CERT_COLUMNS = [
    ("id", "ID", "A short unique name for this certificate, e.g. AS1-PL33000"),
    ("form", "Form", "AS1, EE12, SC1, SL1, MP1, JI1, SH1, MC1, PL1 A, PL1 B (others: header only)"),
    ("filename", "Output file name (optional)", "Without .docx. Blank = '<Form> <ID>'"),
    ("equipment", "Equipment / line", "EQUIPMENT cell"),
    ("location", "Location", "Blank = default location"),
    ("area", "Area", "AS1 only"),
    ("system", "System", "Blank = default system"),
    ("subsystem", "Sub-system", "Blank = default sub-system"),
    ("drawing", "Drawing / P&ID / SLD", "AS1 drawing, EE12 SLD, MP1 and SC1 P&ID"),
    ("description", "Equipment description", "SC1 only"),
    ("scope", "Scope of certificate", "AS1 only; free text"),
    ("procedure", "Commissioning procedure text", "SC1 only; free text"),
    ("ee12_description", "Description of tests (EE12 override)", "Blank = standard description from the Project sheet"),
    ("punch_no", "Punch list number", "PL1 only (header)"),
    ("discipline", "Discipline", "PL1 only (header)"),
    ("folder", "Output folder (optional)", "Blank = standard section folder for the form"),
]
LINE_COLUMNS = [("cert", "Certificate ID", "Must match an ID on the Certificates sheet (SL1 or MP1 rows)"),
                ("pid", "P&ID No / ISO No", "SL1: P&ID No. MP1: ISO No"),
                ("line", "Line No", ""), ("from", "From equipment", ""), ("to", "To equipment", "")]
JOINT_COLUMNS = [("cert", "Certificate ID", "Must match a JI1 ID on the Certificates sheet"),
                 ("joint", "Joint number", ""), ("drawing", "Drawing", ""), ("size", "Flange size (NB)", ""),
                 ("rating", "Rating", ""), ("type", "Type", "e.g. Seal Ring, RTJ"), ("torque", "Required torque value", "")]
TAG_COLUMNS = [("cert", "Certificate ID", "Must match an EE12 ID on the Certificates sheet"),
                ("tag", "Tag", ""), ("drawing", "Drawing No.", "")]

def make_sheet(path):
    if openpyxl is None:
        raise FillError("openpyxl is required")
    wb = openpyxl.Workbook()
    head = PatternFill("solid", fgColor="1F4E79")
    note = PatternFill("solid", fgColor="EAF1FB")
    ws = wb.active
    ws.title = "Read me"
    lines = ["Workpack input sheet", "",
             "Fill the Project sheet once, then one row per certificate on the Certificates sheet.",
             "Lines (SL1 / MP1) and Tags (EE12) go on their own sheets and point at a certificate ID.",
             "Leave a cell blank to leave that cell blank on the form. Signatures, dates, YES/NO answers and test results are never filled.",
             "Type values exactly as they should appear (for example one style of inch mark in line numbers).",
             "Then run the Workpack Filler. It writes filled copies of the blank templates to a separate output folder.",
             "The blank templates are never changed."]
    for i, l in enumerate(lines, 1):
        ws.cell(i, 1, l).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
    ws.column_dimensions["A"].width = 120
    ws = wb.create_sheet("Project")
    for c, h in enumerate(("Field", "Value", "Where it is used"), 1):
        x = ws.cell(1, c, h); x.font = Font(bold=True, color="FFFFFF"); x.fill = head
    for r, (k, label, hint) in enumerate(PROJECT_FIELDS, 2):
        ws.cell(r, 1, label).font = Font(bold=True)
        ws.cell(r, 3, hint).fill = note
        ws.cell(r, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 46; ws.column_dimensions["B"].width = 70; ws.column_dimensions["C"].width = 60
    ws = wb.create_sheet("Certificates")
    for c, (k, label, hint) in enumerate(CERT_COLUMNS, 1):
        x = ws.cell(1, c, label); x.font = Font(bold=True, color="FFFFFF"); x.fill = head
        x.alignment = Alignment(wrap_text=True, vertical="center")
        n = ws.cell(2, c, hint); n.fill = note; n.font = Font(italic=True, size=9); n.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 24
    ws.row_dimensions[2].height = 52
    ws.freeze_panes = "C3"
    dv = DataValidation(type="list", formula1='"AS1,EE12,SC1,SL1,MP1,JI1,SH1,MC1,PL1 A,PL1 B"', allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(dv); dv.add("B3:B200")
    for name, cols in (("Lines", LINE_COLUMNS), ("Joints", JOINT_COLUMNS), ("Tags", TAG_COLUMNS)):
        ws = wb.create_sheet(name)
        for c, (k, label, hint) in enumerate(cols, 1):
            x = ws.cell(1, c, label); x.font = Font(bold=True, color="FFFFFF"); x.fill = head
            n = ws.cell(2, c, hint); n.fill = note; n.font = Font(italic=True, size=9); n.alignment = Alignment(wrap_text=True, vertical="top")
            ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 34
        ws.freeze_panes = "A3"
    wb.save(path)

def read_sheet(path):
    """Read and validate the input workbook. Returns dict(project=..., certs=[...], lines=..., tags=...)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    errs = []
    def val(v):
        if v is None:
            return None
        if isinstance(v, float) and v == int(v):
            v = int(v)
        s = str(v).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        s = "\n".join(x.rstrip() for x in s.split("\n")).strip()
        return s or None
    for need in ("Project", "Certificates"):
        if need not in wb.sheetnames:
            raise FillError("the workbook has no '%s' sheet" % need)
    project = {}
    labels = {label: k for k, label, _ in PROJECT_FIELDS}
    for row in wb["Project"].iter_rows(min_row=2, values_only=True):
        if row and row[0] in labels:
            project[labels[row[0]]] = val(row[1])
    def table(name, cols, first=3):
        if name not in wb.sheetnames:
            return []
        ws = wb[name]
        hdr = {str(c.value).strip(): i for i, c in enumerate(ws[1]) if c.value}
        out = []
        for ri, row in enumerate(ws.iter_rows(min_row=first, values_only=True), first):
            if not any(v not in (None, "") for v in row):
                continue
            rec = {"_row": ri}
            for k, label, _ in cols:
                i = hdr.get(label)
                rec[k] = val(row[i]) if i is not None and i < len(row) else None
            out.append(rec)
        return out
    certs = table("Certificates", CERT_COLUMNS)
    lines = table("Lines", LINE_COLUMNS)
    joints = table("Joints", JOINT_COLUMNS)
    tags = table("Tags", TAG_COLUMNS)
    ids = set()
    for c in certs:
        r = c["_row"]
        if not c["id"]:
            errs.append("Certificates row %d: ID is blank" % r)
        elif c["id"] in ids:
            errs.append("Certificates row %d: duplicate ID '%s'" % (r, c["id"]))
        ids.add(c["id"])
        if not c["form"]:
            errs.append("Certificates row %d: Form is blank" % r)
    by = {c["id"]: c for c in certs}
    for sheet, recs in (("Lines", lines), ("Joints", joints)):
        for rec in recs:
            if rec["cert"] not in by:
                errs.append("%s row %d: certificate '%s' is not on the Certificates sheet" % (sheet, rec["_row"], rec["cert"]))
            elif by[rec["cert"]]["form"] not in ROW_TABLES or ROW_TABLES[by[rec["cert"]]["form"]][4] != sheet:
                errs.append("%s row %d: form %s does not use the %s sheet" % (sheet, rec["_row"], by[rec["cert"]]["form"], sheet))
    for rec in tags:
        if rec["cert"] not in by:
            errs.append("Tags row %d: certificate '%s' is not on the Certificates sheet" % (rec["_row"], rec["cert"]))
        elif by[rec["cert"]]["form"] != "EE12":
            errs.append("Tags row %d: certificate '%s' is not an EE12" % (rec["_row"], rec["cert"]))
    if errs:
        raise FillError("problems in the input workbook:\n  - " + "\n  - ".join(errs))
    return dict(project=project, certs=certs, lines=lines, joints=joints, tags=tags)

# =========================================================================== driver
def values_for(cert, project):
    v = {}
    v["title"] = project.get("title"); v["project_no"] = project.get("project_no")
    v["workpack"] = project.get("workpack"); v["sh1"] = project.get("sh1"); v["mc1"] = project.get("mc1"); v["site"] = project.get("site")
    v["punch_no"] = cert.get("punch_no"); v["discipline"] = cert.get("discipline")
    v["location"] = cert.get("location") or project.get("location")
    v["hdr_location"] = cert.get("location") or project.get("location")
    v["system"] = cert.get("system") or project.get("system")
    v["subsystem"] = cert.get("subsystem") or project.get("subsystem")
    for k in ("equipment", "area", "drawing", "description", "scope", "procedure"):
        v[k] = cert.get(k)
    v["handover_title"] = project.get("handover_title") or project.get("title")
    v["handover_includes"] = project.get("handover_includes")
    v["handover_excludes"] = project.get("handover_excludes")
    v["sh1_number_block"] = project.get("sh1")
    v["mc1_cert_nos"] = project.get("mc1")
    v["mc1_number_block"] = project.get("mc1")
    return v

def inside(path, folder):
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f + os.sep)

def run(input_path, tpl_dir, out_dir, overwrite=False, add_rows=False, spare_rows=None, report=print):
    if inside(out_dir, tpl_dir) or inside(tpl_dir, out_dir):
        raise FillError("the output folder must be separate from the templates folder (the templates are never written to)")
    data = read_sheet(input_path)
    project = data["project"]
    results, audit = [], []
    for cert in data["certs"]:
        form, cid = cert["form"].strip(), cert["id"]
        log = []
        tpl = find_template(tpl_dir, form)
        if not tpl:
            results.append((cid, form, None, "FAILED", "no blank template found for form '%s'" % form))
            continue
        folder = cert.get("folder") or SECTION.get(form, DEFAULT_SECTION)
        name = cert.get("filename") or ("%s %s" % (form, cid))
        out_path = os.path.join(out_dir, folder, re.sub(r'[<>:"/\\|?*]', "_", name) + ".docx")
        if os.path.exists(out_path) and not overwrite:
            results.append((cid, form, out_path, "SKIPPED", "output file already exists (use --overwrite)"))
            continue
        try:
            doc = Doc(tpl)
            vals = values_for(cert, project)
            filled = fill_header(doc, vals, log)
            fill_body(doc, form, vals, log)
            sheet = ROW_TABLES[form][4].lower() if form in ROW_TABLES else "lines"
            rows = [r for r in data[sheet] if r["cert"] == cid]
            fill_rows(doc, form, rows, add_rows, log, spare_rows)
            if form == "EE12":
                tags = [r for r in data["tags"] if r["cert"] == cid]
                fill_ee12_block(doc, cert.get("ee12_description") or project.get("ee12_description"), tags, log)
            elif rows and form not in ROW_TABLES:
                log.append(("WARN", "line rows ignored for form %s" % form))
            if form not in BODY_FIELDS and form not in ("PL1 A", "PL1 B"):
                log.append(("INFO", "form %s: only the header block is filled (body fields are not mapped yet)" % form))
            doc.save(out_path)
            doc.zin.close()
            # prove only intended places changed
            problems = self_check(tpl, out_path, doc, vals, form, rows, cert, project, spare_rows)
            status = "OK" if not problems else "CHECK FAILED"
            note = "; ".join(m for _, m in log) if log else ""
            if problems:
                note = "; ".join(problems)
                os.replace(out_path, out_path + ".REJECTED")
            results.append((cid, form, out_path, status, note))
            for part, what in doc.touched:
                audit.append((cid, form, os.path.relpath(out_path, out_dir), what))
        except FillError as e:
            results.append((cid, form, None, "FAILED", str(e)))
    return results, audit

def self_check(tpl, out_path, doc, vals, form, rows, cert, project, spare_rows=None):
    """Compare template and output cell by cell. Only cells the tool was asked to fill may differ."""
    problems = []
    zt, zo = zipfile.ZipFile(tpl), zipfile.ZipFile(out_path)
    if zt.namelist() != zo.namelist():
        return ["the list of file parts changed"]
    main = main_part_name(zt)
    changed = [n for n in zt.namelist() if zt.read(n) != zo.read(n)]
    for n in changed:
        if not (n == main or re.match(r"word/header\d*\.xml$", n)):
            problems.append("unexpected part changed: %s" % n)
    if zt.read("word/settings.xml") != zo.read("word/settings.xml"):
        problems.append("document protection / settings changed")
    # allowed cells: body fields, row tables, EE12 block; header: any cell that holds a header value
    allowed_body = set()
    tables = None
    for key, (ti, ri, ci), _, slot in BODY_FIELDS.get(form, []):
        allowed_body.add("t%d r%d c%d" % (ti, ri, ci))
    if form in ROW_TABLES:
        ti, first, cols, _, _ = ROW_TABLES[form]
        for r in range(first, first + 60):
            for c in cols:
                allowed_body.add("t%d r%d c%d" % (ti, r, c))
    new_rows_from = None
    if form in ROW_TABLES:
        ti_r = ROW_TABLES[form][0]
        orig_rows = len(top_tables(etree.fromstring(zt.read(main)))[ti_r].findall(q("tr")))
        new_rows_from = (ti_r, orig_rows)
    trim_from = None
    if spare_rows is not None and form in ROW_TABLES:
        ti_, first_, _, _, _ = ROW_TABLES[form]
        trim_from = (ti_, first_ + len(rows) + spare_rows)
    for n in changed:
        a, b = part_cells(etree.fromstring(zt.read(n))), part_cells(etree.fromstring(zo.read(n)))
        for k in set(a) | set(b):
            if a.get(k) == b.get(k):
                continue
            if n == main and new_rows_from and k not in a:
                m2 = re.match(r"t(\d+) r(\d+) c\d+$", k)
                if m2 and int(m2.group(1)) == new_rows_from[0] and int(m2.group(2)) >= new_rows_from[1]:
                    continue          # a row added on request (--add-rows) is a copy of the last template row
            if n == main and trim_from and k not in b:
                m = re.match(r"t(\d+) r(\d+) c\d+$", k)
                if m and int(m.group(1)) == trim_from[0] and int(m.group(2)) >= trim_from[1]:
                    if re.sub(r"\s+", "", a[k]).upper() in ("", "YES/NO"):
                        continue          # a trailing blank template row was removed on request
                    problems.append("a removed row held text at %s" % k)
                    continue
            if n == main:
                ok = k in allowed_body or (form == "EE12" and k.startswith("t1 r0 c0")) or ("t1 r0 c0" in k and form == "EE12")
                if not ok:
                    problems.append("unexpected change in body at %s" % k)
            else:
                # header: the new text must equal one of the values we meant to write
                new = (b.get(k) or "").replace(a.get(k) or "", "", 1).strip()
                if new and not any(new == str(v) for v in vals.values() if v):
                    problems.append("unexpected header text '%s' at %s" % (new[:30], k))
        names = lambda data: sorted((x.get(q("id")), x.get(q("name"))) for x in etree.fromstring(data).iter(q("bookmarkStart")))
        if names(zt.read(n)) != names(zo.read(n)):
            problems.append("bookmarks changed in %s" % n)
    return problems

def write_logs(out_dir, results, audit, project):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "fill-log.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["certificate ID", "form", "output file", "status", "notes"])
        for cid, form, path, status, note in results:
            w.writerow([cid, form, os.path.relpath(path, out_dir) if path else "", status, note])
    with open(os.path.join(out_dir, "fill-audit.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["certificate ID", "form", "output file", "what was filled"])
        w.writerows(audit)

# =========================================================================== command line
def gui_pick():
    """File / folder pickers for people who do not use the command line."""
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    messagebox.showinfo("Workpack filler", "Step 1 of 3: choose the INPUT WORKBOOK (the filled-in input sheet)." + chr(10) + chr(10) + "The blank templates are never changed. Filled copies are written to a separate folder.")
    inp = filedialog.askopenfilename(title="Choose the input workbook", filetypes=[("Excel workbook", "*.xlsx")])
    if not inp:
        root.destroy()
        return None
    tpl = filedialog.askdirectory(title="Step 2 of 3: choose the BLANK TEMPLATES folder (ANS-TI-019)")
    if not tpl:
        root.destroy()
        return None
    out = filedialog.askdirectory(title="Step 3 of 3: choose (or create) the OUTPUT folder for the filled forms")
    if not out:
        root.destroy()
        return None
    validate = messagebox.askyesno("Check afterwards", "Run the validator on the filled forms when finished? (recommended)")
    spare = 4 if messagebox.askyesno("Table rows", "Delete unused blank rows in the line and joint tables, keeping 4 spare rows?" + chr(10) + chr(10) + "Choose No to leave the template's rows exactly as they are.") else None
    root.destroy()
    return inp, tpl, out, validate, spare

def gui_finish(out, results):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        ok = sum(1 for r in results if r[3] == "OK")
        bad = [r for r in results if r[3] != "OK"]
        msg = "%d form(s) written to:" % ok + chr(10) + out
        if bad:
            msg += chr(10) + chr(10) + "%d problem(s):" % len(bad) + chr(10) + chr(10).join("  %s (%s): %s" % (r[0], r[1], r[4][:80]) for r in bad[:6])
        messagebox.showinfo("Workpack filler", msg)
        root.destroy()
        os.startfile(out)
    except Exception:
        pass

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?")
    ap.add_argument("--templates")
    ap.add_argument("--out")
    ap.add_argument("--make-sheet", metavar="PATH")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--add-rows", action="store_true", help="add table rows when there are more line/joint rows than the template has")
    ap.add_argument("--spare-rows", type=int, metavar="N", help="delete unused blank rows in line/joint tables, keeping N spare rows (keeps the form to one page)")
    ap.add_argument("--validate", action="store_true", help="run the workpack validator on the output afterwards")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)
    if a.make_sheet:
        if os.path.exists(a.make_sheet):
            print("Refusing to overwrite an existing file: %s" % a.make_sheet)
            return 2
        make_sheet(a.make_sheet)
        print("Created blank input workbook: %s" % a.make_sheet)
        return 0
    gui = False
    if not a.input:
        picked = gui_pick()
        if not picked:
            print("Cancelled. Nothing was done.")
            return 0
        a.input, a.templates, a.out, a.validate, a.spare_rows = picked
        gui = True
    if not (a.templates and a.out):
        print("Both --templates and --out are needed.")
        return 2
    try:
        results, audit = run(a.input, a.templates, a.out, overwrite=a.overwrite, add_rows=a.add_rows, spare_rows=a.spare_rows)
    except FillError as e:
        print("Stopped: %s" % e)
        return 2
    write_logs(a.out, results, audit, None)
    bad = [r for r in results if r[3] not in ("OK",)]
    print("Workpack filler (templates are never modified)")
    for cid, form, path, status, note in results:
        print("  [%s] %-8s %-24s %s" % (status, form, cid, (os.path.relpath(path, a.out) if path else "") + (("  -- " + note) if note else "")))
    print(chr(10) + "%d form(s) written, %d problem(s). Log: %s" % (sum(1 for r in results if r[3] == "OK"), len(bad), os.path.join(a.out, "fill-log.csv")))
    if a.validate and any(r[3] == "OK" for r in results):
        try:
            import validate_workpack as V
            proj = read_sheet(a.input)["project"]
            vargs = [a.out, "--templates", a.templates, "--out", os.path.join(a.out, "_validation"), "--no-open"]
            for flag, key in (("--ref-sh1", "sh1"), ("--ref-workpack", "workpack"), ("--ref-fcp", "project_no")):
                if proj.get(key):
                    vargs += [flag, proj[key]]
            print(chr(10) + "Running the validator on the filled forms...")
            V.findings.clear()
            vcode = V.main(vargs)
            print("Validation report: %s" % os.path.join(a.out, "_validation", "report.html"))
            if vcode:
                bad.append(("validator", "", None, "ERRORS", "the validator found errors in the filled forms"))
        except ImportError:
            print("validate_workpack.py was not found next to this tool; skipping validation.")
    if gui:
        gui_finish(a.out, results)
    return 1 if bad else 0

if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nSomething went wrong. Please send the text above to whoever supports this tool.")
        code = 3
    sys.exit(code)
