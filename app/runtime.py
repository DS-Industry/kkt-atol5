"""Process objects shared by HTTP, the print queue, and startup."""
from pathlib import Path

from flask import Flask
from flask_apscheduler import APScheduler

from app.data.db import db

ROOT = Path(__file__).resolve().parents[1]

app = Flask(
    __name__,
    root_path=str(ROOT),
    instance_path=str(ROOT / "instance"),
)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///checks.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SCHEDULER_API_ENABLED"] = True
db.init_app(app)
scheduler = APScheduler()
