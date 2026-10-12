"""Numbered .sql files per module, applied once each, in order."""
from __future__ import annotations

import sqlite3
from pathlib import Path

def migrate(db_path: Path, module: str, migrations_dir: Path) -> int:
    """Apply any unapplied NNNN_name.sql files. Returns how many were applied."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    applied = 0
    db = sqlite3.connect(db_path)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                   "module TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (module, name))")
        done = {r[0] for r in db.execute("SELECT name FROM schema_migrations WHERE module = ?", (module,))}
        for f in sorted (Path(migrations_dir).glob("*.sql")):
            if f.name in done:
                continue
            db.executescript(f.read_text(encoding="utf-8"))
            db.execute("INSERT INTO schema_migrations (module, name) VALUES (?,?)", (module, f.name))
            db.commit()
            applied += 1
    finally:
        db.close()
    return applied