from datetime import datetime, timezone
from app.extensions import db


class AppSetting(db.Model):
    """Key/value store for runtime app settings (scheduler config, etc.)."""
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.String(1000), nullable=True)
    description = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key: str, value: str, description: str | None = None) -> None:
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = cls(key=key, value=value, description=description)
            db.session.add(row)
        db.session.commit()

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value}>"
