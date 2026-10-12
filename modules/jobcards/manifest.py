from pathlib import Path

from core.modules import Module

from .web import create_blueprint

MODULE = Module(
    name="jobcards",
    title="Jobcards",
    version="0.1.0",
    create_blueprint=create_blueprint,
    nav=[("Jobcards", "jobcards.index")],
    permissions=["jobcards.view", "jobcards.edit", "jobcards.factor"],
    optional=["norms.lookup"],
    migrations_dir=Path(__file__).parent / "migrations",
)