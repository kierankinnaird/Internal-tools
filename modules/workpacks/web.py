from __future__ import annotations

from typing import Dict, List

from flask import Blueprint, abort, redirect, render_template, request, url_for

from core.context import Context

from . import certfields, rowtables
from .fields import CERTIFICATE_FIELDS, ROW_KIND_BY_FORM, WORKPACK_FIELDS
from .forms import form_codes
from .repo import Repo
from .store import TemplateStatus, TemplateStore, default_folder

# How the project details are grouped on the workpack page: (heading, hint, columns).
# Every column in fields.WORKPACK_FIELDS must appear in exactly one group (a test checks it).
GROUPS = [
    ("Identification", "Shown in the header of every form.",
     ["title", "project_no", "workpack_no", "sh1_no", "mc1_no", "site"]),
    ("Defaults for certificates", "Used wherever a certificate leaves its own value blank.",
     ["location", "system", "subsystem"]),
    ("Handover (SH1 and MC1)", "Leave the title blank to use the project title.",
     ["handover_title", "handover_includes", "handover_excludes"]),
    ("EE12", "Used for every EE12 unless a certificate has its own description of tests.",
     ["ee12_description"]),
    ("Workpack master (DM)", "", ["nmc_cchp_no", "revision", "cover_title"]),
    ("CCHP checklist (C1)", "", ["jre", "cchp_title"]),
]
TEXTAREAS = {"handover_includes", "handover_excludes", "ee12_description"}
ROW_NOUN = {"line": "line", "joint": "joint", "tag": "tag"}


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


def rows_text(cert: Dict) -> str:
    """'3 lines', '1 joint', '' for a form that has no table."""
    kind = ROW_KIND_BY_FORM.get(cert["form"])
    if not kind:
        return ""
    n = cert[f"{kind}_count"]
    return f"{n} {ROW_NOUN[kind]}{'' if n == 1 else 's'}"


