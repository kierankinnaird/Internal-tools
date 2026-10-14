from __future__ import annotations

import getpass
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .services import Services


class SqliteAudit:
    """Appends audit entries to a local SQLite file (standalone edition).

    The platform edition supplies its own sink with the same `log` signature.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:      # closed when done; "with db" commits (or rolls back)
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit ("
                "id INTEGER PRIMARY KEY, at TEXT NOT NULL, user TEXT NOT NULL, "
                "module TEXT NOT NULL, action TEXT NOT NULL, detail TEXT)"
            )

    def log(self, user: str, module: str, action: str, detail: str = "") -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO audit (at, user, module, action, detail) VALUES (?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), user, module, action, detail),
            )


class Context:
    """What a module may ask of its host."""

    def __init__(self, user_name: Optional[str] = None, audit: Optional[SqliteAudit] = None,
                 permissions: Optional[Iterable[str]] = None, data_dir: Optional[Path] = None,
                 services: Optional[Services] = None):
        self.data_dir = Path(data_dir) if data_dir else Path("userdata")
        self.services = services or Services()
        self._user = user_name
        self._audit = audit
        self._permissions = None if permissions is None else set(permissions)

    def current_user(self) -> str:
        if self._user:
            return self._user
        try:
            return getpass.getuser()
        except Exception:  # pragma: no cover - unusual environments
            return "unknown"

    def can(self, permission: str) -> bool:
        """Standalone: everyone who can open the zip may do everything."""
        return self._permissions is None or permission in self._permissions

    def audit(self, module: str, action: str, detail: str = "") -> None:
        if self._audit is not None:
            self._audit.log(self.current_user(), module, action, detail)