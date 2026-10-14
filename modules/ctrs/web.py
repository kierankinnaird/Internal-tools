from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for

from core.context import Context

from . import calc, export
from .constants import FLAGS, HEADER_FIELDS, PAYMENT_TERMS
from .repo import Repo

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def create_blueprint(ctx: Context) -> Blueprint:
    bp = Blueprint("ctrs", __name__, url_prefix="/ctrs", template_folder="templates",
                   static_folder="static", static_url_path="/static")
    repo = Repo(ctx.data_dir / "ctrs.sqlite", audit=lambda a, d: ctx.audit("ctrs", a, d))
    bp.add_app_template_filter(lambda v: calc.tidy(v), "ctr_hours")
    bp.add_app_template_filter(lambda v: f"£{float(v or 0):,.2f}", "ctr_gbp")

    def hours_service():
        return ctx.services.get("jobcards.hours")

    def need(perm):
        if not ctx.can(perm):
            abort(403)

    def ctr_or_404(ctr_id):
        ctr = repo.get_ctr(ctr_id)
        if not ctr:
            abort(404)
        return ctr

    @bp.get("/")
    def index():
        need("ctrs.view")
        return render_template("ctrs/index.html", ctrs=repo.list_ctrs(), error=request.args.get("error"),
                               can_edit=ctx.can("ctrs.edit"))

    @bp.post("/")
    def create():
        need("ctrs.edit")
        try:
            ctr_id = repo.create_ctr(request.form, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("ctrs.index", error=str(e)))
        return redirect(url_for("ctrs.editor", ctr_id=ctr_id))

    @bp.get("/<int:ctr_id>")
    def editor(ctr_id):
        need("ctrs.view")
        ctr = ctr_or_404(ctr_id)
        service = hours_service()
        state = {"lines": ctr["lines"], "resources": ctr["resources"], "additions": ctr["additions"],
                 "computed": calc.compute(ctr), "flags": FLAGS}
        return render_template("ctrs/editor.html", ctr=ctr, state=state, header_fields=HEADER_FIELDS,
                               terms=PAYMENT_TERMS, can_edit=ctx.can("ctrs.edit"),
                               snapshots=service.snapshots() if service else None,
                               error=request.args.get("error"), imported=request.args.get("imported"))

    @bp.post("/<int:ctr_id>/save")
    def save(ctr_id):
        need("ctrs.edit")
        ctr_or_404(ctr_id)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Send the CTR as JSON"}), 400
        try:
            ctr = repo.save_ctr(ctr_id, data, ctx.current_user())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "updated_at": ctr["updated_at"], "updated_by": ctr["updated_by"],
                        "lines": ctr["lines"], "resources": ctr["resources"], "additions": ctr["additions"],
                        "computed": calc.compute(ctr)})

    @bp.post("/<int:ctr_id>/preview")
    def preview(ctr_id):
        """Worked out from what is on the page, saving nothing, so the page never does arithmetic of its own."""
        need("ctrs.view")
        ctr_or_404(ctr_id)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Send the CTR as JSON"}), 400
        try:
            return jsonify({"ok": True, "computed": repo.preview(ctr_id, data)})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.post("/<int:ctr_id>/import-hours")
    def import_hours(ctr_id):
        need("ctrs.edit")
        ctr_or_404(ctr_id)
        service = hours_service()
        try:
            if service is None:
                raise ValueError("The jobcards module is not installed, so there are no snapshots to import")
            try:
                snapshot = service.snapshot(int(request.form.get("snapshot_id", "")))
            except (TypeError, ValueError):
                raise ValueError("Choose a snapshot to import") from None
            count = repo.import_snapshot(ctr_id, snapshot, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("ctrs.editor", ctr_id=ctr_id, error=str(e)))
        return redirect(url_for("ctrs.editor", ctr_id=ctr_id, imported=count) + "#scope")

    @bp.post("/<int:ctr_id>/duplicate")
    def duplicate(ctr_id):
        need("ctrs.edit")
        ctr_or_404(ctr_id)
        return redirect(url_for("ctrs.editor", ctr_id=repo.duplicate_ctr(ctr_id, ctx.current_user())))

    @bp.post("/<int:ctr_id>/delete")
    def delete(ctr_id):
        need("ctrs.edit")
        ctr_or_404(ctr_id)
        repo.delete_ctr(ctr_id)
        return redirect(url_for("ctrs.index"))

    @bp.get("/<int:ctr_id>/export.xlsx")
    def export_xlsx(ctr_id):
        need("ctrs.view")
        ctr = ctr_or_404(ctr_id)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ctr.xlsx"
            export.write_ctr(path, ctr)
            data = path.read_bytes()
        repo.audit("ctr_downloaded", ctr["title"])
        name = _UNSAFE_NAME.sub("", f"{ctr['ctr_no'] + ' ' if ctr['ctr_no'] else ''}{ctr['title']}").strip() or "CTR"
        return send_file(io.BytesIO(data), mimetype=XLSX, as_attachment=True, download_name=f"{name}.xlsx")

    return bp
