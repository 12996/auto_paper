from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS

from api.papers import papers_bp
from api.search import search_bp
from api.files import files_bp
from api.queue import queue_bp

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)  # 允许前端跨域访问

    app.register_blueprint(papers_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(queue_bp)

    # ── 托管前端静态文件 ──────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(FRONTEND_DIR, filename)

    return app
