from flask import Blueprint
parlays_bp = Blueprint("parlays", __name__)
from app.blueprints.parlays import routes  # noqa: F401
