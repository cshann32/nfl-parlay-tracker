from datetime import datetime, timezone
from app.extensions import db


class Odds(db.Model):
    __tablename__ = "odds"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    source = db.Column(db.String(100), nullable=True)         # DraftKings, FanDuel, etc.
    market_type = db.Column(db.String(50), nullable=True)     # moneyline / spread / total
    home_moneyline = db.Column(db.Integer, nullable=True)     # American odds
    away_moneyline = db.Column(db.Integer, nullable=True)
    home_spread = db.Column(db.Numeric(5, 1), nullable=True)  # e.g. -3.5
    away_spread = db.Column(db.Numeric(5, 1), nullable=True)
    spread_juice_home = db.Column(db.Integer, nullable=True)  # Juice on spread (American)
    spread_juice_away = db.Column(db.Integer, nullable=True)
    over_under = db.Column(db.Numeric(5, 1), nullable=True)
    over_juice = db.Column(db.Integer, nullable=True)
    under_juice = db.Column(db.Integer, nullable=True)
    synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    game = db.relationship("Game", back_populates="odds")
    history = db.relationship("OddsHistory", back_populates="odds_record", lazy="dynamic",
                              cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Odds game={self.game_id} {self.market_type} {self.source}>"


class OddsHistory(db.Model):
    __tablename__ = "odds_history"

    id = db.Column(db.Integer, primary_key=True)
    odds_id = db.Column(db.Integer, db.ForeignKey("odds.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    odds_type = db.Column(db.String(50), nullable=True)
    value = db.Column(db.Numeric(10, 4), nullable=True)
    recorded_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    odds_record = db.relationship("Odds", back_populates="history")
