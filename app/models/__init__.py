"""
Import all models so Alembic and Flask-Migrate can detect them.
"""
from app.models.user import User, UserRole
from app.models.season import Season
from app.models.team import Team
from app.models.coach import Coach
from app.models.venue import Venue
from app.models.player import Player
from app.models.game import Game
from app.models.stat import PlayerStat, TeamStat
from app.models.odds import Odds, OddsHistory
from app.models.scoreboard import Scoreboard
from app.models.boxscore import Boxscore
from app.models.play import Play
from app.models.injury import Injury
from app.models.depth_chart import DepthChart
from app.models.draft import Draft
from app.models.news import News
from app.models.parlay import Parlay, ParlayLeg, ParlayStatus, LegType, LegResult
from app.models.document import Document, ParseStatus
from app.models.report import Report
from app.models.sync_log import SyncLog, SyncStatus
from app.models.app_setting import AppSetting

__all__ = [
    "User", "UserRole",
    "Season",
    "Team",
    "Coach",
    "Venue",
    "Player",
    "Game",
    "PlayerStat", "TeamStat",
    "Odds", "OddsHistory",
    "Scoreboard",
    "Boxscore",
    "Play",
    "Injury",
    "DepthChart",
    "Draft",
    "News",
    "Parlay", "ParlayLeg", "ParlayStatus", "LegType", "LegResult",
    "Document", "ParseStatus",
    "Report",
    "SyncLog", "SyncStatus",
    "AppSetting",
]
