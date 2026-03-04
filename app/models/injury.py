from datetime import datetime, timezone
from app.extensions import db


class Injury(db.Model):
    __tablename__ = "injuries"

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    injury_type = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), nullable=True)          # Out / Doubtful / Questionable / IR
    practice_status = db.Column(db.String(50), nullable=True) # DNP / Limited / Full
    description = db.Column(db.Text, nullable=True)
    week = db.Column(db.Integer, nullable=True)
    season_year = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    player = db.relationship("Player", back_populates="injuries")
    team = db.relationship("Team", back_populates="injuries")
