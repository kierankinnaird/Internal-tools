"""Standalone host: no login, data kept in ./userdata next to the app.

Which modules load is decided by enabled_modules.txt (one name per line), so a zip is just a different list.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterable, Optional

from flask import Flask, redirect, url_for

from core.context import Context, SqliteAudit
from core.modules import mount

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["norms", "jobcards"]   # menu order and load order (providers before users)


def read_enabled(path: Optional[Path] = None) -> list:
    path = Path(path or ROOT / "enabled_modules.txt")
    if not path.exists():
        return [m for m in ORDER if (ROOT / "modules" / m).is_dir()]
    names = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    return sorted(names, key=lambda n: ORDER.index(n) if n in ORDER else len(ORDER))


def create_app(userdata: Optional[Path] = None, user_name: Optional[str] = None,
               modules: Optional[Iterable[str]] = None) -> Flask:
    userdata = Path(userdata or ROOT / "userdata")
    names = list(modules) if modules is not None else read_enabled()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    ctx = Context(user_name=user_name, audit=SqliteAudit(userdata / "audit.sqlite"), data_dir=userdata)
    app.config["CTX"] = ctx
    for name in names:
        mount(app, importlib.import_module(f"modules.{name}").MODULE, ctx)

    @app.get("/")
    def home():
        return redirect(url_for(app.config["NAV"][0]["endpoint"]))

    @app.context_processor
    def inject():
        return {"nav": app.config["NAV"], "user": ctx.current_user(), "edition": "Standalone"}

    return app