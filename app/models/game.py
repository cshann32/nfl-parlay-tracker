from datetime import datetime, timezone
from app.extensions import db


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    home_team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"),
                             nullable=True, index=True)
    away_team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"),
                             nullable=True, index=True)
    venue_id = db.Column(db.Integer, db.ForeignKey("venues.id", ondelete="SET NULL"),
                         nullable=True)
    week = db.Column(db.Integer, nullable=True, index=True)
    season_year = db.Column(db.Integer, nullable=True, index=True)
    season_type = db.Column(db.String(50), nullable=True)    # Regular / Postseason / Preseason
    game_date = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), nullable=True, index=True)  # Scheduled / InProgress / Final
    neutral_site = db.Column(db.Boolean, default=False)
    broadcast = db.Column(db.String(100), nullable=True)
    attendance = db.Column(db.Integer, nullable=True)
    api_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    season = db.relationship("Season", back_populates="games")
    home_team = db.relationship("Team", foreign_keys=[home_team_id], back_populates="home_games")
    away_team = db.relationship("Team", foreign_keys=[away_team_id], back_populates="away_games")
    player_stats = db.relationship("PlayerStat", back_populates="game", lazy="dynamic",
                                   cascade="all, delete-orphan")
    team_stats = db.relationship("TeamStat", back_populates="game", lazy="dynamic",
                                 cascade="all, delete-orphan")
    odds = db.relationship("Odds", back_populates="game", lazy="dynamic",
                           cascade="all, delete-orphan")
    boxscore = db.relationship("Boxscore", back_populates="game", uselist=False,
                               cascade="all, delete-orphan")
    plays = db.relationship("Play", back_populates="game", lazy="dynamic",
                            cascade="all, delete-orphan")
    scoreboard_entries = db.relationship("Scoreboard", back_populates="game", lazy="dynamic",
                                         cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Game {self.away_team_id}@{self.home_team_id} W{self.week} {self.season_year}>"
