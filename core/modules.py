from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from flask import Blueprint, Flask

from .context import Context
from .migrations import migrate


@dataclass
class Module:
    name: str                       # short id, e.g. "norms"
    title: str                      # shown to people
    version: str
    create_blueprint: Callable[[Context], Blueprint]
    nav: List[Tuple[str, str]] = field(default_factory=list)   # (label, endpoint)
    permissions: List[str] = field(default_factory=list)       # what the module defines
    provides: List[str] = field(default_factory=list)          # services it registers
    requires: List[str] = field(default_factory=list)          # services it cannot work without
    optional: List[str] = field(default_factory=list)          # services it uses when present
    migrations_dir: Optional[Path] = None                      # numbered .sql files for its own data
    register_services: Optional[Callable[[Context], None]] = None


class MissingRequirement(RuntimeError):
    pass


def mount(app: Flask, module: Module, ctx: Context) -> None:
    """Attach a module to a host app: services, own data, routes, menu."""
    if module.register_services:
        module.register_services(ctx)
    missing = [r for r in module.requires if not ctx.services.has(r)]
    if missing:
        raise MissingRequirement(f"{module.title} needs {', '.join(missing)}, which is not installed")
    if module.migrations_dir:
        migrate(ctx.data_dir / f"{module.name}.sqlite", module.name, module.migrations_dir)
    app.register_blueprint(module.create_blueprint(ctx))
    nav = app.config.setdefault("NAV", [])
    for label, endpoint in module.nav:
        nav.append({"label": label, "endpoint": endpoint})
    app.config.setdefault("MODULES", []).append(module)