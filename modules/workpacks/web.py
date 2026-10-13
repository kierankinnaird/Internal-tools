from __future__ import annotations

from typing import Dict, List

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core.context import Context

from .repo import Repo
from .store import TemplateStatus, TemplateStore, default_folder


def template_banner(status: TemplateStatus) -> Dict:
    """What to tell people about the blank templates: a level (ok / warn), a headline and any detail lines."""
    if not status.present:
        return {"level": "warn", "headline": "The blank Apache templates are not installed",
                "details": [f"Looked in {status.folder}. Workpacks can be written up, but no forms can be filled "
                            "until the templates pack is installed there."]}
    details: List[str] = []
    if status.differs:
        details.append("Different from the templates pack: " + ", ".join(status.differs))
    if status.missing:
        details.append("Missing from the folder: " + ", ".join(status.missing))
    if status.unlisted:
        details.append("Not in the pack's manifest (for example a newer revision): " + ", ".join(status.unlisted))
    if not status.manifest_found:
        return {"level": "warn", "headline": f"{status.docx_count} templates found, but there is no MANIFEST.csv",
                "details": ["Without the manifest the template versions cannot be checked."]}
    if status.differs or status.missing:
        return {"level": "warn", "headline": "The templates folder does not match the templates pack",
                "details": details}
    return {"level": "ok", "headline": f"{status.docx_count} templates installed, all matching the pack",
            "details": details}


def create_blueprint(ctx: Context) -> Blueprint:
    bp = Blueprint("workpacks", __name__, url_prefix="/workpacks", template_folder="templates",
                   static_folder="static", static_url_path="/static")
    repo = Repo(ctx.data_dir / "workpacks.sqlite", audit=lambda a, d: ctx.audit("workpacks", a, d))
    store = TemplateStore(default_folder(ctx.data_dir))

    def need(perm):
        if not ctx.can(perm):
            abort(403)

    @bp.get("/")
    def index():
        need("workpacks.view")
        return render_template("workpacks/index.html", workpacks=repo.list_workpacks(),
                               banner=template_banner(store.status()), error=request.args.get("error"),
                               can_edit=ctx.can("workpacks.edit"))

    @bp.post("/")
    def create():
        need("workpacks.edit")
        try:
            repo.create_workpack(request.form, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("workpacks.index", error=str(e)))
        return redirect(url_for("workpacks.index"))

    return bp