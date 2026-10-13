from pathlib import Path

from core.modules import Module

from .web import create_blueprint

MODULE = Module(
    name="workpacks",
    title="Workpacks",
    version="0.1.0",
    create_blueprint=create_blueprint,
    nav=[("Workpacks", "workpacks.index")],
    permissions=["workpacks.view", "workpacks.edit", "workpacks.fill"],
    migrations_dir=Path(__file__).parent / "migrations",
)