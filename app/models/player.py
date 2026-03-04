from datetime import datetime, timezone
from app.extensions import db


class Player(db.Model):
    __tablename__ = "players"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    position = db.Column(db.String(20), nullable=True, index=True)
    jersey_number = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), nullable=True)       # Active / Injured / Practice Squad
    height = db.Column(db.String(20), nullable=True)       # e.g. "6'2\""
    weight = db.Column(db.Integer, nullable=True)          # lbs
    age = db.Column(db.Integer, nullable=True)
    college = db.Column(db.String(150), nullable=True)
    experience = db.Column(db.Integer, nullable=True)      # years in NFL
    image_url = db.Column(db.String(500), nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    team = db.relationship("Team", back_populates="players")
    stats = db.relationship("PlayerStat", back_populates="player", lazy="dynamic",
                            cascade="all, delete-orphan")
    injuries = db.relationship("Injury", back_populates="player", lazy="dynamic",
                               cascade="all, delete-orphan")
    depth_chart_entries = db.relationship("DepthChart", back_populates="player", lazy="dynamic",
                                          cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Player {self.name} ({self.position})>"
