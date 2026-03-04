from datetime import datetime, timezone
from app.extensions import db


class Boxscore(db.Model):
    __tablename__ = "boxscores"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=False, unique=True, index=True)
    # Store full raw API response for complete flexibility
    raw_data = db.Column(db.JSON, nullable=True)
    home_q1 = db.Column(db.Integer, nullable=True)
    home_q2 = db.Column(db.Integer, nullable=True)
    home_q3 = db.Column(db.Integer, nullable=True)
    home_q4 = db.Column(db.Integer, nullable=True)
    home_ot = db.Column(db.Integer, nullable=True)
    away_q1 = db.Column(db.Integer, nullable=True)
    away_q2 = db.Column(db.Integer, nullable=True)
    away_q3 = db.Column(db.Integer, nullable=True)
    away_q4 = db.Column(db.Integer, nullable=True)
    away_ot = db.Column(db.Integer, nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    game = db.relationship("Game", back_populates="boxscore")
