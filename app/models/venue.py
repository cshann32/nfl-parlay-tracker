from datetime import datetime, timezone
from app.extensions import db


class Venue(db.Model):
    __tablename__ = "venues"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    country = db.Column(db.String(50), nullable=True)
    capacity = db.Column(db.Integer, nullable=True)
    surface = db.Column(db.String(50), nullable=True)    # Grass / FieldTurf / etc.
    roof_type = db.Column(db.String(50), nullable=True)  # Open / Dome / Retractable
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    team = db.relationship("Team", back_populates="venue")

    def __repr__(self) -> str:
        return f"<Venue {self.name}>"
