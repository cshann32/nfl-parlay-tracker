from datetime import datetime, timezone
from app.extensions import db


class Draft(db.Model):
    __tablename__ = "drafts"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    round = db.Column(db.Integer, nullable=True)
    pick = db.Column(db.Integer, nullable=True)
    overall_pick = db.Column(db.Integer, nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    player_name = db.Column(db.String(150), nullable=True)   # Name at draft time
    position = db.Column(db.String(20), nullable=True)
    college = db.Column(db.String(150), nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
