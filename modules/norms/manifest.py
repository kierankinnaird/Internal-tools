from core.modules import Module

from .service import NormsService
from .web import create_blueprint


def _register(ctx):
    ctx.services.register("norms.lookup", NormsService())


MODULE = Module(
    name="norms",
    title="Norms library",
    version="0.1.0",
    create_blueprint=create_blueprint,
    nav=[("Norms", "norms.index")],
    permissions=["norms.view"],
    provides=["norms.lookup"],
    register_services=_register,
)