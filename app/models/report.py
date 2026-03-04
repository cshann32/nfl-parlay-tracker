from datetime import datetime, timezone
from app.extensions import db


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    # config stores filter criteria as JSON: date_range, teams, players, stat_types, etc.
    config = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_run_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="reports")

    def __repr__(self) -> str:
        return f"<Report '{self.name}' user={self.user_id}>"
