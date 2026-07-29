from flask import Blueprint, render_template
from sqlalchemy import text

from webapp.database import db

web_bp = Blueprint("web", __name__)


@web_bp.route("/")
def index():
    return render_template("index.html")


@web_bp.route("/admin/cameras")
def admin_cameras():
    return render_template("admin_cameras.html")


@web_bp.route("/admin/config")
def admin_config():
    return render_template("admin_config.html")


@web_bp.route("/admin/detections")
def admin_detections():
    return render_template("detections.html")


@web_bp.route("/health")
def health():
    status = {"status": "ok"}
    code = 200
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        status["status"] = "error"
        status["db"] = "unreachable"
        code = 503
    return status, code
