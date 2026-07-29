import logging
import os

from flask import Flask
from flask_migrate import Migrate

from webapp import config as cfg
from webapp import database
from webapp.database import db, RtspCamera
from webapp.rtsp import _start_rtsp_threads, _stop_all_rtsp_threads
from webapp.routes.web import web_bp
from webapp.routes.api import api_bp


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "postgresql://moesio:moesio@localhost:5432/plates"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()))

    db.init_app(app)
    Migrate(app, db, directory="alembic")

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def _seed_config():
        if not getattr(app, "_config_seeded", False):
            try:
                session = database.get_session()
                cfg.seed(session)
                cameras = session.query(RtspCamera).filter_by(enabled=True).all()
                session.close()
                if cameras:
                    _start_rtsp_threads(cameras)
                else:
                    _stop_all_rtsp_threads()
            except Exception:
                pass
            app._config_seeded = True

    _seed_config()

    return app
