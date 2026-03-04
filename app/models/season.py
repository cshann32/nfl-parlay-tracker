from datetime import datetime, timezone
from app.extensions import db


class Season(db.Model):
    __tablename__ = "seasons"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    season_type = db.Column(db.String(50), nullable=True)   # Regular, Preseason, Postseason
    name = db.Column(db.String(100), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    games = db.relationship("Game", back_populates="season", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Season {self.year} {self.season_type}>"
