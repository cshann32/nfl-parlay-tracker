from datetime import datetime, timezone
from app.extensions import db


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    abbreviation = db.Column(db.String(10), nullable=True, index=True)
    city = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(150), nullable=True)
    conference = db.Column(db.String(10), nullable=True)   # AFC / NFC
    division = db.Column(db.String(20), nullable=True)     # North / South / East / West
    logo_url = db.Column(db.String(500), nullable=True)
    primary_color = db.Column(db.String(10), nullable=True)
    secondary_color = db.Column(db.String(10), nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    players = db.relationship("Player", back_populates="team", lazy="dynamic")
    coaches = db.relationship("Coach", back_populates="team", lazy="dynamic",
                              cascade="all, delete-orphan")
    venue = db.relationship("Venue", back_populates="team", uselist=False,
                            cascade="all, delete-orphan")
    injuries = db.relationship("Injury", back_populates="team", lazy="dynamic",
                               cascade="all, delete-orphan")
    depth_charts = db.relationship("DepthChart", back_populates="team", lazy="dynamic",
                                   cascade="all, delete-orphan")
    home_games = db.relationship("Game", foreign_keys="Game.home_team_id",
                                 back_populates="home_team", lazy="dynamic")
    away_games = db.relationship("Game", foreign_keys="Game.away_team_id",
                                 back_populates="away_team", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Team {self.abbreviation or self.name}>"
