from datetime import datetime, timezone
from app.extensions import db


class DepthChart(db.Model):
    __tablename__ = "depth_charts"
    __table_args__ = (
        db.UniqueConstraint("team_id", "player_id", "position", "unit", name="uq_depth_chart"),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    position = db.Column(db.String(20), nullable=True)
    depth_order = db.Column(db.Integer, nullable=True)      # 1 = starter, 2 = backup, etc.
    unit = db.Column(db.String(20), nullable=True)           # offense / defense / special
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    team = db.relationship("Team", back_populates="depth_charts")
    player = db.relationship("Player", back_populates="depth_chart_entries")