def create_blueprint(ctx: Context) -> Blueprint:
    bp = Blueprint("workpacks", __name__, url_prefix="/workpacks", template_folder="templates",
                   static_folder="static", static_url_path="/static")
    repo = Repo(ctx.data_dir / "workpacks.sqlite", audit=lambda a, d: ctx.audit("workpacks", a, d))
    store = TemplateStore(default_folder(ctx.data_dir))
    labels = dict(WORKPACK_FIELDS)
    cert_labels = dict(CERTIFICATE_FIELDS)

    def need(perm):
        if not ctx.can(perm):
            abort(403)

    def wp_or_404(wp_id):
        wp = repo.get_workpack(wp_id)
        if not wp:
            abort(404)
        return wp

    def cert_or_404(cert_pk):
        cert = repo.get_certificate(cert_pk)
        if not cert:
            abort(404)
        return cert

    def back(wp_id, error=None, anchor=""):
        return redirect(url_for("workpacks.workpack", wp_id=wp_id, error=error) + anchor)

    def cert_field(cert, column):
        return {"name": column, "label": cert_labels[column], "value": cert[column], "hint": certfields.hint(column),
                "textarea": column in certfields.TEXTAREAS}

    # ---- the list ----------------------------------------------------------------------------
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
            wp_id = repo.create_workpack(request.form, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("workpacks.index", error=str(e)))
        return redirect(url_for("workpacks.workpack", wp_id=wp_id))

    # ---- one workpack ------------------------------------------------------------------------
    @bp.get("/<int:wp_id>")
    def workpack(wp_id):
        need("workpacks.view")
        wp = wp_or_404(wp_id)
        groups = [{"heading": heading, "hint": hint,
                   "fields": [{"name": c, "label": labels[c], "value": wp[c], "textarea": c in TEXTAREAS} for c in cols]}
                  for heading, hint, cols in GROUPS]
        certs = repo.list_certificates(wp_id)
        for c in certs:
            c["rows_text"] = rows_text(c)
        return render_template("workpacks/workpack.html", wp=wp, groups=groups, certs=certs,
                               forms=form_codes(store.folder), error=request.args.get("error"),
                               can_edit=ctx.can("workpacks.edit"))

    @bp.post("/<int:wp_id>")
    def update_workpack(wp_id):
        need("workpacks.edit")
        wp_or_404(wp_id)
        try:
            repo.update_workpack(wp_id, request.form, ctx.current_user())
        except ValueError as e:
            return back(wp_id, str(e))
        return back(wp_id)

    @bp.post("/<int:wp_id>/delete")
    def delete_workpack(wp_id):
        need("workpacks.edit")
        wp_or_404(wp_id)
        repo.delete_workpack(wp_id)
        return redirect(url_for("workpacks.index"))

    # ---- certificates ------------------------------------------------------------------------
    @bp.post("/<int:wp_id>/certificates")
    def add_certificate(wp_id):
        need("workpacks.edit")
        wp_or_404(wp_id)
        data = {"cert_id": request.form.get("cert_id", ""), "form": request.form.get("form", "").strip().upper()}
        try:
            repo.add_certificate(wp_id, data, ctx.current_user())
        except ValueError as e:
            return back(wp_id, str(e), "#certificates")
        return back(wp_id, anchor="#certificates")

    @bp.get("/certificates/<int:cert_pk>")
    def certificate(cert_pk):
        need("workpacks.view")
        cert = cert_or_404(cert_pk)
        wp = wp_or_404(cert["workpack_id"])
        sections = {name: [cert_field(cert, c) for c in cols]
                    for name, cols in certfields.sections(cert["form"]).items()}
        siblings = repo.list_certificates(wp["id"])
        at = next(i for i, c in enumerate(siblings) if c["id"] == cert_pk)
        kind = rowtables.kind_for(cert["form"])
        table = None
        if kind:
            n = len(repo.get_rows(cert_pk, kind))
            table = {"title": rowtables.TITLES[kind], "count": rowtables.count_text(kind, n)}
        return render_template("workpacks/certificate.html", wp=wp, cert=cert, sections=sections, table=table,
                               previous=siblings[at - 1] if at > 0 else None,
                               following=siblings[at + 1] if at + 1 < len(siblings) else None,
                               forms=form_codes(store.folder), error=request.args.get("error"),
                               saved=bool(request.args.get("saved")), can_edit=ctx.can("workpacks.edit"))

    @bp.post("/certificates/<int:cert_pk>")
    def update_certificate(cert_pk):
        need("workpacks.edit")
        cert_or_404(cert_pk)
        data = request.form.to_dict()
        if "form" in data:
            data["form"] = data["form"].strip().upper()
        try:
            repo.update_certificate(cert_pk, data, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("workpacks.certificate", cert_pk=cert_pk, error=str(e)))
        return redirect(url_for("workpacks.certificate", cert_pk=cert_pk, saved=1))

    # ---- table rows (lines, joints, tags) ------------------------------------------------------
    def table_or_redirect(cert_pk):
        """The certificate and its row kind, or None and a redirect when the form has no table."""
        cert = cert_or_404(cert_pk)
        kind = rowtables.kind_for(cert["form"])
        if kind:
            return cert, kind, None
        return cert, None, redirect(url_for("workpacks.certificate", cert_pk=cert_pk,
                                            error=f"The {cert['form']} form has no table rows"))

    @bp.get("/certificates/<int:cert_pk>/rows")
    def rows(cert_pk):
        need("workpacks.view")
        cert, kind, refused = table_or_redirect(cert_pk)
        if refused:
            return refused
        can_edit = ctx.can("workpacks.edit")
        return render_template("workpacks/rows.html", wp=wp_or_404(cert["workpack_id"]), cert=cert, kind=kind,
                               title=rowtables.TITLES[kind], note=rowtables.NOTES.get(kind, ""),
                               columns=rowtables.columns(kind), rows=repo.get_rows(cert_pk, kind),
                               blank=rowtables.BLANK_ROWS if can_edit else 0, can_edit=can_edit,
                               saved=request.args.get("saved", type=int), error=request.args.get("error"),
                               count_text=rowtables.count_text)

    @bp.post("/certificates/<int:cert_pk>/rows")
    def save_rows(cert_pk):
        need("workpacks.edit")
        cert, kind, refused = table_or_redirect(cert_pk)
        if refused:
            return refused
        try:
            names = [c["name"] for c in rowtables.columns(kind)]
            saved = repo.replace_rows(cert_pk, kind, rowtables.parse_rows(request.form, names), ctx.current_user())
        except ValueError as e:
            return redirect(url_for("workpacks.rows", cert_pk=cert_pk, error=str(e)))
        return redirect(url_for("workpacks.rows", cert_pk=cert_pk, saved=saved))

    @bp.post("/certificates/<int:cert_pk>/duplicate")
    def duplicate_certificate(cert_pk):
        need("workpacks.edit")
        cert = cert_or_404(cert_pk)
        try:
            repo.duplicate_certificate(cert_pk, request.form.get("cert_id", ""), ctx.current_user())
        except ValueError as e:
            return back(cert["workpack_id"], str(e), "#certificates")
        return back(cert["workpack_id"], anchor="#certificates")

    @bp.post("/certificates/<int:cert_pk>/delete")
    def delete_certificate(cert_pk):
        need("workpacks.edit")
        cert = cert_or_404(cert_pk)
        repo.delete_certificate(cert_pk, ctx.current_user())
        return back(cert["workpack_id"], anchor="#certificates")

    return bp