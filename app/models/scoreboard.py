from datetime import datetime, timezone
from app.extensions import db


class Scoreboard(db.Model):
    __tablename__ = "scoreboards"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=False, unique=True, index=True)
    period = db.Column(db.Integer, nullable=True)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    time_remaining = db.Column(db.String(20), nullable=True)
    raw_data = db.Column(db.JSON, nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    game = db.relationship("Game", back_populates="scoreboard_entries")
