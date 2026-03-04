from flask import Blueprint
stats_bp = Blueprint("stats", __name__)
from app.blueprints.stats import routes  # noqa: F401
