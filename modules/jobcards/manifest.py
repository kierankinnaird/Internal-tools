from pathlib import Path

from core.modules import Module

from .link import JobcardsLink
from .web import create_blueprint


def _register(ctx):
    ctx.services.register("jobcards.link", JobcardsLink(
        ctx.data_dir / "jobcards.sqlite", audit=lambda a, d: ctx.audit("jobcards", a, d)))


MODULE = Module(
    name="jobcards",
    title="Jobcards",
    version="0.1.0",
    create_blueprint=create_blueprint,
    nav=[("Jobcards", "jobcards.index")],
    permissions=["jobcards.view", "jobcards.edit", "jobcards.factor"],
    provides=["jobcards.link"],
    optional=["norms.lookup"],
    migrations_dir=Path(__file__).parent / "migrations",
    register_services=_register,
)
