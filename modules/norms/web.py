from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request

from core.context import Context

from .service import NormsService


def create_blueprint(ctx: Context) -> Blueprint:
    bp = Blueprint("norms", __name__, url_prefix="/norms", template_folder="templates",
                   static_folder="static", static_url_path="/static")
    service = ctx.services.get("norms.lookup") or NormsService()

    def _need_view():
        if not ctx.can("norms.view"):
            abort(403)

    @bp.get("/")
    def index():
        _need_view()
        return render_template("norms/index.html", disciplines=service.disciplines())

    @bp.get("/api/items")
    def api_items():
        _need_view()
        return jsonify(service.items(request.args.get("discipline") or None))

    @bp.get("/api/search")
    def api_search():
        _need_view()
        result = service.search(
            query=request.args.get("q", ""),
            discipline=request.args.get("discipline") or None,
            item_id=request.args.get("item") or None,
            usable_only=request.args.get("all") != "1",
            limit=request.args.get("limit", 200),
        )
        return jsonify({"total": result.total, "shown": len(result.rows), "rows": result.rows})

    @bp.post("/api/copied")
    def api_copied():
        _need_view()
        key = (request.get_json(silent=True) or {}).get("key", "")
        if service.get(key):
            ctx.audit("norms", "key_copied", key)
        return ("", 204)

    return bp