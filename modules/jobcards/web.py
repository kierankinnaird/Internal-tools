from __future__ import annotations

import csv
import io

from flask import (Blueprint, Response, abort, jsonify, redirect, render_template, request, url_for)

from core.context import Context

from . import calc
from .constants import FLAG_GROUPS, TRADES
from .repo import Repo


def create_blueprint(ctx: Context) -> Blueprint:
    bp = Blueprint("jobcards", __name__, url_prefix="/jobcards", template_folder="templates",
                   static_folder="static", static_url_path="/static")
    repo = Repo(ctx.data_dir / "jobcards.sqlite", audit=lambda a, d: ctx.audit("jobcards", a, d))

    def norms():
        return ctx.services.get("norms.lookup")

    def need(perm):
        if not ctx.can(perm):
            abort(403)

    def wp_or_404(wp_id):
        wp = repo.get_workpack(wp_id)
        if not wp:
            abort(404)
        return wp

    def jc_or_404(jc_id):
        jc = repo.get_jobcard(jc_id)
        if not jc:
            abort(404)
        return jc

    @bp.get("/")
    def index():
        need("jobcards.view")
        return render_template("jobcards/index.html", workpacks=repo.list_workpacks(), error=request.args.get("error"))

    @bp.post("/workpacks")
    def create_workpack():
        need("jobcards.edit")
        try:
            wp_id = repo.create_workpack(request.form, ctx.current_user())
        except ValueError as e:
            return redirect(url_for("jobcards.index", error=str(e)))
        return redirect(url_for("jobcards.workpack", wp_id=wp_id))

    @bp.get("/workpacks/<int:wp_id>")
    def workpack(wp_id):
        need("jobcards.view")
        wp = wp_or_404(wp_id)
        jcs = repo.list_jobcards(wp_id)
        return render_template("jobcards/workpack.html", wp=wp, jobcards=jcs, trades=TRADES,
                               rollup=calc.rollup(jcs), snapshots=repo.list_snapshots(wp_id))

    @bp.post("/workpacks/<int:wp_id>")
    def update_workpack(wp_id):
        need("jobcards.edit")
        wp_or_404(wp_id)
        repo.update_workpack(wp_id, request.form)
        return redirect(url_for("jobcards.workpack", wp_id=wp_id))

    @bp.post("/workpacks/<int:wp_id>/delete")
    def delete_workpack(wp_id):
        need("jobcards.edit")
        wp_or_404(wp_id)
        repo.delete_workpack(wp_id)
        return redirect(url_for("jobcards.index"))

    @bp.post("/workpacks/<int:wp_id>/jobcards")
    def create_jobcard(wp_id):
        need("jobcards.edit")
        wp_or_404(wp_id)
        trade = request.form.get("trade", "")
        jc_id = repo.create_jobcard(wp_id, ctx.current_user(), trade if trade in TRADES else "")
        return redirect(url_for("jobcards.editor", jc_id=jc_id))

    @bp.post("/workpacks/<int:wp_id>/snapshots")
    def create_snapshot(wp_id):
        need("jobcards.edit")
        wp_or_404(wp_id)
        repo.create_snapshot(wp_id, request.form.get("label", ""), ctx.current_user())
        return redirect(url_for("jobcards.workpack", wp_id=wp_id) + "#snapshots")

    @bp.get("/workpacks/<int:wp_id>/rollup.csv")
    def rollup_csv(wp_id):
        need("jobcards.view")
        wp = wp_or_404(wp_id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Workpack", "Trade", "Library hours", "Manual hours", "Total hours"])
        for r in repo.rollup(wp_id):
            w.writerow([wp["number"], r["trade"], round(r["library"], 2), round(r["manual"], 2), round(r["total"], 2)])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{wp["number"]}-hours-by-trade.csv"'})

    @bp.get("/cards/<int:jc_id>")
    def editor(jc_id):
        need("jobcards.view")
        jc = jc_or_404(jc_id)
        return render_template("jobcards/editor.html", jc=jc, wp=repo.get_workpack(jc["workpack_id"]), trades=TRADES,
                               flag_groups=FLAG_GROUPS, has_norms=norms() is not None,
                               can_edit=ctx.can("jobcards.edit"), can_factor=ctx.can("jobcards.factor"))

    @bp.post("/cards/<int:jc_id>/save")
    def save(jc_id):
        need("jobcards.edit")
        old = jc_or_404(jc_id)
        data = request.get_json(silent=True) or {}
        if not ctx.can("jobcards.factor"):      # without the factor permission, factors stay as they were
            prev = {t["id"]: t for t in old["tasks"]}
            for t in data.get("tasks", []):
                p = prev.get(t.get("id"))
                t["factor"], t["factor_reason"] = (p["factor"], p["factor_reason"]) if p else (1, "")
        jc = repo.save_jobcard(jc_id, data, ctx.current_user())
        return jsonify(_view(jc))

    @bp.post("/cards/<int:jc_id>/duplicate")
    def duplicate(jc_id):
        need("jobcards.edit")
        jc_or_404(jc_id)
        return redirect(url_for("jobcards.editor", jc_id=repo.duplicate_jobcard(jc_id, ctx.current_user())))

    @bp.post("/cards/<int:jc_id>/delete")
    def delete(jc_id):
        need("jobcards.edit")
        jc = jc_or_404(jc_id)
        repo.delete_jobcard(jc_id)
        return redirect(url_for("jobcards.workpack", wp_id=jc["workpack_id"]))

    @bp.get("/cards/<int:jc_id>/print")
    def print_view(jc_id):
        need("jobcards.view")
        jc = jc_or_404(jc_id)
        for t in jc["tasks"]:
            t["hours"] = calc.line_hours(t["qty"], t["norm_hours"], t["factor"])
        return render_template("jobcards/print.html", jc=jc, wp=repo.get_workpack(jc["workpack_id"]),
                               flag_groups=FLAG_GROUPS)

    # ---- norm picker: only works when the norms module is installed -------------------------------
    @bp.get("/api/norm-disciplines")
    def norm_disciplines():
        need("jobcards.view")
        n = norms()
        return jsonify({"available": n is not None, "disciplines": n.disciplines() if n else []})

    @bp.get("/api/norm-search")
    def norm_search():
        need("jobcards.view")
        n = norms()
        if n is None:
            return jsonify({"available": False, "total": 0, "rows": []})
        r = n.search(query=request.args.get("q", ""), discipline=request.args.get("discipline") or None,
                     usable_only=True, limit=60)
        return jsonify({"available": True, "total": r.total, "rows": r.rows})

    @bp.get("/api/norm-suggest")
    def norm_suggest():
        """Norms that might fit what is being typed. Advisory only: nothing is applied unless the user clicks."""
        need("jobcards.view")
        n = norms()
        if n is None or not hasattr(n, "suggest"):
            return jsonify({"available": False, "rows": []})
        r = n.suggest(request.args.get("q", ""), limit=5)
        return jsonify({"available": True, "rows": r.rows})

    return bp


def _view(jc):
    for t in jc["tasks"]:
        t["hours"] = calc.line_hours(t["qty"], t["norm_hours"], t["factor"])
        t["warnings"] = calc.warnings(t)
    return jc