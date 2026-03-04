from datetime import datetime, timezone
from app.extensions import db


class Coach(db.Model):
    __tablename__ = "coaches"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    title = db.Column(db.String(100), nullable=True)
    experience = db.Column(db.Integer, nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    team = db.relationship("Team", back_populates="coaches")

    def __repr__(self) -> str:
        return f"<Coach {self.name} ({self.title})>"
