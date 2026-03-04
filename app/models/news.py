from datetime import datetime, timezone
from app.extensions import db


class News(db.Model):
    __tablename__ = "news"

    id = db.Column(db.Integer, primary_key=True)
    headline = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, nullable=True)
    link = db.Column(db.String(1000), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="SET NULL"), nullable=True, index=True)
    image_url = db.Column(db.String(1000), nullable=True)
    api_id = db.Column(db.String(200), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
