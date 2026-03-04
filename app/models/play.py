from datetime import datetime, timezone
from app.extensions import db


class Play(db.Model):
    __tablename__ = "plays"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"),
                        nullable=True)
    sequence = db.Column(db.Integer, nullable=True)
    quarter = db.Column(db.Integer, nullable=True)
    clock = db.Column(db.String(20), nullable=True)     # e.g. "10:32"
    play_type = db.Column(db.String(50), nullable=True) # rush / pass / punt / kick / etc.
    description = db.Column(db.Text, nullable=True)
    yards_gained = db.Column(db.Integer, nullable=True)
    down = db.Column(db.Integer, nullable=True)
    distance = db.Column(db.Integer, nullable=True)     # yards to first down
    is_scoring = db.Column(db.Boolean, default=False)
    score_type = db.Column(db.String(30), nullable=True) # TD / FG / Safety / PAT
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    game = db.relationship("Game", back_populates="plays")
