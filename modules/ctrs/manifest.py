from pathlib import Path

from core.modules import Module

from .web import create_blueprint

MODULE = Module(
    name="ctrs",
    title="CTRs",
    version="0.1.0",
    create_blueprint=create_blueprint,
    nav=[("CTRs", "ctrs.index")],
    permissions=["ctrs.view", "ctrs.edit"],
    optional=["jobcards.hours"],
    migrations_dir=Path(__file__).parent / "migrations",
)
