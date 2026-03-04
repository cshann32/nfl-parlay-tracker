from datetime import datetime, timezone
from app.extensions import db


class PlayerStat(db.Model):
    __tablename__ = "player_stats"
    __table_args__ = (
        db.UniqueConstraint("player_id", "game_id", "stat_category", "stat_type",
                            name="uq_player_stat"),
    )

    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=True, index=True)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id", ondelete="SET NULL"),
                          nullable=True)
    season_year = db.Column(db.Integer, nullable=True)
    week = db.Column(db.Integer, nullable=True)
    stat_category = db.Column(db.String(50), nullable=False)  # passing / rushing / receiving / defense
    stat_type = db.Column(db.String(100), nullable=False)     # yards / touchdowns / completions / etc.
    value = db.Column(db.Numeric(12, 4), nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    player = db.relationship("Player", back_populates="stats")
    game = db.relationship("Game", back_populates="player_stats")

    def __repr__(self) -> str:
        return f"<PlayerStat player={self.player_id} {self.stat_category}.{self.stat_type}={self.value}>"


class TeamStat(db.Model):
    __tablename__ = "team_stats"
    __table_args__ = (
        db.UniqueConstraint("team_id", "game_id", "stat_category", "stat_type",
                            name="uq_team_stat"),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=True, index=True)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id", ondelete="SET NULL"),
                          nullable=True)
    season_year = db.Column(db.Integer, nullable=True)
    week = db.Column(db.Integer, nullable=True)
    stat_category = db.Column(db.String(50), nullable=False)
    stat_type = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Numeric(12, 4), nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    team = db.relationship("Team")
    game = db.relationship("Game", back_populates="team_stats")

    def __repr__(self) -> str:
        return f"<TeamStat team={self.team_id} {self.stat_category}.{self.stat_type}={self.value}>"
