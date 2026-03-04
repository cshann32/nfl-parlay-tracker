from flask import Blueprint
schedules_bp = Blueprint("schedules", __name__)
from app.blueprints.schedules import routes  # noqa: F401
