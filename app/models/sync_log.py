import enum
from datetime import datetime, timezone
from app.extensions import db


class SyncStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"   # completed but with some errors
    FAILED = "failed"


class SyncLog(db.Model):
    __tablename__ = "sync_logs"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False, index=True)  # teams / players / games / etc.
    started_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    records_fetched = db.Column(db.Integer, nullable=True, default=0)
    records_inserted = db.Column(db.Integer, nullable=True, default=0)
    records_updated = db.Column(db.Integer, nullable=True, default=0)
    records_skipped = db.Column(db.Integer, nullable=True, default=0)
    errors = db.Column(db.JSON, nullable=True)     # List of {endpoint, error} dicts
    status = db.Column(
        db.Enum(SyncStatus, name='syncstatus', create_type=False,
                values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=SyncStatus.RUNNING,
    )
    triggered_by = db.Column(db.String(50), nullable=True)  # admin_panel / cli / scheduler

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def __repr__(self) -> str:
        return f"<SyncLog {self.category} {self.status.value} @ {self.started_at}>"
