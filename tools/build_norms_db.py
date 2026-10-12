"""Rebuild modules/norms/data/norms.sqlite from the flattened Norms_Lookup.xlsx.

Developer step only (needs openpyxl). People who just run the tool never need this.
Usage:  python tools/build_norms_db.py path/to/Norms_Lookup.xlsx
"""
import sqlite3
import sys
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parent.parent / "modules" / "norms" / "data" / "norms.sqlite"


def main(xlsx: str) -> None:
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = []
    for i, r in enumerate(wb["Lookup"].iter_rows(min_row=2, values_only=True)):
        if r[0] is None:
            continue
        key, disc, tno, _table, ino, item, _mat, _r2, _r3, rdesc, uom, cdesc, hrs, src, status = r[:15]
        item_text = str(item or "").strip()
        row_desc, col_desc = str(rdesc or "").strip(), str(cdesc or "").strip()
        rows.append((
            str(key), str(disc), str(tno), str(ino), f"{tno}-{ino}", item_text, row_desc, col_desc,
            str(uom or "").strip(), float(hrs) if isinstance(hrs, (int, float)) else 0.0,
            str(status or "").strip(), str(src or ""),
            item_text.lower(), " ".join([str(key), row_desc, col_desc, str(uom or "")]).lower(), i,
        ))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    db = sqlite3.connect(OUT)
    db.execute(
        "CREATE TABLE norms (key TEXT PRIMARY KEY, discipline TEXT, table_no TEXT, item_no TEXT, item_id TEXT, "
        "item TEXT, row_desc TEXT, col_desc TEXT, uom TEXT, hours REAL, status TEXT, source_cell TEXT, "
        "item_hay TEXT, line_hay TEXT, ord INTEGER)"
    )
    db.executemany("INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.execute("CREATE INDEX norms_disc ON norms(discipline)")
    db.execute("CREATE INDEX norms_item ON norms(item_id)")
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"{len(rows)} norm lines written to {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])