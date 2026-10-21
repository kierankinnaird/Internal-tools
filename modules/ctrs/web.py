from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, render_template, request, send_file, url_for

from core.context import Context

from . import calc, export
from .constants import (DISCIPLINE_TRADES, DISCIPLINES, ESTIMATE_FIELDS, FLAGS, HEADER_FIELDS, PAYMENT_TERMS,
                        SHARED_FIELDS)
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

    def estimate_or_404(estimate_id):
        estimate = repo.get_estimate(estimate_id)
        if not estimate:
            abort(404)
        return estimate

    # ---- hours from the jobcards, filled in by the workbook's link ---------------------------------
    def workpacks_with_snapshots():
        """The jobcards workpacks that have a snapshot to take hours from, or None when the jobcards module is not installed."""
        service = hours_service()
        if service is None:
            return None
        seen = {}
        for snap in service.snapshots():
            seen.setdefault(snap["workpack_number"], snap["workpack_title"])
        return [{"number": n, "title": t} for n, t in seen.items()]

    def chosen_workpack(form, current=""):
        """The jobcards workpack the form picks (blank for none). Refused if it has no snapshot to use, unless it is the one
        already set. Without the jobcards module there is nothing to pick, so the current choice stands."""
        offered = workpacks_with_snapshots()
        if offered is None:
            return current
        number = (form.get("jobcards_workpack", current) or "").strip()
        if number and number != current and number not in {w["number"] for w in offered}:
            raise ValueError(f"There is no snapshot of a jobcards workpack numbered {number} to take hours from")
        return number

    def auto_trades(title):
        """The trades a CTR with this title takes from the jobcards by itself (Piping takes P/Fitter), else None."""
        for name, trades in DISCIPLINE_TRADES.items():
            if name.casefold() == (title or "").strip().casefold():
                return trades
        return None

    def fill_from_jobcards(estimate, only_ctr=None):
        """Bring each matching CTR's trades in from the newest snapshot of the workbook's jobcards workpack. Returns
        (lines brought in, sheets filled, a message about anything that could not be done)."""
        service, number = hours_service(), estimate.get("jobcards_workpack")
        if service is None or not number:
            return 0, 0, ""
        snaps = [s for s in service.snapshots() if s["workpack_number"] == number]
        if not snaps:
            return 0, 0, (f"No snapshot of jobcards workpack {number} has been taken yet. Take one on the workpack's page in "
                          "Jobcards, then press Update hours from jobcards.")
        snapshot = service.snapshot(snaps[0]["id"])
        lines = sheets = 0
        problems = []
        for ctr in estimate["ctrs"]:
            trades = auto_trades(ctr["title"])
            if not trades or (only_ctr is not None and ctr["id"] != only_ctr):
                continue
            try:
                lines += repo.import_snapshot(ctr["id"], snapshot, ctx.current_user(), only=trades, with_resources=True)
                sheets += 1
            except ValueError as e:
                problems.append(f"{ctr['title']}: {e}.")
        return lines, sheets, " ".join(problems)

    # ---- the workbooks (estimates) ---------------------------------------------------------------
    @bp.get("/")
    def index():
        need("ctrs.view")
        return render_template("ctrs/index.html", estimates=repo.list_estimates(), error=request.args.get("error"),
                               can_edit=ctx.can("ctrs.edit"), disciplines=DISCIPLINES, workpacks=workpacks_with_snapshots(),
                               auto=DISCIPLINE_TRADES)

    @bp.post("/")
    def create():
        need("ctrs.edit")
        try:
            data = {**request.form.to_dict(), "jobcards_workpack": chosen_workpack(request.form)}
            estimate_id = repo.create_estimate(data, ctx.current_user(), request.form.getlist("disciplines"))
        except ValueError as e:
            return redirect(url_for("ctrs.index", error=str(e)))
        _, sheets, problem = fill_from_jobcards(repo.get_estimate(estimate_id))
        return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, hours=sheets or None, error=problem or None))

    @bp.get("/estimates/<int:estimate_id>")
    def estimate(estimate_id):
        need("ctrs.view")
        return render_template("ctrs/estimate.html", estimate=estimate_or_404(estimate_id), fields=ESTIMATE_FIELDS,
                               disciplines=DISCIPLINES, error=request.args.get("error"), saved=bool(request.args.get("saved")),
                               hours=request.args.get("hours", type=int), workpacks=workpacks_with_snapshots(),
                               auto=DISCIPLINE_TRADES, can_edit=ctx.can("ctrs.edit"))

    @bp.post("/estimates/<int:estimate_id>")
    def save_estimate(estimate_id):
        need("ctrs.edit")
        before = estimate_or_404(estimate_id)
        try:
            data = {**request.form.to_dict(), "jobcards_workpack": chosen_workpack(request.form, before["jobcards_workpack"])}
            estimate = repo.save_estimate(estimate_id, data, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, error=str(e)))
        sheets = problem = None
        if estimate["jobcards_workpack"] and estimate["jobcards_workpack"] != before["jobcards_workpack"]:
            _, sheets, problem = fill_from_jobcards(estimate)               # a newly chosen workpack fills the sheets at once
        return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, saved=1, hours=sheets or None, error=problem or None))

    @bp.post("/estimates/<int:estimate_id>/update-hours")
    def update_hours(estimate_id):
        need("ctrs.edit")
        estimate = estimate_or_404(estimate_id)
        if not estimate["jobcards_workpack"]:
            return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, error="Choose a jobcards workpack first"))
        _, sheets, problem = fill_from_jobcards(estimate)
        if not sheets and not problem:
            problem = "No sheet here takes its hours from the jobcards by itself (" + ", ".join(
                f"{d} takes {', '.join(t)}" for d, t in DISCIPLINE_TRADES.items()) + ")."
        return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, hours=sheets or None, error=problem or None))

    @bp.post("/estimates/<int:estimate_id>/ctrs")
    def add_ctr(estimate_id):
        need("ctrs.edit")
        estimate_or_404(estimate_id)
        try:
            ctr_id = repo.create_ctr(request.form, ctx.current_user(), estimate_id=estimate_id)
        except ValueError as e:
            return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, error=str(e)))
        lines, _, problem = fill_from_jobcards(repo.get_estimate(estimate_id), only_ctr=ctr_id)
        return redirect(url_for("ctrs.editor", ctr_id=ctr_id, imported=lines or None, error=problem or None))

    @bp.post("/estimates/<int:estimate_id>/delete")
    def delete_estimate(estimate_id):
        need("ctrs.edit")
        estimate_or_404(estimate_id)
        repo.delete_estimate(estimate_id)
        return redirect(url_for("ctrs.index"))

    @bp.get("/estimates/<int:estimate_id>/export.xlsx")
    def export_workbook(estimate_id):
        need("ctrs.view")
        estimate = estimate_or_404(estimate_id)
        if not estimate["ctrs"]:
            return redirect(url_for("ctrs.estimate", estimate_id=estimate_id, error="Add a CTR before downloading the workbook"))
        ctrs = [repo.get_ctr(c["id"]) for c in estimate["ctrs"]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "estimate.xlsx"
            export.write_workbook(path, estimate, ctrs)
            data = path.read_bytes()
        repo.audit("estimate_downloaded", estimate["title"])
        name = " ".join(_UNSAFE_NAME.sub("", estimate["title"]).split()) or "CTRs"
        return send_file(io.BytesIO(data), mimetype=XLSX, as_attachment=True, download_name=f"{name}.xlsx")

    # ---- one CTR ---------------------------------------------------------------------------------
    @bp.get("/<int:ctr_id>")
    def editor(ctr_id):
        need("ctrs.view")
        ctr = ctr_or_404(ctr_id)
        service = hours_service()
        state = {"lines": ctr["lines"], "resources": ctr["resources"], "additions": ctr["additions"],
                 "computed": calc.compute(ctr), "flags": FLAGS}
        return render_template("ctrs/editor.html", ctr=ctr, state=state, header_fields=HEADER_FIELDS,
                               estimate=repo.get_estimate(ctr["estimate_id"], with_ctrs=False), shared=SHARED_FIELDS,
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
        ctr = ctr_or_404(ctr_id)
        repo.delete_ctr(ctr_id)
        return redirect(url_for("ctrs.estimate", estimate_id=ctr["estimate_id"]))

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
