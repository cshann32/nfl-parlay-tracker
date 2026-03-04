import enum
from datetime import datetime, timezone
from app.extensions import db


class ParlayStatus(str, enum.Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    PUSH = "push"
    PARTIAL = "partial"  # some legs push


class LegType(str, enum.Enum):
    SPREAD = "spread"
    MONEYLINE = "moneyline"
    TOTAL = "total"       # Over/Under
    PLAYER_PROP = "player_prop"
    TEAM_PROP = "team_prop"
    PARLAY = "parlay"     # SGP leg


class LegResult(str, enum.Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    PUSH = "push"


class Parlay(db.Model):
    __tablename__ = "parlays"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    name = db.Column(db.String(200), nullable=True)
    bet_date = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    bet_amount = db.Column(db.Numeric(10, 2), nullable=False)
    potential_payout = db.Column(db.Numeric(10, 2), nullable=True)
    actual_payout = db.Column(db.Numeric(10, 2), nullable=True, default=0)
    status = db.Column(db.Enum(ParlayStatus, name='parlaystatustype', create_type=False, native_enum=False, values_callable=lambda x: [m.value for m in x]), nullable=False, default=ParlayStatus.PENDING, index=True)
    sportsbook = db.Column(db.String(100), nullable=True)   # DraftKings / FanDuel / etc.
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", back_populates="parlays")
    legs = db.relationship("ParlayLeg", back_populates="parlay", lazy="joined",
                           cascade="all, delete-orphan", order_by="ParlayLeg.id")

    @property
    def profit_loss(self) -> float:
        if self.status == ParlayStatus.WON:
            return float(self.actual_payout or 0) - float(self.bet_amount)
        elif self.status == ParlayStatus.LOST:
            return -float(self.bet_amount)
        return 0.0

    @property
    def leg_count(self) -> int:
        return len(self.legs)

    def __repr__(self) -> str:
        return f"<Parlay id={self.id} ${self.bet_amount} {self.status.value}>"


class ParlayLeg(db.Model):
    __tablename__ = "parlay_legs"

    id = db.Column(db.Integer, primary_key=True)
    parlay_id = db.Column(db.Integer, db.ForeignKey("parlays.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id", ondelete="SET NULL"), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    leg_type = db.Column(db.Enum(LegType, name='legtype', create_type=False, native_enum=False, values_callable=lambda x: [m.value for m in x]), nullable=False)
    pick = db.Column(db.String(500), nullable=False)     # Human-readable: "Chiefs -3.5"
    odds = db.Column(db.Integer, nullable=True)          # American odds: -110, +150
    result = db.Column(db.Enum(LegResult, name='legresult', create_type=False, native_enum=False, values_callable=lambda x: [m.value for m in x]), nullable=False, default=LegResult.PENDING)
    description = db.Column(db.Text, nullable=True)

    parlay = db.relationship("Parlay", back_populates="legs")
    game = db.relationship("Game")
    player = db.relationship("Player")
    team = db.relationship("Team")

    def __repr__(self) -> str:
        return f"<ParlayLeg {self.leg_type.value}: {self.pick} @ {self.odds}>"
